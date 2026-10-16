# apps/reporting/web_views.py
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse

from apps.barcodes import services as barcode_services
from apps.barcodes.labels import (
    render_batch_label_pdf, render_lot_label_pdf,
    render_order_label_pdf, render_sku_shelf_label_pdf,
)
from apps.barcodes.models import Barcode
from apps.barcodes.printing import PrintJob, PrintJobStatus
from apps.barcodes.services import BarcodeError
from apps.inventory.models import InventoryLot, Item
from apps.production.models import Batch
from apps.sales.models import Order


# ---------------------------------------------------------------------------
# Scan Anything
# ---------------------------------------------------------------------------

@login_required
def scan_anything(request):
    """
    Landing page for scanning. Renders the scanner, and if a token was
    posted, resolves it and shows the target with action buttons.
    """
    token = ""
    resolved = None
    error = ""

    if request.method == "POST":
        token = (request.POST.get("token") or "").strip()
        if token:
            try:
                target = barcode_services.resolve(token)
            except BarcodeError as e:
                error = str(e)
            else:
                # Facility check
                facility = getattr(target, "facility", None)
                if facility and not request.user.is_superuser:
                    if not request.user.facilities.filter(pk=facility.pk).exists():
                        error = "Barcode is for a facility you don't have access to."
                    else:
                        resolved = _describe_target(target)
                else:
                    resolved = _describe_target(target)
        else:
            error = "No token provided."

    return render(request, "reporting/scan_anything.html", {
        "token": token,
        "resolved": resolved,
        "error": error,
    })


def _describe_target(target):
    """
    Returns a dict describing the resolved target with enough info
    for the template to render an action card.
    """
    if isinstance(target, InventoryLot):
        return {
            "kind": "lot",
            "title": f"Lot {target.lot_number}",
            "subtitle": f"{target.item.sku} — {target.item.name}",
            "meta": [
                ("Facility", target.facility.name),
                ("On hand", f"{target.quantity_on_hand} {target.item.unit.code}"),
                ("Unit cost", f"${target.unit_cost} / {target.item.unit.code}"),
            ],
            "actions": [
                {"label": "Open lot", "url": reverse("inventory:lot_detail", args=[target.pk])},
                {"label": "Print label", "url": reverse("reporting:print_label_lot", args=[target.pk])},
            ],
        }
    if isinstance(target, Batch):
        return {
            "kind": "batch",
            "title": f"Batch {target.batch_number}",
            "subtitle": f"{target.recipe.name} v{target.recipe.version}",
            "meta": [
                ("Facility", target.facility.name),
                ("Status", target.get_status_display()),
                ("Planned volume", f"{target.planned_volume_liters} L"),
            ],
            "actions": [
                {"label": "Open batch", "url": reverse("production:batch_detail", args=[target.pk])},
                {"label": "Print label", "url": reverse("reporting:print_label_batch", args=[target.pk])},
            ],
        }
    if isinstance(target, Order):
        return {
            "kind": "order",
            "title": f"Order {target.number}",
            "subtitle": target.customer.name,
            "meta": [
                ("Facility", target.facility.name),
                ("Status", target.get_status_display()),
                ("Order date", str(target.order_date)),
            ],
            "actions": [
                {"label": "Open order", "url": reverse("sales:order_detail", args=[target.pk])},
                {"label": "Print label", "url": reverse("reporting:print_label_order", args=[target.pk])},
            ],
        }
    if isinstance(target, Item):
        return {
            "kind": "item",
            "title": f"Item {target.sku}",
            "subtitle": target.name,
            "meta": [
                ("Category", target.get_category_display()),
                ("Unit", target.unit.code),
                ("Active", "Yes" if target.is_active else "No"),
            ],
            "actions": [
                {"label": "Open item (admin)", "url": f"/admin/inventory/item/{target.pk}/change/"},
                {"label": "Print shelf label", "url": reverse("reporting:print_label_item", args=[target.pk])},
            ],
        }
    return {
        "kind": "unknown",
        "title": "Unknown target",
        "subtitle": str(target),
        "meta": [],
        "actions": [],
    }


# ---------------------------------------------------------------------------
# Label PDF endpoints (redirect into the existing API label views)
# ---------------------------------------------------------------------------

@login_required
def print_label_lot(request, pk):
    lot = InventoryLot.objects.select_related("item", "facility").get(pk=pk)
    _require_facility_access(request.user, lot.facility)
    pdf = render_lot_label_pdf(lot)
    return _pdf_response(pdf, f"lot-{lot.lot_number}.pdf")


