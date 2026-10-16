from django.shortcuts import render

from apps.inventory.models import InventoryLot
from apps.production.models import Batch, BatchStatus


def dashboard(request):
    """
    Landing page. Counts are facility-scoped for non-superusers.
    """
    user = request.user

    if user.is_authenticated and not user.is_superuser:
        facility_ids = list(user.facilities.values_list("id", flat=True))
    else:
        facility_ids = None  # no filtering

    lots = InventoryLot.objects.all()
    batches = Batch.objects.exclude(
        status__in=[BatchStatus.CLOSED, BatchStatus.CANCELLED],
    )
    if facility_ids is not None:
        lots = lots.filter(facility_id__in=facility_ids)
        batches = batches.filter(facility_id__in=facility_ids)

    context = {
        "active_batches": batches.count(),
        "inventory_lots": lots.count(),
        "low_stock_count": lots.filter(
            quantity_on_hand__lt=0,
        ).count(),  # placeholder, real low-stock query is in selectors
        "recent_lots": lots.select_related("item", "facility")
                           .order_by("-created_at")[:10],
    }
    return render(request, "core/dashboard.html", context)
