from decimal import Decimal
from django.db.models import Sum, F, DecimalField, ExpressionWrapper, Q

from .models import BatchCost, JournalEntry, GLAccount


def cogs_for_period(facility, year, month):
    return (
        JournalEntry.objects
        .filter(
            facility=facility,
            posted_at__year=year, posted_at__month=month,
            lines__account=GLAccount.COGS,
        )
        .aggregate(t=Sum("lines__debit"))["t"] or Decimal("0")
    )


def margin_by_item(facility, since=None):
    """
    Revenue − COGS per finished item, using shipped allocations and
    their frozen batch costs.
    """
    from apps.sales.models import StockAllocation

    qs = StockAllocation.objects.filter(
        released_at__isnull=False,
        order_line__order__facility=facility,
    )
    if since:
        qs = qs.filter(released_at__gte=since)

    rows = {}
    for a in qs.select_related("order_line__item", "lot__item"):
        item = a.order_line.item
        revenue = a.quantity * a.order_line.unit_price
        cogs = a.quantity * a.lot.unit_cost
        agg = rows.setdefault(item.sku, {
            "sku": item.sku, "name": item.name,
            "revenue": Decimal("0"), "cogs": Decimal("0"),
        })
        agg["revenue"] += revenue
        agg["cogs"] += cogs
    for r in rows.values():
        r["margin"] = r["revenue"] - r["cogs"]
        r["margin_pct"] = (
            (r["margin"] / r["revenue"] * 100).quantize(Decimal("0.01"))
            if r["revenue"] else Decimal("0")
        )
    return list(rows.values())
