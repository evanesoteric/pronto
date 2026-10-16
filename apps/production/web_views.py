# apps/production/web_views.py
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from apps.core.models import Facility
from apps.inventory.models import InventoryLot, Item, ItemCategory
from apps.inventory import services as inventory_services
from apps.production import selectors, services
from apps.production.models import (
    Batch, BatchStatus, Recipe, RecipeIngredient, Tank, TankStatus,
)
from apps.production.services import BatchStateError


# ---------------------------------------------------------------------------
# Batches
# ---------------------------------------------------------------------------

@login_required
def batches_list(request):
    facility = _current_facility(request)

    qs = (
        Batch.objects
        .select_related("recipe", "tank", "facility")
        .order_by("-created_at")
    )
    if facility is not None:
        qs = qs.filter(facility=facility)

    status = request.GET.get("status", "")
    if status:
        qs = qs.filter(status=status)

    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(
            Q(batch_number__icontains=q) | Q(recipe__name__icontains=q)
        )

    # Separate active and closed for visual grouping
    active_qs = qs.exclude(
        status__in=[BatchStatus.CLOSED, BatchStatus.CANCELLED]
    )
    closed_qs = qs.filter(
        status__in=[BatchStatus.CLOSED, BatchStatus.CANCELLED]
    )[:50]

    return render(request, "production/batches_list.html", {
        "active_batches": active_qs,
        "closed_batches": closed_qs,
        "status_choices": BatchStatus.choices,
        "status_filter": status,
        "q": q,
        "facility": facility,
    })


@login_required
def batch_detail(request, pk):
    batch = get_object_or_404(
        Batch.objects.select_related("recipe", "tank", "facility"),
        pk=pk,
    )
    _require_facility_access(request.user, batch.facility)

    # Ingredient availability
    ingredient_status = _ingredient_availability(batch)

    # Next legal status
    next_status = _next_status(batch)

    # Consumption (if any movements have been written)
    consumption = list(selectors.batch_consumption(batch))
    total_cost = selectors.batch_cost(batch)

    return render(request, "production/batch_detail.html", {
        "batch": batch,
        "ingredient_status": ingredient_status,
        "next_status": next_status,
        "consumption": consumption,
        "total_cost": total_cost,
        "can_start": (
            batch.status == BatchStatus.PLANNED
            and all(row["sufficient"] for row in ingredient_status)
        ),
        "available_tanks": _available_tanks(batch),
    })


@login_required
@require_http_methods(["GET", "POST"])
def batch_create(request):
    facility = _current_facility(request)
    if facility is None:
        messages.error(request, "No facility selected.")
        return redirect("production:batches_list")

    recipes = Recipe.objects.all().order_by("name", "-version")

    if request.method == "POST":
        batch_number = request.POST.get("batch_number", "").strip()
        recipe_id = request.POST.get("recipe")
        volume_str = request.POST.get("planned_volume_liters", "0")

        errors = []
        recipe = None
        volume = Decimal("0")

        if not batch_number:
            errors.append("Batch number is required.")
        if not recipe_id:
            errors.append("Recipe is required.")
        else:
            recipe = Recipe.objects.filter(pk=recipe_id).first()
            if recipe is None:
                errors.append("Invalid recipe.")

        try:
            volume = Decimal(volume_str)
            if volume <= 0:
                errors.append("Volume must be positive.")
        except (InvalidOperation, TypeError):
            errors.append("Volume must be a number.")

        if errors:
            for e in errors:
                messages.error(request, e)
            return render(request, "production/batch_create.html", {
                "facility": facility,
                "recipes": recipes,
                "form_data": request.POST,
            })

        try:
            batch = services.create_batch(
                recipe=recipe,
                facility=facility,
                batch_number=batch_number,
                planned_volume_liters=volume,
                performed_by=request.user,
                notes=request.POST.get("notes", ""),
            )
        except ValidationError as e:
            messages.error(request, str(e))
            return render(request, "production/batch_create.html", {
                "facility": facility,
                "recipes": recipes,
                "form_data": request.POST,
            })

        messages.success(request, f"Batch {batch.batch_number} created.")
        return redirect("production:batch_detail", pk=batch.pk)

    return render(request, "production/batch_create.html", {
        "facility": facility,
        "recipes": recipes,
        "form_data": {},
    })


