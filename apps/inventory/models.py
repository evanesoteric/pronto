# apps/inventory/models.py
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Sum, F, Q

from apps.core.models import Facility, TimeStampedModel


# ---------------------------------------------------------------------------
# Units of measure
# ---------------------------------------------------------------------------

class UnitDimension(models.TextChoices):
    MASS = "mass", "Mass"
    VOLUME = "volume", "Volume"
    COUNT = "count", "Count"
    PACKAGING = "packaging", "Packaging"


class UnitOfMeasure(TimeStampedModel):
    """
    A unit like 'kg', 'L', 'keg'. Every item is stocked and sold in
    exactly one unit.

    Base units (is_base=True) are the canonical reference for a
    dimension. Exactly one per dimension is enforced.
    """
    code = models.CharField(max_length=16, unique=True)
    name = models.CharField(max_length=80)
    dimension = models.CharField(
        max_length=16, choices=UnitDimension.choices,
    )
    is_base = models.BooleanField(
        default=False,
        help_text="Base unit for its dimension. Exactly one per dimension.",
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["dimension", "code"]
        constraints = [
            models.UniqueConstraint(
                fields=["dimension"],
                condition=models.Q(is_base=True),
                name="unique_base_unit_per_dimension",
            ),
        ]

    def __str__(self):
        return f"{self.code} ({self.get_dimension_display()})"


class UnitConversion(TimeStampedModel):
    """
    1 from_unit = factor to_unit, for a specific item.

    Only needed when an item's stocked unit differs from a unit a
    report or rollup wants to reason in. E.g., a keg item with a
    conversion to liters so total volume can be summed across items.
    """
    item = models.ForeignKey(
        "inventory.Item", on_delete=models.CASCADE,
        related_name="unit_conversions",
    )
    from_unit = models.ForeignKey(
        UnitOfMeasure, on_delete=models.PROTECT,
        related_name="conversions_from",
    )
    to_unit = models.ForeignKey(
        UnitOfMeasure, on_delete=models.PROTECT,
        related_name="conversions_to",
    )
    factor = models.DecimalField(max_digits=16, decimal_places=6)

    class Meta:
        unique_together = ("item", "from_unit", "to_unit")
        constraints = [
            models.CheckConstraint(
                check=Q(factor__gt=0),
                name="conversion_factor_positive",
            ),
        ]

    def __str__(self):
        return (
            f"{self.item.sku}: 1 {self.from_unit.code} "
            f"= {self.factor} {self.to_unit.code}"
        )

    def clean(self):
        """
        Refuse conversions only when both units are physical AND
        their dimensions differ. Packaging <-> physical and
        packaging <-> packaging are always allowed.
        """
        from_d = self.from_unit.dimension
        to_d = self.to_unit.dimension
        physical = {"mass", "volume", "count"}
        if from_d in physical and to_d in physical and from_d != to_d:
            raise ValidationError(
                "Cannot convert between different physical dimensions "
                f"({from_d} vs {to_d})."
            )


# ---------------------------------------------------------------------------
# Items
# ---------------------------------------------------------------------------

class ItemCategory(models.TextChoices):
    MALT = "malt", "Malt"
    HOPS = "hops", "Hops"
    YEAST = "yeast", "Yeast"
    ADJUNCT = "adjunct", "Adjunct"
    PACKAGING = "packaging", "Packaging"
    FINISHED = "finished", "Finished Good"
    WIP = "wip", "Work in Progress"


class ItemQuerySet(models.QuerySet):
    def raw_materials(self):
        return self.exclude(
            category__in=[ItemCategory.FINISHED, ItemCategory.WIP],
        )

    def finished_goods(self):
        return self.filter(category=ItemCategory.FINISHED)

    def below_reorder_point(self):
        return self.annotate(
            on_hand=Sum("lots__quantity_on_hand"),
        ).filter(on_hand__lt=F("reorder_point"), reorder_point__gt=0)


class Item(TimeStampedModel):
    sku = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=200)
    category = models.CharField(max_length=20, choices=ItemCategory.choices)
    unit = models.ForeignKey(
        UnitOfMeasure, on_delete=models.PROTECT,
        related_name="items",
        help_text="The unit this item is stocked and sold in.",
    )
    reorder_point = models.DecimalField(
        max_digits=12, decimal_places=3, default=Decimal("0"),
    )
    track_lot = models.BooleanField(
        default=True,
        help_text="If False, movements aggregate onto a single system lot.",
    )
    is_active = models.BooleanField(default=True)

    objects = ItemQuerySet.as_manager()

    class Meta:
        ordering = ["sku"]
        indexes = [models.Index(fields=["category", "is_active"])]

    def __str__(self):
        return f"{self.sku} — {self.name}"


