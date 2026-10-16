"""
Production read helpers.
"""
from decimal import Decimal

from django.db.models import Sum

from .models import Batch, BatchStatus, Tank


def active_batches(facility=None):
    """Batches not yet closed or cancelled, newest first."""
    qs = (
        Batch.objects
        .exclude(status__in=[BatchStatus.CLOSED, BatchStatus.CANCELLED])
        .select_related("recipe", "tank", "facility")
        .order_by("-created_at")
    )
    if facility is not None:
        qs = qs.filter(facility=facility)
    return qs


def batch_consumption(batch):
    """Total quantity consumed per item for a batch."""
    return (
        batch.movements
        .filter(delta__lt=0)
        .values("lot__item__sku", "lot__item__name", "lot__item__unit")
        .annotate(total=Sum("delta"))
        .order_by("lot__item__sku")
    )


def batch_cost(batch) -> Decimal:
    """Rolled-up ingredient cost for a batch."""
    total = Decimal("0")
    for m in batch.movements.filter(delta__lt=0).select_related("lot"):
        total += m.lot.unit_cost * -m.delta
    return total.quantize(Decimal("0.0001"))


def tank_utilization(facility):
    """Tanks at a facility, annotated with the number of active batches."""
    from django.db.models import Count, Q
    active_statuses = [
        BatchStatus.BREWING, BatchStatus.FERMENTING, BatchStatus.CONDITIONING,
    ]
    return (
        Tank.objects.filter(facility=facility)
        .annotate(
            active_batch_count=Count(
                "batches",
                filter=Q(batches__status__in=active_statuses),
            ),
        )
        .order_by("name")
    )
