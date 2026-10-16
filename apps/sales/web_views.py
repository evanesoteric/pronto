# apps/sales/web_views.py
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from apps.core.models import Facility
from apps.inventory.models import Item, ItemCategory
from apps.sales import selectors, services
from apps.sales.models import (
    Customer, Order, OrderLine, OrderStatus, StockAllocation,
)
from apps.sales.services import OrderStateError


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------

@login_required
def orders_list(request):
    facility = _current_facility(request)

    status_filter = request.GET.get("status", "")
    q = request.GET.get("q", "").strip()

    active_qs = selectors.open_orders(facility=facility)
    closed_qs = selectors.closed_orders(facility=facility)

    if status_filter:
        active_qs = active_qs.filter(status=status_filter)
        closed_qs = closed_qs.filter(status=status_filter)

    if q:
        active_qs = active_qs.filter(
            Q(number__icontains=q) | Q(customer__name__icontains=q)
        )
        closed_qs = closed_qs.filter(
            Q(number__icontains=q) | Q(customer__name__icontains=q)
        )

    # Slice AFTER filtering — this is the only safe order.
    closed_qs = closed_qs[:50]

    active_orders = [{"order": o, "total": o.total} for o in active_qs]
    closed_orders = [{"order": o, "total": o.total} for o in closed_qs]

    return render(request, "sales/orders_list.html", {
        "active_orders": active_orders,
        "closed_orders": closed_orders,
        "status_choices": OrderStatus.choices,
        "status_filter": status_filter,
        "q": q,
        "facility": facility,
    })


@login_required
def order_detail(request, pk):
    order = get_object_or_404(
        Order.objects.select_related("customer", "facility"), pk=pk,
    )
    _require_facility_access(request.user, order.facility)

    lines = selectors.order_fill_summary(order)

    return render(request, "sales/order_detail.html", {
        "order": order,
        "lines": lines,
        "total": order.total,
    })


@login_required
@require_http_methods(["GET", "POST"])
def order_create(request):
    facility = _current_facility(request)
    if facility is None:
        messages.error(request, "No facility selected.")
        return redirect("sales:orders_list")

    customers = Customer.objects.filter(is_active=True).order_by("name")
    finished_items = (
        Item.objects
        .filter(category=ItemCategory.FINISHED, is_active=True)
        .order_by("sku")
    )

    if request.method == "POST":
        return _handle_order_create(request, facility, customers, finished_items)

    return render(request, "sales/order_create.html", {
        "facility": facility,
        "customers": customers,
        "finished_items": finished_items,
        "today": timezone.now().date().isoformat(),
    })


def _handle_order_create(request, facility, customers, finished_items):
    import re

    number = request.POST.get("number", "").strip()
    customer_id = request.POST.get("customer_id")
    order_date_str = request.POST.get("order_date", "").strip()
    ship_by_str = request.POST.get("ship_by", "").strip()
    notes = request.POST.get("notes", "").strip()

    errors = []
    if not number:
        errors.append("Order number is required.")
    if not customer_id:
        errors.append("Customer is required.")
    if not order_date_str:
        errors.append("Order date is required.")

    customer = None
    if customer_id:
        customer = Customer.objects.filter(pk=customer_id).first()
        if customer is None:
            errors.append("Invalid customer.")

    order_date = _parse_date(order_date_str)
    if order_date_str and order_date is None:
        errors.append("Invalid order date.")
    ship_by = _parse_date(ship_by_str) if ship_by_str else None

    # Parse lines from POST (same pattern as receive form)
    lines_data = {}
    pattern = re.compile(r"^line-(\d+)-(.+)$")
    for key, value in request.POST.items():
        m = pattern.match(key)
        if not m:
            continue
        idx, field = m.groups()
        lines_data.setdefault(int(idx), {})[field] = value

    parsed_lines = []
    for i, line in sorted(lines_data.items()):
        item_id = line.get("item_id")
        qty_str = line.get("quantity", "")
        price_str = line.get("unit_price", "")

        if not item_id or not qty_str or not price_str:
            continue  # skip empty lines

        item = Item.objects.filter(pk=item_id).first()
        if item is None:
            errors.append(f"Line {i+1}: invalid item.")
            continue
        try:
            qty = Decimal(qty_str)
            if qty <= 0:
                raise InvalidOperation
        except (InvalidOperation, TypeError):
            errors.append(f"Line {i+1}: invalid quantity.")
            continue
        try:
            price = Decimal(price_str)
            if price < 0:
                raise InvalidOperation
        except (InvalidOperation, TypeError):
            errors.append(f"Line {i+1}: invalid unit price.")
            continue

        parsed_lines.append({"item": item, "quantity": qty, "unit_price": price})

    if not parsed_lines:
        errors.append("Order must have at least one line.")

    if errors:
        for e in errors:
            messages.error(request, e)
        return render(request, "sales/order_create.html", {
            "facility": facility,
            "customers": customers,
            "finished_items": finished_items,
            "today": timezone.now().date().isoformat(),
            "form_data": request.POST,
        })

    try:
        order = services.create_order(
            customer=customer,
            facility=facility,
            number=number,
            order_date=order_date,
            ship_by=ship_by,
            notes=notes,
            lines=parsed_lines,
            performed_by=request.user,
        )
    except (OrderStateError, ValidationError) as e:
        messages.error(request, str(e))
        return render(request, "sales/order_create.html", {
            "facility": facility,
            "customers": customers,
            "finished_items": finished_items,
            "today": timezone.now().date().isoformat(),
            "form_data": request.POST,
        })

    messages.success(request, f"Order {order.number} created.")
    return redirect("sales:order_detail", pk=order.pk)


