from decimal import Decimal
from django.db import models
from django.db.models import Sum, F

from apps.core.models import Facility, TimeStampedModel


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
    unit = models.CharField(max_length=16, help_text="kg, L, each, etc.")
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
            f"{sign}{self.delta} {self.lot.item.unit} "
            f"{self.lot.item.sku} ({self.reason})"
        )
