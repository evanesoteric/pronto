# apps/inventory/web_views.py
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from apps.core.models import Facility
from apps.inventory import services, selectors
from apps.inventory.models import (
    InventoryLot, Item, MovementReason, StockMovement,
)


@login_required
def lots_list(request):
    facility = _current_facility(request)

    qs = (
        InventoryLot.objects
        .select_related("item", "facility")
        .order_by("-created_at")
    )
    if facility is not None:
        qs = qs.filter(facility=facility)

    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(
            Q(lot_number__icontains=q)
            | Q(item__sku__icontains=q)
            | Q(item__name__icontains=q)
        )

    show_zero = request.GET.get("show_zero") == "1"
    if not show_zero:
        qs = qs.filter(quantity_on_hand__gt=0)

    return render(request, "inventory/lots_list.html", {
        "lots": qs[:200],
        "q": q,
        "show_zero": show_zero,
        "facility": facility,
    })


@login_required
def lot_detail(request, pk):
    lot = get_object_or_404(
        InventoryLot.objects.select_related("item", "facility"),
        pk=pk,
    )
    _require_facility_access(request.user, lot.facility)

    history = selectors.lot_history(lot)
    return render(request, "inventory/lot_detail.html", {
        "lot": lot,
        "history": history,
    })


@login_required
@require_http_methods(["GET", "POST"])
def receive_form(request):
    facility = _current_facility(request)
    if facility is None:
        messages.error(request, "No facility selected. Contact an administrator.")
        return redirect("core:dashboard")

    items = Item.objects.filter(is_active=True).order_by("sku")

    if request.method == "POST":
        return _handle_receive_submit(request, facility, items)

    return render(request, "inventory/receive_form.html", {
        "facility": facility,
        "items": items,
    })


def _handle_receive_submit(request, facility, items):
    """
    Parse the form, call receive_stock, redirect on success.

    Form fields (per line N, indexed from 0):
      lines[N][item_id]
      lines[N][lot_number]
      lines[N][quantity]
      lines[N][unit_cost]
      lines[N][reference]
      lines[N][expires_at]
    """
    # Django forms with arrays are awkward in raw request.POST;
    # we parse by prefix.
    lines = _parse_lines(request.POST)
    if not lines:
        messages.error(request, "No lines submitted.")
        return render(request, "inventory/receive_form.html",
                      {"facility": facility, "items": items})

    received = []
    errors = []

    for i, line in enumerate(lines):
        try:
            item = Item.objects.get(pk=line["item_id"])
            quantity = Decimal(line["quantity"])
            unit_cost = Decimal(line["unit_cost"] or "0")
        except (Item.DoesNotExist, InvalidOperation, KeyError) as e:
            errors.append(f"Line {i+1}: {e}")
            continue

        if not line.get("lot_number"):
            errors.append(f"Line {i+1}: lot number is required.")
            continue

        try:
            movement = services.receive_stock(
                item=item,
                facility=facility,
                lot_number=line["lot_number"],
                quantity=quantity,
                unit_cost=unit_cost,
                performed_by=request.user,
                reference=line.get("reference", ""),
                note=line.get("note", ""),
            )
            received.append(movement)
        except ValidationError as e:
            errors.append(f"Line {i+1} ({item.sku}): {e}")

    if errors and not received:
        for err in errors:
            messages.error(request, err)
        return render(request, "inventory/receive_form.html",
                      {"facility": facility, "items": items})

    if errors:
        for err in errors:
            messages.warning(request, err)

    if received:
        # Store IDs in session for the success page
        request.session["last_received_movement_ids"] = [m.pk for m in received]
        return redirect("inventory:receive_success")

    messages.error(request, "Nothing was received.")
    return render(request, "inventory/receive_form.html",
                  {"facility": facility, "items": items})


def _parse_lines(post):
    """
    Extract line items from POST data keyed like:
      line-0-item_id=1&line-0-quantity=500&...
    """
    import re
    lines = {}
    pattern = re.compile(r"^line-(\d+)-(.+)$")
    for key, value in post.items():
        m = pattern.match(key)
        if not m:
            continue
        idx, field = m.groups()
        lines.setdefault(int(idx), {})[field] = value
    return [lines[i] for i in sorted(lines)]


@login_required
def receive_success(request):
    movement_ids = request.session.pop("last_received_movement_ids", [])
    movements = (
        StockMovement.objects
        .filter(pk__in=movement_ids)
        .select_related("lot__item", "lot__facility")
    )
    return render(request, "inventory/receive_success.html", {
        "movements": movements,
    })


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _current_facility(request):
    facility_id = request.session.get("facility_id")
    if facility_id:
        f = Facility.objects.filter(pk=facility_id).first()
        if f and (request.user.is_superuser
                  or request.user.facilities.filter(pk=f.pk).exists()):
            return f
    if not request.user.is_superuser:
        return request.user.facilities.first()
    return Facility.objects.first()


def _require_facility_access(user, facility):
    if user.is_superuser:
        return
    if not user.facilities.filter(pk=facility.pk).exists():
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied("You do not have access to that facility.")
