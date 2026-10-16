"""
Inventory read helpers.

No mutations here. Every function returns querysets or plain data.
"""
from decimal import Decimal

from django.db.models import (
    DecimalField, ExpressionWrapper, F, Q, Sum,
)

from .models import InventoryLot, Item, MovementReason, StockMovement


def inventory_value_by_facility(facility) -> Decimal:
    """Total $ value of on-hand inventory at a facility."""
    expr = ExpressionWrapper(
        F("quantity_on_hand") * F("unit_cost"),
        output_field=DecimalField(max_digits=18, decimal_places=4),
    )
    return (
        InventoryLot.objects
        .filter(facility=facility)
        .aggregate(total=Sum(expr))["total"]
        or Decimal("0")
    )


def lot_history(lot):
    """All movements for a lot, oldest first."""
    return (
        StockMovement.objects
        .filter(lot=lot)
        .select_related("performed_by", "batch")
        .order_by("created_at")
    )


def low_stock_items(facility=None):
    """
    Items whose on-hand (optionally scoped to a facility) is below
    their reorder_point. Items with zero on hand are included if their
    reorder_point is > 0.
    """
    lot_filter = Q(lots__quantity_on_hand__gt=0)
    if facility is not None:
        lot_filter &= Q(lots__facility=facility)

    return (
        Item.objects
        .filter(is_active=True, reorder_point__gt=0)
        .annotate(
            on_hand=Sum("lots__quantity_on_hand", filter=lot_filter),
        )
        .filter(Q(on_hand__lt=F("reorder_point")) | Q(on_hand__isnull=True))
        .order_by("sku")
    )


def ledger_reconciliation():
    """
    Yield (lot, cached_qty, ledger_qty) for each lot where the cache has
    drifted from the sum of its movements.

    Run nightly via the reconcile_inventory command.
    """
    for lot in InventoryLot.objects.with_balance():
        ledger = lot.ledger_balance or Decimal("0")
        if lot.quantity_on_hand != ledger:
            yield lot, lot.quantity_on_hand, ledger