@login_required
@require_http_methods(["GET", "POST"])
def batch_start_brew(request, pk):
    batch = get_object_or_404(Batch, pk=pk)
    _require_facility_access(request.user, batch.facility)

    if batch.status != BatchStatus.PLANNED:
        messages.error(
            request,
            f"Cannot start brew — batch is {batch.get_status_display()}.",
        )
        return redirect("production:batch_detail", pk=batch.pk)

    ingredient_status = _ingredient_availability(batch)

    if request.method == "POST":
        scaling_str = request.POST.get("scaling_factor", "1.0")
        try:
            scaling = Decimal(scaling_str)
            if scaling <= 0:
                raise InvalidOperation
        except (InvalidOperation, TypeError):
            messages.error(request, "Invalid scaling factor.")
            return redirect("production:batch_start_brew", pk=batch.pk)

        try:
            movements = services.start_brew(
                batch=batch,
                performed_by=request.user,
                scaling_factor=scaling,
            )
        except (BatchStateError, ValidationError) as e:
            messages.error(request, str(e))
            return redirect("production:batch_detail", pk=batch.pk)

        messages.success(
            request,
            f"Brew started — {len(movements)} ingredient(s) consumed.",
        )
        return redirect("production:batch_detail", pk=batch.pk)

    return render(request, "production/batch_start_brew.html", {
        "batch": batch,
        "ingredient_status": ingredient_status,
        "all_sufficient": all(r["sufficient"] for r in ingredient_status),
    })


@login_required
@require_http_methods(["GET", "POST"])
def batch_transfer(request, pk):
    batch = get_object_or_404(Batch, pk=pk)
    _require_facility_access(request.user, batch.facility)

    if batch.status not in (BatchStatus.BREWING, BatchStatus.FERMENTING):
        messages.error(
            request,
            f"Cannot transfer — batch is {batch.get_status_display()}.",
        )
        return redirect("production:batch_detail", pk=batch.pk)

    tanks = _available_tanks(batch)

    if request.method == "POST":
        tank_id = request.POST.get("tank_id")
        tank = Tank.objects.filter(pk=tank_id).first()
        if tank is None:
            messages.error(request, "Invalid tank.")
            return redirect("production:batch_transfer", pk=batch.pk)

        try:
            services.transfer_to_tank(
                batch=batch, tank=tank, performed_by=request.user,
            )
        except BatchStateError as e:
            messages.error(request, str(e))
            return redirect("production:batch_transfer", pk=batch.pk)

        messages.success(request, f"Transferred to {tank.name}.")
        return redirect("production:batch_detail", pk=batch.pk)

    return render(request, "production/batch_transfer.html", {
        "batch": batch,
        "tanks": tanks,
    })


@login_required
@require_http_methods(["POST"])
def batch_advance(request, pk):
    batch = get_object_or_404(Batch, pk=pk)
    _require_facility_access(request.user, batch.facility)

    to_status = request.POST.get("to_status")
    if not to_status:
        messages.error(request, "No target status specified.")
        return redirect("production:batch_detail", pk=batch.pk)

    try:
        services.advance_status(
            batch=batch, to_status=to_status, performed_by=request.user,
        )
    except BatchStateError as e:
        messages.error(request, str(e))
        return redirect("production:batch_detail", pk=batch.pk)

    messages.success(
        request,
        f"Batch advanced to {batch.get_status_display()}.",
    )
    return redirect("production:batch_detail", pk=batch.pk)


