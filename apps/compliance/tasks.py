from datetime import date
from calendar import monthrange
from dateutil.relativedelta import relativedelta

from celery import shared_task
from django.utils import timezone

from apps.core.models import Facility
from . import services


@shared_task(acks_late=True)
def generate_ttb_report(facility_id: int | None = None):
    """
    Monthly: generate TTB reports for all facilities (or one).
    Idempotent on (facility, period_start, period_end).
    """
    facilities = Facility.objects.all()
    if facility_id:
        facilities = facilities.filter(pk=facility_id)

    last_month = timezone.now().replace(day=1) - relativedelta(days=1)
    period_start = last_month.replace(day=1).date()
    period_end = last_month.date()

    results = []
    for facility in facilities:
        report = services.generate_ttb_report(
            facility=facility, period_start=period_start, period_end=period_end,
        )
        results.append({"facility": facility.code, "report_id": report.pk})
    return {"reports": results}
