# apps/sales/selectors.py
from decimal import Decimal

from django.db.models import Sum

from .models import Order, OrderStatus, StockAllocation


def open_orders(facility=None):
    """Orders not yet fulfilled, invoiced, or cancelled."""
    qs = (
        Order.objects
        .exclude(status__in=[
            OrderStatus.FULFILLED,
            OrderStatus.INVOICED,
            OrderStatus.CANCELLED,
        ])
        .select_related("customer", "facility")
        .order_by("-order_date")
    )
    if facility is not None:
        qs = qs.filter(facility=facility)
    return qs


def closed_orders(facility=None):
    """
    Orders that are fulfilled, invoiced, or cancelled.

    Returns an unsliced queryset. The caller is responsible for
    slicing AFTER any additional filters — Django refuses .filter()
    on a queryset that has already been sliced.
    """
    qs = (
        Order.objects
        .filter(status__in=[
            OrderStatus.FULFILLED,
            OrderStatus.INVOICED,
            OrderStatus.CANCELLED,
        ])
        .select_related("customer", "facility")
        .order_by("-order_date")
    )
    if facility is not None:
        qs = qs.filter(facility=facility)
    return qs


def lot_available_quantity(lot) -> Decimal:
    """
    On-hand minus open allocations. What a salesperson should see
    when promising stock.
    """
    allocated = (
        StockAllocation.objects
        .filter(lot=lot, released_at__isnull=True)
        .aggregate(t=Sum("quantity"))["t"]
        or Decimal("0")
    )
    return lot.quantity_on_hand - allocated


def order_fill_summary(order):
    """
    For each line, how much is allocated vs. ordered.
    """
    rows = []
    for line in order.lines.select_related("item").all():
        allocated = line.allocated_quantity
        rows.append({
            "line": line,
            "item": line.item,
            "ordered": line.quantity,
            "allocated": allocated,
            "remaining": line.quantity - allocated,
            "filled": allocated >= line.quantity,
            "backordered": line.backordered,
        })
    return rows


def customer_order_history(customer, limit=50):
    return (
        Order.objects
        .filter(customer=customer)
        .select_related("facility")
        .order_by("-order_date")[:limit]
    )
