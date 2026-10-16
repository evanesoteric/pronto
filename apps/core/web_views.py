# apps/core/web_views.py
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.db.models import Sum, Count
from django.shortcuts import render

from apps.inventory.models import InventoryLot, Item, StockMovement
from apps.inventory import selectors as inventory_selectors
from apps.production.models import Batch, BatchStatus
from apps.production import selectors as production_selectors


@login_required
def dashboard(request):
    user = request.user
    facility = _current_facility(request)

    # Facility scoping
    lots_qs = InventoryLot.objects.all()
    batches_qs = Batch.objects.all()
    if facility is not None:
        lots_qs = lots_qs.filter(facility=facility)
        batches_qs = batches_qs.filter(facility=facility)

    # KPIs
    active_batches = batches_qs.exclude(
        status__in=[BatchStatus.CLOSED, BatchStatus.CANCELLED]
    ).count()

    inventory_value = (
        inventory_selectors.inventory_value_by_facility(facility)
        if facility else Decimal("0")
    )

    low_stock = (
        inventory_selectors.low_stock_items(facility=facility)
        if facility else []
    )
    low_stock_count = len(list(low_stock))

    # Recent activity — last 15 movements
    recent_movements = (
        StockMovement.objects
        .select_related("lot__item", "performed_by")
        .order_by("-created_at")[:15]
    )
    if facility is not None:
        recent_movements = (
            StockMovement.objects
            .filter(lot__facility=facility)
            .select_related("lot__item", "performed_by")
            .order_by("-created_at")[:15]
        )

    # Batches in flight
    active_batches_list = (
        production_selectors.active_batches(facility=facility)
        .select_related("recipe", "tank")[:8]
        if facility else []
    )

    context = {
        "facility": facility,
        "active_batches": active_batches,
        "active_batches_list": active_batches_list,
        "inventory_value": inventory_value,
        "low_stock_count": low_stock_count,
        "recent_movements": recent_movements,
    }
    return render(request, "dashboard/home.html", context)


def _current_facility(request):
    """
    Determine the current facility for the request.

    Priority:
      1. Session override (facility switcher)
      2. User's first facility
      3. None (superuser w/o selection → shows all)
    """
    facility_id = request.session.get("facility_id")
    if facility_id:
        from apps.core.models import Facility
        f = Facility.objects.filter(pk=facility_id).first()
        if f and (request.user.is_superuser
                  or request.user.facilities.filter(pk=f.pk).exists()):
            return f

    if not request.user.is_superuser:
        return request.user.facilities.first()

    return None