@login_required
@require_http_methods(["GET", "POST"])
def batch_package(request, pk):
    batch = get_object_or_404(Batch, pk=pk)
    _require_facility_access(request.user, batch.facility)

    if batch.status not in (BatchStatus.CONDITIONING, BatchStatus.PACKAGED):
        messages.error(
            request,
            f"Cannot package — batch is {batch.get_status_display()}.",
        )
        return redirect("production:batch_detail", pk=batch.pk)

    finished_items = Item.objects.filter(
        category=ItemCategory.FINISHED, is_active=True,
    ).order_by("sku")

    if request.method == "POST":
        item_id = request.POST.get("finished_item_id")
        volume_str = request.POST.get("packaged_volume_liters", "0")
        containers_str = request.POST.get("containers", "0")
        lot_number = request.POST.get("lot_number", "").strip()

        finished = Item.objects.filter(pk=item_id).first()
        if finished is None:
            messages.error(request, "Invalid finished item.")
            return redirect("production:batch_package", pk=batch.pk)

        try:
            volume = Decimal(volume_str)
            if volume <= 0:
                raise InvalidOperation
        except (InvalidOperation, TypeError):
            messages.error(request, "Invalid volume.")
            return redirect("production:batch_package", pk=batch.pk)

        try:
            containers = int(containers_str)
            if containers < 0:
                raise ValueError
        except (ValueError, TypeError):
            messages.error(request, "Invalid container count.")
            return redirect("production:batch_package", pk=batch.pk)

        if not lot_number:
            messages.error(request, "Lot number is required.")
            return redirect("production:batch_package", pk=batch.pk)

        try:
            services.package_batch(
                batch=batch,
                finished_item=finished,
                packaged_volume_liters=volume,
                containers=containers,
                lot_number=lot_number,
                performed_by=request.user,
            )
        except (BatchStateError, ValidationError) as e:
            messages.error(request, str(e))
            return redirect("production:batch_package", pk=batch.pk)

        messages.success(request, f"Batch packaged as {lot_number}.")
        return redirect("production:batch_detail", pk=batch.pk)

    return render(request, "production/batch_package.html", {
        "batch": batch,
        "finished_items": finished_items,
        "suggested_lot_number": f"{batch.batch_number}-KEG",
    })


# ---------------------------------------------------------------------------
# Tanks
# ---------------------------------------------------------------------------

@login_required
def tanks_list(request):
    facility = _current_facility(request)
    qs = Tank.objects.select_related("facility")
    if facility is not None:
        qs = qs.filter(facility=facility)

    # Annotate with current batch
    tanks = []
    for tank in qs.order_by("name"):
        current = (
            Batch.objects
            .filter(tank=tank)
            .exclude(status__in=[BatchStatus.CLOSED, BatchStatus.CANCELLED])
            .first()
        )
        tanks.append({"tank": tank, "current_batch": current})

    return render(request, "production/tanks_list.html", {
        "tanks": tanks,
        "facility": facility,
    })


@login_required
def tank_detail(request, pk):
    tank = get_object_or_404(Tank.objects.select_related("facility"), pk=pk)
    _require_facility_access(request.user, tank.facility)

    history = (
        Batch.objects
        .filter(tank=tank)
        .select_related("recipe")
        .order_by("-created_at")[:20]
    )

    return render(request, "production/tank_detail.html", {
        "tank": tank,
        "history": history,
    })


# ---------------------------------------------------------------------------
# Recipes
# ---------------------------------------------------------------------------

@login_required
def recipes_list(request):
    recipes = (
        Recipe.objects
        .prefetch_related("ingredients__item")
        .order_by("name", "-version")
    )
    q = request.GET.get("q", "").strip()
    if q:
        recipes = recipes.filter(
            Q(name__icontains=q) | Q(style__icontains=q)
        )

    return render(request, "production/recipes_list.html", {
        "recipes": recipes,
        "q": q,
    })


@login_required
def recipe_detail(request, pk):
    recipe = get_object_or_404(
        Recipe.objects.prefetch_related("ingredients__item"), pk=pk,
    )
    batches = (
        Batch.objects
        .filter(recipe=recipe)
        .select_related("facility")
        .order_by("-created_at")[:10]
    )
    return render(request, "production/recipe_detail.html", {
        "recipe": recipe,
        "batches": batches,
    })


