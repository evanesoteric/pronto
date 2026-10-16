from django.db.models import Sum, F, DecimalField, ExpressionWrapper, Q
from .models import Order, OrderStatus, StockAllocation


def open_orders(facility=None):
    qs = Order.objects.exclude(
        status__in=[OrderStatus.FULFILLED, OrderStatus.INVOICED, OrderStatus.CANCELLED]
    ).select_related("customer", "facility")
    return qs.filter(facility=facility) if facility else qs


def lot_available_quantity(lot):
    """
    On-hand minus open allocations. This is the number a salesperson
    should see when promising stock.
    """
    from apps.inventory.models import InventoryLot
    from .models import StockAllocation
    from decimal import Decimal

    allocated = (
        StockAllocation.objects
        .filter(lot=lot, released_at__isnull=True)
        .aggregate(t=Sum("quantity"))["t"] or Decimal("0")
    )
    return lot.quantity_on_hand - allocated


def customer_revenue(customer, since=None):
    qs = StockAllocation.objects.filter(
        order_line__order__customer=customer, released_at__isnull=False,
    )
    if since:
        qs = qs.filter(released_at__gte=since)
    return sum(
        (a.quantity * a.order_line.unit_price for a in qs.select_related("order_line")),
        0,
    )
