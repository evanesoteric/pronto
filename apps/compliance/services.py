from datetime import date, datetime, time, timedelta
from decimal import Decimal
import csv
import io

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.core.models import User
from apps.inventory.models import ItemCategory, MovementReason, StockMovement
from .models import TTBReport


class ComplianceError(ValidationError):
    pass


@transaction.atomic
def generate_ttb_report(
    *, facility, period_start: date, period_end: date, performed_by: User | None = None,
) -> TTBReport:
    """
    Compute the TTB Brewer's Report numbers for a period from the ledger.
    Idempotent on (facility, period_start, period_end).
    """
    if period_end < period_start:
        raise ComplianceError("period_end must be >= period_start.")

    report, _created = TTBReport.objects.get_or_create(
        facility=facility, period_start=period_start, period_end=period_end,
        defaults={"payload_json": {}},
    )
    if report.status == "filed" and performed_by is not None:
        raise ComplianceError("Cannot regenerate a filed report; file an amendment instead.")

    start_dt = timezone.make_aware(datetime.combine(period_start, time.min))
    end_dt = timezone.make_aware(datetime.combine(period_end, time.max))

    payload = _compute_ttb_numbers(facility, start_dt, end_dt)
    report.payload_json = payload
    report.save(update_fields=["payload_json", "updated_at"])
    return report


def _compute_ttb_numbers(facility, start_dt, end_dt) -> dict:
    """
    Aggregate ledger movements into TTB-required buckets.
    The exact schema mirrors TTB Form 5130.9 (Brewer's Report).
    """
    movs = StockMovement.objects.filter(
        lot__facility=facility,
        created_at__gte=start_dt,
        created_at__lte=end_dt,
    ).select_related("lot__item")

    def sum_for(reason, category=None):
        qs = movs.filter(reason=reason)
        if category:
            qs = qs.filter(lot__item__category=category)
        return qs.aggregate(t=Sum("delta"))["t"] or Decimal("0")

    # Receipts of raw materials (positive delta on receipt)
    received = sum_for(MovementReason.RECEIPT)
    brewed = -sum_for(MovementReason.BREW_CONSUME)
    produced = sum_for(MovementReason.PACKAGE_PRODUCE, ItemCategory.FINISHED)
    shipped = -sum_for(MovementReason.SHIPMENT, ItemCategory.FINISHED)
    shrinkage = -sum_for(MovementReason.SHRINKAGE)
    adjustments = sum_for(MovementReason.ADJUSTMENT)

    # Beginning inventory = sum of deltas on all movements before start
    beginning = (
        StockMovement.objects
        .filter(lot__facility=facility, created_at__lt=start_dt)
        .aggregate(t=Sum("delta"))["t"] or Decimal("0")
    )
    ending = beginning + received + brewed + produced + shipped + shrinkage + adjustments

    return {
        "facility_code": facility.code,
        "ttb_registry_number": facility.ttb_registry_number,
        "period": {
            "start": start_dt.date().isoformat(),
            "end": end_dt.date().isoformat(),
        },
        "raw_materials": {
            "beginning_inventory": str(beginning),
            "received": str(received),
            "used_in_production": str(brewed),
            "adjustments": str(adjustments),
            "ending_inventory": str(ending),
        },
        "production": {
            "packaged_liters": str(produced),
            "shipped_liters": str(shipped),
            "shrinkage_liters": str(shrinkage),
        },
        "generated_at": timezone.now().isoformat(),
    }


def ttb_report_as_csv(report: TTBReport) -> str:
    """Emit a CSV matching TTB Permits Online import format."""
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Field", "Value"])
    for section, values in report.payload_json.items():
        if isinstance(values, dict):
            for k, v in values.items():
                w.writerow([f"{section}.{k}", v])
        else:
            w.writerow([section, values])
    return buf.getvalue()
