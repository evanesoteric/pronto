from decimal import Decimal
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.core.models import User
from apps.inventory.models import MovementReason, StockMovement
from apps.production.models import Batch, BatchStatus
from .models import (
    AccountingPeriod, BatchCost, GLAccount,
    JournalEntry, JournalLine,
)


class FinanceError(ValidationError):
    pass


# ---------------------------------------------------------------------------
# Journal entry posting
# ---------------------------------------------------------------------------

@transaction.atomic
def post_entry(*, facility, memo: str, lines: list[dict], performed_by: User,
               reference: str = "") -> JournalEntry:
    """
    lines: [{"account": GLAccount.X, "debit": D, "credit": C, "description": "..."}]
    Validates balance before writing.
    """
    total_debit = sum((l.get("debit", Decimal("0")) for l in lines), Decimal("0"))
    total_credit = sum((l.get("credit", Decimal("0")) for l in lines), Decimal("0"))
    if total_debit != total_credit:
        raise FinanceError(
            f"Entry does not balance: debits={total_debit} credits={total_credit}."
        )

    period = _current_open_period(facility)
    if period.is_closed:
        raise FinanceError(f"Period {period.year}-{period.month:02d} is closed.")

    entry = JournalEntry.objects.create(
        facility=facility, memo=memo, reference=reference,
        posted_at=timezone.now(),
    )
    for l in lines:
        JournalLine.objects.create(
            entry=entry,
            account=l["account"],
            debit=l.get("debit", Decimal("0")),
            credit=l.get("credit", Decimal("0")),
            description=l.get("description", ""),
        )
    return entry


# ---------------------------------------------------------------------------
# Batch cost rollup
# ---------------------------------------------------------------------------

@transaction.atomic
def rollup_batch_cost(*, batch: Batch, performed_by: User) -> BatchCost:
    """
    Freeze the COGS for a batch. Idempotent: OneToOne on batch.
    """
    batch = Batch.objects.select_for_update().get(pk=batch.pk)
    if batch.status not in (BatchStatus.PACKAGED, BatchStatus.CLOSED):
        raise FinanceError("Only packaged or closed batches can be costed.")

    if hasattr(batch, "cost"):
        return batch.cost

    movements = (
        batch.movements
        .filter(delta__lt=0)
        .select_related("lot")
    )
    total = sum(
        (m.lot.unit_cost * -m.delta for m in movements),
        Decimal("0"),
    ).quantize(Decimal("0.0001"))

    volume = batch.actual_volume_liters or batch.planned_volume_liters
    cost_per_liter = (
        (total / volume).quantize(Decimal("0.0001")) if volume else Decimal("0")
    )

    # WIP → FG journal entry
    entry = post_entry(
        facility=batch.facility,
        memo=f"Batch {batch.batch_number} cost rollup",
        reference=f"batch:{batch.batch_number}",
        performed_by=performed_by,
        lines=[
            {"account": GLAccount.INVENTORY_FG, "debit": total,
             "description": f"Capitalize batch {batch.batch_number}"},
            {"account": GLAccount.INVENTORY_WIP, "credit": total,
             "description": f"Clear WIP for {batch.batch_number}"},
        ],
    )

    return BatchCost.objects.create(
        batch=batch, total_cost=total, volume_liters=volume,
        cost_per_liter=cost_per_liter, journal_entry=entry,
    )


# ---------------------------------------------------------------------------
# Period close
# ---------------------------------------------------------------------------

@transaction.atomic
def close_period(*, facility, year: int, month: int, performed_by: User) -> AccountingPeriod:
    period, _ = AccountingPeriod.objects.select_for_update().get_or_create(
        facility=facility, year=year, month=month,
    )
    if period.is_closed:
        raise FinanceError("Period already closed.")

    # Guard: no open batches stamped with a brew_date in this period.
    open_batches = Batch.objects.filter(
        facility=facility,
        brew_date__year=year,
        brew_date__month=month,
    ).exclude(status__in=[BatchStatus.CLOSED, BatchStatus.CANCELLED])
    if open_batches.exists():
        nums = ", ".join(open_batches.values_list("batch_number", flat=True))
        raise FinanceError(f"Open batches block close: {nums}")

    # Guard: every un-costed packaged batch must have a cost row.
    uncosted = Batch.objects.filter(
        facility=facility,
        status=BatchStatus.PACKAGED,
        brew_date__year=year,
        brew_date__month=month,
        cost__isnull=True,
    )
    for b in uncosted:
        rollup_batch_cost(batch=b, performed_by=performed_by)

    period.closed_at = timezone.now()
    period.closed_by = performed_by
    period.save(update_fields=["closed_at", "closed_by", "updated_at"])
    return period


# ---------------------------------------------------------------------------
# Internal
# ---------------------------------------------------------------------------

def _current_open_period(facility) -> AccountingPeriod:
    now = timezone.now()
    period, _ = AccountingPeriod.objects.get_or_create(
        facility=facility, year=now.year, month=now.month,
    )
    return period