@login_required
@require_http_methods(["POST"])
def order_confirm(request, pk):
    order = get_object_or_404(Order, pk=pk)
    _require_facility_access(request.user, order.facility)

    try:
        services.confirm_order(order=order, performed_by=request.user)
    except OrderStateError as e:
        messages.error(request, str(e))
        return redirect("sales:order_detail", pk=order.pk)

    messages.success(request, f"Order {order.number} confirmed.")
    return redirect("sales:order_detail", pk=order.pk)


@login_required
@require_http_methods(["POST"])
def order_allocate(request, pk):
    order = get_object_or_404(Order, pk=pk)
    _require_facility_access(request.user, order.facility)

    try:
        services.allocate_order(order=order, performed_by=request.user)
    except OrderStateError as e:
        messages.error(request, str(e))
        return redirect("sales:order_detail", pk=order.pk)

    order.refresh_from_db()
    backordered = order.lines.filter(backordered=True).count()
    if backordered:
        messages.warning(
            request,
            f"Order allocated with {backordered} backordered line(s).",
        )
    else:
        messages.success(request, "Order fully allocated.")
    return redirect("sales:order_detail", pk=order.pk)


@login_required
@require_http_methods(["POST"])
def order_ship(request, pk):
    order = get_object_or_404(Order, pk=pk)
    _require_facility_access(request.user, order.facility)

    try:
        services.ship_order(order=order, performed_by=request.user)
    except OrderStateError as e:
        messages.error(request, str(e))
        return redirect("sales:order_detail", pk=order.pk)

    messages.success(request, f"Order {order.number} shipped.")
    return redirect("sales:order_detail", pk=order.pk)


@login_required
@require_http_methods(["POST"])
def order_cancel(request, pk):
    order = get_object_or_404(Order, pk=pk)
    _require_facility_access(request.user, order.facility)

    try:
        services.cancel_order(order=order, performed_by=request.user)
    except OrderStateError as e:
        messages.error(request, str(e))
        return redirect("sales:order_detail", pk=order.pk)

    messages.success(request, f"Order {order.number} cancelled.")
    return redirect("sales:order_detail", pk=order.pk)


# ---------------------------------------------------------------------------
# Customers
# ---------------------------------------------------------------------------

@login_required
def customers_list(request):
    qs = Customer.objects.order_by("name")
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(
            Q(name__icontains=q) | Q(account_number__icontains=q)
        )
    return render(request, "sales/customers_list.html", {
        "customers": qs,
        "q": q,
    })


@login_required
def customer_detail(request, pk):
    customer = get_object_or_404(Customer, pk=pk)
    orders = selectors.customer_order_history(customer)
    return render(request, "sales/customer_detail.html", {
        "customer": customer,
        "orders": orders,
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
        raise PermissionDenied("You do not have access to that facility.")


def _parse_date(s):
    if not s:
        return None
    from datetime import date
    try:
        return date.fromisoformat(s)
    except (ValueError, TypeError):
        return None
