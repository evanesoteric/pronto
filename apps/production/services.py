"""
Production services — the batch lifecycle.

A batch moves through states. Every transition is guarded, and every
consumption goes through the inventory ledger, not by touching
InventoryLot directly.

See docs/WORKFLOWS.md for the state machine.
"""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.core.models import User
from apps.barcodes.signals import emit
from apps.inventory import services as inventory_services
from apps.inventory.models import (
    InventoryLot, Item, ItemCategory, MovementReason, StockMovement,
)
from .models import (
    Batch, BatchStatus, Recipe, RecipeIngredient, Tank, TankStatus,
)


class BatchStateError(ValidationError):
    """Raised when a batch transition is illegal for the current state."""

    def __str__(self):
        return " ".join(self.messages) if hasattr(self, "messages") else super().__str__()

# ---------------------------------------------------------------------------
# Batch creation
# ---------------------------------------------------------------------------

@transaction.atomic
def create_batch(
    *,
    recipe: Recipe,
    facility,
    batch_number: str,
    planned_volume_liters: Decimal,
    performed_by: User,
    tank: Tank | None = None,
    brew_date=None,
    notes: str = "",
) -> Batch:
    """
    Create a batch in PLANNED state. Does not consume anything yet.
    Call start_brew() when the brewer actually begins.
    """
    if planned_volume_liters <= 0:
        raise ValidationError("Planned volume must be positive.")

    if Batch.objects.filter(batch_number=batch_number).exists():
        raise BatchStateError(f"Batch {batch_number} already exists.")

    if tank is not None and tank.facility_id != facility.pk:
        raise BatchStateError("Tank and batch must be at the same facility.")

    return Batch.objects.create(
        batch_number=batch_number,
        recipe=recipe,
        facility=facility,
        tank=tank,
        planned_volume_liters=planned_volume_liters,
        brew_date=brew_date,
        notes=notes,
        status=BatchStatus.PLANNED,
    )


# ---------------------------------------------------------------------------
# start_brew — PLANNED → BREWING (consumes ingredients)
# ---------------------------------------------------------------------------

@transaction.atomic
def start_brew(
    *,
    batch: Batch,
    performed_by: User,
    scaling_factor: Decimal = Decimal("1.0"),
) -> list[StockMovement]:
    """
    Move a PLANNED batch into BREWING and consume its ingredients from
    inventory via FIFO. Returns the list of StockMovements created.

    scaling_factor lets you brew a double batch off the same recipe.
    If any ingredient is short, the whole thing rolls back — no partial
    consumption.
    """
    if scaling_factor <= 0:
        raise ValidationError("Scaling factor must be positive.")

    batch = Batch.objects.select_for_update().get(pk=batch.pk)
    if batch.status != BatchStatus.PLANNED:
        raise BatchStateError(
            f"Cannot start brew from status '{batch.status}'. "
            f"Batch must be PLANNED."
        )

    movements: list[StockMovement] = []
    for ing in batch.recipe.ingredients.select_related("item").all():
        qty = (ing.quantity * scaling_factor).quantize(Decimal("0.001"))
        try:
            movements.extend(inventory_services.consume_fifo(
                item=ing.item,
                facility=batch.facility,
                quantity=qty,
                reason=MovementReason.BREW_CONSUME,
                performed_by=performed_by,
                batch=batch,
                reference=f"brew:{batch.batch_number}:{ing.stage}",
            ))
        except inventory_services.InsufficientStock as e:
            # Roll back the whole brew with a clear message.
            raise BatchStateError(str(e)) from e

    batch.status = BatchStatus.BREWING
    batch.brew_date = batch.brew_date or timezone.now().date()
    batch.save(update_fields=["status", "brew_date", "updated_at"])
    return movements


# ---------------------------------------------------------------------------
# transfer_to_tank — BREWING → FERMENTING (acquires tank)
# ---------------------------------------------------------------------------

@transaction.atomic
def transfer_to_tank(
    *, batch: Batch, tank: Tank, performed_by: User,
) -> Batch:
    """
    Assign a tank to a brewed batch and move it to FERMENTING.
    Releases any previously held tank on this batch.
    """
    batch = Batch.objects.select_for_update().get(pk=batch.pk)
    tank = Tank.objects.select_for_update().get(pk=tank.pk)

    if batch.status not in (BatchStatus.BREWING, BatchStatus.FERMENTING):
        raise BatchStateError(
            f"Cannot transfer a batch in status '{batch.status}' to a tank."
        )

    if tank.facility_id != batch.facility_id:
        raise BatchStateError("Tank and batch must be at the same facility.")

    if tank.status not in (TankStatus.IDLE, TankStatus.CLEANING):
        raise BatchStateError(
            f"Tank {tank.name} is not available (status: {tank.status})."
        )

    # If batch already occupied a different tank, release it.
    if batch.tank_id and batch.tank_id != tank.pk:
        Tank.objects.filter(pk=batch.tank_id).update(status=TankStatus.IDLE)

    batch.tank = tank
    batch.status = BatchStatus.FERMENTING
    batch.save(update_fields=["tank", "status", "updated_at"])

    tank.status = TankStatus.FERMENTING
    tank.save(update_fields=["status", "updated_at"])
    return batch


