from celery import shared_task
from django.db import OperationalError
from django.utils.dateparse import parse_datetime

from apps.production.models import Batch, BatchStatus
from apps.core.models import User
from . import services


@shared_task(bind=True, max_retries=3, acks_late=True)
def rollup_batch_costs(self, since_iso: str | None = None, user_id: int | None = None):
    """
    Nightly: cost any batch that was packaged but not yet costed.
    Idempotent by OneToOne on Batch.
    """
    try:
        qs = Batch.objects.filter(status=BatchStatus.PACKAGED, cost__isnull=True)
        if since_iso:
            qs = qs.filter(packaged_at__gte=parse_datetime(since_iso))

        system_user = User.objects.get(pk=user_id) if user_id else User.objects.filter(
            is_superuser=True,
        ).first()

        count = 0
        for batch in qs:
            services.rollup_batch_cost(batch=batch, performed_by=system_user)
            count += 1
        return {"rolled_up": count}
    except OperationalError as e:
        raise self.retry(exc=e, countdown=60 * (2 ** self.request.retries))


@shared_task(bind=True, acks_late=True)
def close_previous_month(self, facility_id: int, user_id: int):
    from apps.core.models import Facility
    from django.utils import timezone
    from dateutil.relativedelta import relativedelta

    facility = Facility.objects.get(pk=facility_id)
    user = User.objects.get(pk=user_id)
    last = timezone.now() - relativedelta(months=1)
    return services.close_period(
        facility=facility, year=last.year, month=last.month, performed_by=user,
    ).pk
