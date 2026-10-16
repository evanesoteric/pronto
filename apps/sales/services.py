from decimal import Decimal
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.core.models import User
from apps.inventory import services as inventory_services
from apps.inventory.models import InventoryLot, MovementReason
from .models import (
    Customer, Order, OrderLine, OrderStatus, StockAllocation,
)


class OrderStateError(ValidationError):
    pass


# ---------------------------------------------------------------------------
# Order lifecycle
# ---------------------------------------------------------------------------

@transaction.atomic
def create_order(
    *,
    customer: Customer,
    facility,
    number: str,
    order_date,
    lines: list[dict],
    performed_by: User,
    ship_by=None,
    notes: str = "",
) -> Order:
    """
    lines: [{"item": Item, "quantity": Decimal, "unit_price": Decimal}, ...]
    """
    order = Order.objects.create(
        number=number, customer=customer, facility=facility,
        order_date=order_date, ship_by=ship_by, notes=notes,
    )
    for line in lines:
        OrderLine.objects.create(
            order=order, item=line["item"],
            quantity=line["quantity"], unit_price=line["unit_price"],
        )
    return order


@transaction.atomic
def confirm_order(*, order: Order, performed_by: User) -> Order:
    order = Order.objects.select_for_update().get(pk=order.pk)
    if order.status != OrderStatus.DRAFT:
        raise OrderStateError(f"Cannot confirm from '{order.status}'.")
    order.status = OrderStatus.CONFIRMED
    order.save(update_fields=["status", "updated_at"])
    return order


@transaction.atomic
def allocate_order(*, order: Order, performed_by: User) -> Order:
    """
    Reserve finished-good lots (FIFO) for every line. Does NOT move stock.
    Partial allocation is allowed — lines that can't be fully filled are
    marked backordered and allocation proceeds with what's available.
    """
    order = Order.objects.select_for_update().get(pk=order.pk)
    if order.status not in (OrderStatus.CONFIRMED, OrderStatus.ALLOCATED):
        raise OrderStateError(f"Cannot allocate from '{order.status}'.")

    for line in order.lines.select_related("item").all():
        needed = line.remaining_to_ship
        if needed <= 0:
            continue

        lots = (
            InventoryLot.objects
            .select_for_update()
            .filter(item=line.item, facility=order.facility, quantity_on_hand__gt=0)
            .order_by("expires_at", "received_at", "id")
        )

        for lot in lots:
            if needed <= 0:
                break
            available = lot.quantity_on_hand - _open_allocated_quantity(lot)
            if available <= 0:
                continue
            take = min(available, needed)
            StockAllocation.objects.create(
                order_line=line, lot=lot, quantity=take,
            )
            needed -= take

        line.backordered = needed > 0
        line.save(update_fields=["backordered", "updated_at"])

    order.status = OrderStatus.ALLOCATED
    order.save(update_fields=["status", "updated_at"])
    return order


@transaction.atomic
def ship_order(*, order: Order, performed_by: User) -> Order:
    """
    Consume the allocated lots and flip the order to FULFILLED.
    Any line that's still short is shipped as-is; the remainder stays
    backordered on the order for a future shipment.
    """
    order = Order.objects.select_for_update().get(pk=order.pk)
    if order.status != OrderStatus.ALLOCATED:
        raise OrderStateError(f"Cannot ship from '{order.status}'.")

    now = timezone.now()
    for line in order.lines.all():
        for alloc in line.allocations.filter(released_at__isnull=True).select_related("lot"):
            inventory_services.consume_stock(
                lot=alloc.lot,
                quantity=alloc.quantity,
                reason=MovementReason.SHIPMENT,
                performed_by=performed_by,
                order_line=line,
                reference=f"ship:{order.number}",
            )
            alloc.released_at = now
            alloc.save(update_fields=["released_at", "updated_at"])

    order.status = OrderStatus.FULFILLED
    order.shipped_at = now
    order.save(update_fields=["status", "shipped_at", "updated_at"])
    return order


@transaction.atomic
def cancel_order(*, order: Order, performed_by: User) -> Order:
    order = Order.objects.select_for_update().get(pk=order.pk)
    if order.status == OrderStatus.FULFILLED:
        raise OrderStateError("Cannot cancel a fulfilled order; issue a return instead.")
    StockAllocation.objects.filter(
        order_line__order=order, released_at__isnull=True,
    ).update(released_at=timezone.now())
    order.status = OrderStatus.CANCELLED
    order.save(update_fields=["status", "updated_at"])
    return order


def _open_allocated_quantity(lot: InventoryLot) -> Decimal:
    return (
        StockAllocation.objects
        .filter(lot=lot, released_at__isnull=True)
        .aggregate(t=Sum("quantity"))["t"] or Decimal("0")
    )