@login_required
@require_http_methods(["GET", "POST"])
def recipe_create(request):
    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        version_str = request.POST.get("version", "1")
        style = request.POST.get("style", "").strip()
        notes = request.POST.get("notes", "")

        errors = []
        if not name:
            errors.append("Name is required.")
        try:
            version = int(version_str)
            if version < 1:
                raise ValueError
        except (ValueError, TypeError):
            errors.append("Version must be a positive integer.")

        if errors:
            for e in errors:
                messages.error(request, e)
            return render(request, "production/recipe_form.html", {
                "form_data": _recipe_form_data_from_request(request),
                "mode": "create",
            })

        recipe = Recipe.objects.create(
            name=name, version=version, style=style, notes=notes,
            target_og=_optional_decimal(request.POST.get("target_og")),
            target_fg=_optional_decimal(request.POST.get("target_fg")),
            target_abv=_optional_decimal(request.POST.get("target_abv")),
        )
        messages.success(request, f"Recipe {recipe.name} v{recipe.version} created.")
        return redirect("production:recipe_detail", pk=recipe.pk)

    return render(request, "production/recipe_form.html", {
        "form_data": _recipe_form_data_empty(),
        "mode": "create",
    })


@login_required
@require_http_methods(["GET", "POST"])
def recipe_edit(request, pk):
    recipe = get_object_or_404(Recipe, pk=pk)

    if request.method == "POST":
        action = request.POST.get("action", "save")

        if action == "add_ingredient":
            item_id = request.POST.get("item_id")
            qty_str = request.POST.get("quantity", "0")
            stage = request.POST.get("stage", "mash")
            item = Item.objects.filter(pk=item_id).first()
            if item is None:
                messages.error(request, "Invalid item.")
            else:
                try:
                    qty = Decimal(qty_str)
                    if qty <= 0:
                        raise InvalidOperation
                    RecipeIngredient.objects.create(
                        recipe=recipe, item=item, quantity=qty, stage=stage,
                    )
                    messages.success(request, f"Added {item.sku} to {recipe.name}.")
                except (InvalidOperation, TypeError):
                    messages.error(request, "Invalid quantity.")
            return redirect("production:recipe_edit", pk=recipe.pk)

        if action == "remove_ingredient":
            ing_id = request.POST.get("ingredient_id")
            RecipeIngredient.objects.filter(pk=ing_id, recipe=recipe).delete()
            messages.success(request, "Ingredient removed.")
            return redirect("production:recipe_edit", pk=recipe.pk)

        # Default: save recipe header fields
        recipe.name = request.POST.get("name", recipe.name).strip()
        recipe.style = request.POST.get("style", recipe.style).strip()
        recipe.notes = request.POST.get("notes", recipe.notes)
        recipe.target_og = _optional_decimal(request.POST.get("target_og"))
        recipe.target_fg = _optional_decimal(request.POST.get("target_fg"))
        recipe.target_abv = _optional_decimal(request.POST.get("target_abv"))
        recipe.save()
        messages.success(request, "Recipe saved.")
        return redirect("production:recipe_detail", pk=recipe.pk)

    items = Item.objects.filter(is_active=True).order_by("sku")

    return render(request, "production/recipe_form.html", {
        "recipe": recipe,
        "items": items,
        "form_data": _recipe_form_data_from_instance(recipe),
        "mode": "edit",
    })


# ---------------------------------------------------------------------------
# Form data helpers
# ---------------------------------------------------------------------------

def _recipe_form_data_empty():
    return {
        "name": "",
        "style": "",
        "notes": "",
        "target_og": "",
        "target_fg": "",
        "target_abv": "",
    }


def _recipe_form_data_from_request(request):
    return {
        "name": request.POST.get("name", ""),
        "style": request.POST.get("style", ""),
        "notes": request.POST.get("notes", ""),
        "target_og": request.POST.get("target_og", ""),
        "target_fg": request.POST.get("target_fg", ""),
        "target_abv": request.POST.get("target_abv", ""),
    }