# ---------------------------------------------------------------------------
# Lots and the ledger
# ---------------------------------------------------------------------------

class InventoryLotQuerySet(models.QuerySet):
    def for_facility(self, facility):
        return self.filter(facility=facility)

    def available(self):
        return self.filter(quantity_on_hand__gt=0)

    def with_balance(self):
        return self.annotate(ledger_balance=Sum("movements__delta"))


class InventoryLot(TimeStampedModel):
    """
    A traceable quantity of an Item at a Facility.
    `quantity_on_hand` is a CACHE — the ledger (StockMovement) is truth.
    Never write to it directly; use apps.inventory.services.
    """
    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name="lots")
    facility = models.ForeignKey(
        Facility, on_delete=models.PROTECT, related_name="lots",
    )
    lot_number = models.CharField(max_length=80)
    quantity_on_hand = models.DecimalField(
        max_digits=14, decimal_places=3, default=Decimal("0"),
    )
    unit_cost = models.DecimalField(
        max_digits=12, decimal_places=4, default=Decimal("0"),
    )
    received_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    objects = InventoryLotQuerySet.as_manager()

    class Meta:
        unique_together = ("item", "lot_number", "facility")
        indexes = [
            models.Index(fields=["facility", "item"]),
            models.Index(fields=["expires_at"]),
        ]

    def __str__(self):
        return f"{self.item.sku} / {self.lot_number} @ {self.facility.code}"

    @property
    def value(self):
        return self.quantity_on_hand * self.unit_cost


class MovementReason(models.TextChoices):
    RECEIPT = "receipt", "Receipt"
    BREW_CONSUME = "brew_consume", "Brew Consumption"
    PACKAGE_CONSUME = "package_consume", "Packaging Consumption"
    PACKAGE_PRODUCE = "package_produce", "Packaging Output"
    TRANSFER_OUT = "transfer_out", "Transfer Out"
    TRANSFER_IN = "transfer_in", "Transfer In"
    ADJUSTMENT = "adjustment", "Adjustment"
    SHRINKAGE = "shrinkage", "Shrinkage / Loss"
    SHIPMENT = "shipment", "Order Shipment"


class StockMovementQuerySet(models.QuerySet):
    def for_facility(self, facility):
        return self.filter(lot__facility=facility)

    def for_batch(self, batch):
        return self.filter(batch=batch)


class StockMovement(models.Model):
    """
    Append-only ledger row. NEVER update or delete.
    Corrections are written as opposing ADJUSTMENT movements.
    """
    lot = models.ForeignKey(
        InventoryLot, on_delete=models.PROTECT, related_name="movements",
    )
    delta = models.DecimalField(
        max_digits=14, decimal_places=3,
        help_text="Positive = in, negative = out.",
    )
    reason = models.CharField(max_length=32, choices=MovementReason.choices)
    reference = models.CharField(max_length=128, blank=True)
    batch = models.ForeignKey(
        "production.Batch", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="movements",
    )
    order_line = models.ForeignKey(
        "sales.OrderLine", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="movements",
    )
    performed_by = models.ForeignKey(
        "core.User", on_delete=models.PROTECT, related_name="stock_movements",
    )
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    objects = StockMovementQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["lot", "created_at"]),
            models.Index(fields=["reason"]),
        ]

    def __str__(self):
        sign = "+" if self.delta >= 0 else ""
        return (
            f"{sign}{self.delta} {self.lot.item.unit.code} "
            f"{self.lot.item.sku} ({self.reason})"
        )
