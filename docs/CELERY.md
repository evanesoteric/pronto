# Celery

## Why Celery and not cron

Cron can't do retries, dependencies, or fan-out. We use Celery for:
- Scheduled work (replaces cron): `rollup_batch_costs`, `generate_ttb_report`
- Long-running work: PDF report generation, large exports
- Retryable work: anything talking to an external service (accounting sync)

## Broker and backend

Redis, on the same host as Postgres in dev. Set `CELERY_BROKER_URL` and
`CELERY_RESULT_BACKEND` in `.env`.

```env
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/1
```

We use database `0` for the broker and database `1` for the result backend
so a broker flush doesn't nuke results.

## Configuration

`config/celery.py`:

```python
import os
from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
app = Celery("ekos")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
```

`config/__init__.py`:

```python
from .celery import app as celery_app
__all__ = ("celery_app",)
```

## Running

```bash
# Worker
celery -A config worker -l info

# Beat scheduler (replaces all cron entries)
celery -A config beat -l info --scheduler django_celery_beat.schedulers:DatabaseScheduler
```

The database scheduler means schedules are editable in Django admin. No
more editing cron files on prod.

## Defining a task

```python
# apps/finance/tasks.py
from celery import shared_task
from django.db import OperationalError

from .services import rollup_batch_costs as rollup_service


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    acks_late=True,
)
def rollup_batch_costs(self, since_iso: str | None = None):
    try:
        count = rollup_service(since_iso=since_iso)
    except OperationalError as e:
        # Transient DB issue — retry with backoff.
        raise self.retry(exc=e, countdown=60 * (2 ** self.request.retries))
    return {"rolled_up": count}
```

Rules:
- **Every task is a thin wrapper around a service function.** No business
  logic in `tasks.py`.
- **Every task is idempotent.** Retries are guaranteed by Celery's at-least-
  once delivery.
- **Business exceptions never retry.** If `rollup_service` raises
  `PeriodCloseError`, that's a permanent failure. Log it and move on.
- **`acks_late=True`** for state-mutating tasks so a worker crash mid-task
  re-delivers. Combined with idempotency, this is safe.

## Periodic tasks

Register in Django admin under "Periodic Tasks," or define in a data
migration so they version with the code:

```python
# apps/finance/migrations/0002_seed_periodic_tasks.py
from django.db import migrations


def create_periodic_tasks(apps, schema_editor):
    IntervalSchedule = apps.get_model("django_celery_beat", "IntervalSchedule")
    CrontabSchedule = apps.get_model("django_celery_beat", "CrontabSchedule")
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")

    nightly, _ = CrontabSchedule.objects.get_or_create(
        minute="0", hour="2", day_of_week="*", day_of_month="*", month_of_year="*",
    )
    PeriodicTask.objects.get_or_create(
        name="Rollup batch costs",
        task="apps.finance.tasks.rollup_batch_costs",
        crontab=nightly,
    )

    monthly, _ = CrontabSchedule.objects.get_or_create(
        minute="0", hour="4", day_of_week="*", day_of_month="1", month_of_year="*",
    )
    PeriodicTask.objects.get_or_create(
        name="Generate TTB report",
        task="apps.compliance.tasks.generate_ttb_report",
        crontab=monthly,
    )

    quarter, _ = IntervalSchedule.objects.get_or_create(every=15, period="MINUTES")
    PeriodicTask.objects.get_or_create(
        name="Low stock scan",
        task="apps.forecasting.tasks.low_stock_scan",
        interval=quarter,
    )


class Migration(migrations.Migration):
    dependencies = [("finance", "0001_initial")]
    operations = [migrations.RunPython(create_periodic_tasks, migrations.RunPython.noop)]
```

## Testing tasks

Do **not** use `CELERY_ALWAYS_EAGER` in tests — it hides ordering and
retry bugs. Instead, call the underlying service function directly in unit
tests, and only use eager mode in a small number of integration tests that
specifically verify task wiring.

```python
# tests/test_tasks.py
def test_rollup_task_calls_service(mocker):
    mock = mocker.patch("apps.finance.tasks.rollup_service", return_value=3)
    result = rollup_batch_costs.apply()
    assert result.result == {"rolled_up": 3}
    mock.assert_called_once()
```