def _recipe_form_data_from_instance(recipe):
    return {
        "name": recipe.name or "",
        "style": recipe.style or "",
        "notes": recipe.notes or "",
        "target_og": str(recipe.target_og) if recipe.target_og is not None else "",
        "target_fg": str(recipe.target_fg) if recipe.target_fg is not None else "",
        "target_abv": str(recipe.target_abv) if recipe.target_abv is not None else "",
    }


# ---------------------------------------------------------------------------
# Form data helpers
# ---------------------------------------------------------------------------

def _recipe_form_data_empty():
    return {
        "name": "",
        "style": "",
        "notes": "",
        "target_og": "",
        "target_fg": "",
        "target_abv": "",
    }


def _recipe_form_data_from_request(request):
    return {
        "name": request.POST.get("name", ""),
        "style": request.POST.get("style", ""),
        "notes": request.POST.get("notes", ""),
        "target_og": request.POST.get("target_og", ""),
        "target_fg": request.POST.get("target_fg", ""),
        "target_abv": request.POST.get("target_abv", ""),
    }


def _recipe_form_data_from_instance(recipe):
    return {
        "name": recipe.name or "",
        "style": recipe.style or "",
        "notes": recipe.notes or "",
        "target_og": str(recipe.target_og) if recipe.target_og is not None else "",
        "target_fg": str(recipe.target_fg) if recipe.target_fg is not None else "",
        "target_abv": str(recipe.target_abv) if recipe.target_abv is not None else "",
    }

# ---------------------------------------------------------------------------
# Scan brew — the mobile floor page
# ---------------------------------------------------------------------------

@login_required
def scan_brew(request, pk):
    """
    Mobile-friendly page for a brewer to consume ingredients from a
    specific batch by scanning lot labels.
    """
    batch = get_object_or_404(Batch, pk=pk)
    _require_facility_access(request.user, batch.facility)

    return render(request, "production/scan_brew.html", {
        "batch": batch,
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


def _available_tanks(batch):
    """
    Tanks at the same facility that are idle or cleaning, or the batch's
    current tank (so it can stay put).
    """
    qs = Tank.objects.filter(
        facility=batch.facility,
        status__in=[TankStatus.IDLE, TankStatus.CLEANING],
    ).order_by("name")
    if batch.tank_id:
        current = Tank.objects.filter(pk=batch.tank_id)
        return (qs | current).distinct().order_by("name")
    return qs


def _next_status(batch):
    """
    Return the next legal status for a batch, or None if terminal.
    """
    transitions = {
        BatchStatus.BREWING: BatchStatus.FERMENTING,
        BatchStatus.FERMENTING: BatchStatus.CONDITIONING,
        BatchStatus.CONDITIONING: BatchStatus.PACKAGED,
        BatchStatus.PACKAGED: BatchStatus.CLOSED,
    }
    return transitions.get(batch.status)


def _ingredient_availability(batch):
    """
    For each ingredient in the batch's recipe, compute:
      - required quantity
      - on-hand at the batch's facility (aggregated across lots)
      - whether sufficient
    """
    rows = []
    for ing in batch.recipe.ingredients.select_related("item").order_by("stage", "item__sku"):
        on_hand = (
            InventoryLot.objects
            .filter(item=ing.item, facility=batch.facility)
            .aggregate(total=Sum("quantity_on_hand"))["total"]
            or Decimal("0")
        )
        rows.append({
            "item": ing.item,
            "required": ing.quantity,
            "on_hand": on_hand,
            "sufficient": on_hand >= ing.quantity,
            "short_by": max(Decimal("0"), ing.quantity - on_hand),
            "stage": ing.stage,
        })
    return rows


def _optional_decimal(s):
    if not s:
        return None
    try:
        return Decimal(s)
    except (InvalidOperation, TypeError):
        return None
