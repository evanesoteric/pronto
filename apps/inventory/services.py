"""
Inventory services — the ledger mutation layer.

The ledger (StockMovement) is the source of truth. InventoryLot.quantity_on_hand
is a denormalized cache updated only here, inside atomic transactions, with
row-level locks. Every function that writes to the cache uses F() expressions
so the arithmetic happens in SQL, not Python.

Never write to InventoryLot.quantity_on_hand outside this module.
Corrections are made by writing opposing movements, never by updating rows.

See docs/TRANSACTIONS.md for the locking discipline.
See docs/ARCHITECTURE.md for the ground rules.
"""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from apps.core.models import User
from apps.barcodes.signals import emit
from .models import (
    InventoryLot, Item, MovementReason, StockMovement,
)


class InsufficientStock(ValidationError):
    """Raised when a consume or adjustment would drive a lot negative."""

    def __str__(self):
        return " ".join(self.messages) if hasattr(self, "messages") else super().__str__()

# ---------------------------------------------------------------------------
# Receiving
# ---------------------------------------------------------------------------

@transaction.atomic
def receive_stock(
    *,
    item: Item,
    facility,
    lot_number: str,
    quantity: Decimal,
    unit_cost: Decimal,
    performed_by: User,
    received_at=None,
    expires_at=None,
    reference: str = "",
    note: str = "",
    auto_print_label: bool = True,
) -> StockMovement:
    """
    Receive raw material, packaging, or finished goods into inventory.

    If a lot with this (item, lot_number, facility) already exists, the
    receipt is added to it. Otherwise a new lot is created.

    Returns the StockMovement written. Emits `inventory.lot.received`
    which the barcodes handlers use to queue a print job.
    """
    if quantity <= 0:
        raise ValidationError("Quantity must be positive.")
    if unit_cost < 0:
        raise ValidationError("Unit cost cannot be negative.")

    lot, created = InventoryLot.objects.select_for_update().get_or_create(
        item=item,
        facility=facility,
        lot_number=lot_number,
        defaults={
            "unit_cost": unit_cost,
            "received_at": received_at or timezone.now(),
            "expires_at": expires_at,
        },
    )

    # If the lot already existed but had no cost, set it on first receipt.
    if not created and lot.unit_cost == 0 and unit_cost > 0:
        lot.unit_cost = unit_cost
        lot.save(update_fields=["unit_cost", "updated_at"])

    movement = StockMovement.objects.create(
        lot=lot,
        delta=quantity,
        reason=MovementReason.RECEIPT,
        reference=reference,
        performed_by=performed_by,
        note=note,
    )
    _apply_movement_to_lot_cache(lot, quantity)

    if auto_print_label and created:
        emit("inventory.lot.received", lot=lot, copies=1)

    return movement


# ---------------------------------------------------------------------------
# Consumption — the two paths
# ---------------------------------------------------------------------------

@transaction.atomic
def consume_stock(
    *,
    lot: InventoryLot,
    quantity: Decimal,
    reason: str,
    performed_by: User,
    batch=None,
    order_line=None,
    reference: str = "",
    note: str = "",
) -> StockMovement:
    """
    Remove quantity from a specific lot.

    Locks the lot row and validates sufficiency against the locked value.
    Raises InsufficientStock if the lot doesn't have enough.
    """
    if quantity <= 0:
        raise ValidationError("Quantity must be positive.")

    lot = InventoryLot.objects.select_for_update().get(pk=lot.pk)
    if lot.quantity_on_hand < quantity:
        raise InsufficientStock(
            f"Lot {lot.lot_number} has {lot.quantity_on_hand} {lot.item.unit}; "
            f"cannot consume {quantity}."
        )

    movement = StockMovement.objects.create(
        lot=lot,
        delta=-quantity,
        reason=reason,
        batch=batch,
        order_line=order_line,
        reference=reference,
        performed_by=performed_by,
        note=note,
    )
    _apply_movement_to_lot_cache(lot, -quantity)
    return movement


@transaction.atomic
def consume_fifo(
    *,
    item: Item,
    facility,
    quantity: Decimal,
    reason: str,
    performed_by: User,
    batch=None,
    order_line=None,
    reference: str = "",
) -> list[StockMovement]:
    """
    Consume a total quantity from oldest-expiring lots first (FIFO/FEFO).

    Splits across lots as needed, returns one movement per lot touched.
    If the total on hand across all lots is insufficient, raises
    InsufficientStock and — because of @transaction.atomic — rolls back
    every partial consumption already written in this call.
    """
    if quantity <= 0:
        raise ValidationError("Quantity must be positive.")

    remaining = quantity
    movements: list[StockMovement] = []

    lots = (
        InventoryLot.objects
        .select_for_update()
        .filter(item=item, facility=facility, quantity_on_hand__gt=0)
        .order_by(
            F("expires_at").asc(nulls_last=True),
            F("received_at").asc(nulls_last=True),
            "id",
        )
    )

    for lot in lots:
        if remaining <= 0:
            break
        take = min(lot.quantity_on_hand, remaining)
        movements.append(consume_stock(
            lot=lot,
            quantity=take,
            reason=reason,
            performed_by=performed_by,
            batch=batch,
            order_line=order_line,
            reference=reference,
        ))
        remaining -= take

    if remaining > 0:
        # The transaction rolls back, undoing any partial consumption above.
        raise InsufficientStock(
            f"Not enough {item.sku} at {facility.code}: "
            f"short by {remaining} {item.unit}."
        )
    return movements


# ---------------------------------------------------------------------------
# Adjustments (cycle count, shrinkage, corrections)
# ---------------------------------------------------------------------------

@transaction.atomic
def adjust_stock(
    *,
    lot: InventoryLot,
    delta: Decimal,
    performed_by: User,
    reason: str = MovementReason.ADJUSTMENT,
    note: str = "",
) -> StockMovement:
    """
    Write a correction movement. delta may be positive or negative.

    Used for cycle counts, shrinkage, and reversing mistakes. Never
    update an existing movement — always write an opposing one.
    """
    if delta == 0:
        raise ValidationError("Adjustment delta cannot be zero.")

    lot = InventoryLot.objects.select_for_update().get(pk=lot.pk)
    if lot.quantity_on_hand + delta < 0:
        raise InsufficientStock(
            f"Adjustment would drive lot {lot.lot_number} negative "
            f"({lot.quantity_on_hand} + {delta})."
        )

    movement = StockMovement.objects.create(
        lot=lot,
        delta=delta,
        reason=reason,
        performed_by=performed_by,
        note=note,
    )
    _apply_movement_to_lot_cache(lot, delta)
    return movement


# ---------------------------------------------------------------------------
# Internal — the ONLY place quantity_on_hand is written
# ---------------------------------------------------------------------------

def _apply_movement_to_lot_cache(lot: InventoryLot, delta: Decimal) -> None:
    """
    Atomically add `delta` to the lot's cached quantity.

    Uses F() so the arithmetic happens in SQL. Combined with the
    select_for_update() lock the caller holds, this cannot race.
    """
    InventoryLot.objects.filter(pk=lot.pk).update(
        quantity_on_hand=F("quantity_on_hand") + delta,
        updated_at=timezone.now(),
    )
    lot.refresh_from_db(fields=["quantity_on_hand"])