@login_required
def print_label_batch(request, pk):
    batch = Batch.objects.select_related("recipe", "facility", "tank").get(pk=pk)
    _require_facility_access(request.user, batch.facility)
    pdf = render_batch_label_pdf(batch)
    return _pdf_response(pdf, f"batch-{batch.batch_number}.pdf")


@login_required
def print_label_order(request, pk):
    order = Order.objects.select_related("customer", "facility").get(pk=pk)
    _require_facility_access(request.user, order.facility)
    pdf = render_order_label_pdf(order)
    return _pdf_response(pdf, f"order-{order.number}.pdf")


@login_required
def print_label_item(request, pk):
    item = Item.objects.get(pk=pk)
    pdf = render_sku_shelf_label_pdf(item)
    return _pdf_response(pdf, f"item-{item.sku}.pdf")


# ---------------------------------------------------------------------------
# Print Queue
# ---------------------------------------------------------------------------

@login_required
def print_queue(request):
    """
    Shows pending, recently printed, and failed print jobs.
    """
    pending = (
        PrintJob.objects
        .filter(status=PrintJobStatus.PENDING)
        .select_related("barcode")
        .order_by("created_at")
    )
    printed = (
        PrintJob.objects
        .filter(status=PrintJobStatus.PRINTED)
        .select_related("barcode")
        .order_by("-printed_at")[:50]
    )
    failed = (
        PrintJob.objects
        .filter(status=PrintJobStatus.FAILED)
        .select_related("barcode")
        .order_by("-updated_at")[:20]
    )

    # Resolve target info for each job so we can show a readable label.
    pending = [_enrich_job(j) for j in pending]
    printed = [_enrich_job(j) for j in printed]
    failed = [_enrich_job(j) for j in failed]

    return render(request, "reporting/print_queue.html", {
        "pending": pending,
        "printed": printed,
        "failed": failed,
        "pending_count": len(pending),
    })


@login_required
def print_job_pdf(request, pk):
    """
    Render a single job's label as PDF. Used by the print queue's
    per-job "Print" button.
    """
    job = PrintJob.objects.select_related("barcode").get(pk=pk)

    # Resolve target
    try:
        target = barcode_services.resolve(job.barcode.token)
    except BarcodeError as e:
        messages.error(request, str(e))
        return redirect("reporting:print_queue")

    # Facility check
    facility = getattr(target, "facility", None)
    if facility and not request.user.is_superuser:
        if not request.user.facilities.filter(pk=facility.pk).exists():
            messages.error(request, "Not your facility.")
            return redirect("reporting:print_queue")

    pdf = _render_target_label(target)
    if pdf is None:
        messages.error(request, f"Cannot render a label for {type(target).__name__}.")
        return redirect("reporting:print_queue")

    # Mark as printed
    from django.utils import timezone
    job.status = PrintJobStatus.PRINTED
    job.printed_at = timezone.now()
    job.save(update_fields=["status", "printed_at", "updated_at"])

    return _pdf_response(pdf, f"label-{job.pk}.pdf")


@login_required
def print_job_cancel(request, pk):
    """Cancel a pending or failed print job."""
    job = PrintJob.objects.get(pk=pk)
    job.status = PrintJobStatus.CANCELLED
    job.save(update_fields=["status", "updated_at"])
    messages.success(request, f"Print job #{job.pk} cancelled.")
    return redirect("reporting:print_queue")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _render_target_label(target):
    if isinstance(target, InventoryLot):
        return render_lot_label_pdf(target)
    if isinstance(target, Batch):
        return render_batch_label_pdf(target)
    if isinstance(target, Order):
        return render_order_label_pdf(target)
    if isinstance(target, Item):
        return render_sku_shelf_label_pdf(target)
    return None


def _enrich_job(job):
    """Attach display info to a PrintJob for the template."""
    try:
        target = barcode_services.resolve(job.barcode.token)
        display = str(target)
        kind = type(target).__name__
    except Exception:
        display = job.barcode.token
        kind = "?"
    return {
        "job": job,
        "display": display,
        "kind": kind,
        "token": job.barcode.token,
    }


def _pdf_response(pdf_bytes, filename):
    resp = HttpResponse(pdf_bytes, content_type="application/pdf")
    resp["Content-Disposition"] = f'inline; filename="{filename}"'
    return resp


def _require_facility_access(user, facility):
    if user.is_superuser:
        return
    from django.core.exceptions import PermissionDenied
    if not user.facilities.filter(pk=facility.pk).exists():
        raise PermissionDenied("You do not have access to that facility.")