# ---------------------------------------------------------------------------
# advance_status — FERMENTING → CONDITIONING → PACKAGED → CLOSED
# ---------------------------------------------------------------------------

@transaction.atomic
def advance_status(
    *, batch: Batch, to_status: str, performed_by: User,
) -> Batch:
    """
    Move a batch forward through its allowed transitions.
    QC gates block the CONDITIONING → PACKAGED transition.
    """
    allowed = {
        BatchStatus.BREWING: {BatchStatus.FERMENTING},
        BatchStatus.FERMENTING: {BatchStatus.CONDITIONING},
        BatchStatus.CONDITIONING: {BatchStatus.PACKAGED},
        BatchStatus.PACKAGED: {BatchStatus.CLOSED},
    }

    batch = Batch.objects.select_for_update().get(pk=batch.pk)
    if to_status not in allowed.get(batch.status, set()):
        raise BatchStateError(
            f"Illegal transition {batch.status} → {to_status}."
        )

    # QC gate check — only enforced on the packaging transition.
    if to_status == BatchStatus.PACKAGED:
        _check_qc_gates(batch)

    batch.status = to_status
    update_fields = ["status", "updated_at"]

    if to_status == BatchStatus.PACKAGED:
        batch.packaged_at = timezone.now()
        update_fields.append("packaged_at")
    if to_status == BatchStatus.CLOSED:
        batch.closed_at = timezone.now()
        update_fields.append("closed_at")

    batch.save(update_fields=update_fields)

    # Release tank when the batch closes.
    if to_status == BatchStatus.CLOSED and batch.tank_id:
        Tank.objects.filter(pk=batch.tank_id).update(status=TankStatus.IDLE)

    return batch


# ---------------------------------------------------------------------------
# package_batch — creates the finished-good lot in inventory
# ---------------------------------------------------------------------------

@transaction.atomic
def package_batch(
    *,
    batch: Batch,
    finished_item: Item,
    packaged_volume_liters: Decimal,
    containers: int,
    lot_number: str,
    performed_by: User,
    auto_print_label: bool = True,
) -> Batch:
    """
    Mark a batch as packaged and create a FINISHED GOOD lot in inventory.

    Cost rollup: sum of (-delta * lot.unit_cost) across every consumption
    movement on this batch, divided by packaged volume.
    """
    if packaged_volume_liters <= 0:
        raise ValidationError("Packaged volume must be positive.")
    if containers < 0:
        raise ValidationError("Containers cannot be negative.")

    batch = Batch.objects.select_for_update().get(pk=batch.pk)
    if batch.status not in (BatchStatus.CONDITIONING, BatchStatus.PACKAGED):
        raise BatchStateError(
            f"Cannot package a batch in status '{batch.status}'. "
            f"Batch must be CONDITIONING or PACKAGED."
        )

    if finished_item.category != ItemCategory.FINISHED:
        raise ValidationError(
            f"Item {finished_item.sku} is not a finished good."
        )

    # Compute cost from all consumption movements on this batch.
    total_cost = Decimal("0")
    for m in StockMovement.objects.filter(
        batch=batch, delta__lt=0,
    ).select_related("lot"):
        total_cost += m.lot.unit_cost * -m.delta

    unit_cost = (
        (total_cost / packaged_volume_liters).quantize(Decimal("0.0001"))
        if packaged_volume_liters > 0
        else Decimal("0")
    )

    # Create the finished-good lot via the ledger.
    inventory_services.receive_stock(
        item=finished_item,
        facility=batch.facility,
        lot_number=lot_number or batch.batch_number,
        quantity=packaged_volume_liters,
        unit_cost=unit_cost,
        performed_by=performed_by,
        reference=f"package:{batch.batch_number}",
        auto_print_label=auto_print_label,
    )

    batch.actual_volume_liters = packaged_volume_liters
    batch.status = BatchStatus.PACKAGED
    batch.packaged_at = timezone.now()
    batch.save(update_fields=[
        "actual_volume_liters", "status", "packaged_at", "updated_at",
    ])

    if auto_print_label:
        emit("production.batch.packaged", batch=batch)

    return batch


# ---------------------------------------------------------------------------
# Internal — QC gate check (wired up once apps.quality exists)
# ---------------------------------------------------------------------------

def _check_qc_gates(batch: Batch) -> None:
    """
    If the quality app is installed and has failing/pending gates on
    this batch, raise BatchStateError. If the app isn't installed (yet),
    this is a no-op.
    """
    try:
        from apps.quality.services import failing_gates
    except ImportError:
        return

    gates = failing_gates(batch)
    if gates:
        summary = ", ".join(g.test_type for g in gates)
        raise BatchStateError(
            f"Failing QC gates block packaging: {summary}."
        )
