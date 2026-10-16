from decimal import Decimal
from django.db import models

from apps.core.models import Facility, TimeStampedModel
from apps.inventory.models import Item


class TankStatus(models.TextChoices):
    IDLE = "idle", "Idle"
    CLEANING = "cleaning", "Cleaning"
    FERMENTING = "fermenting", "Fermenting"
    CONDITIONING = "conditioning", "Conditioning"
    PACKAGING = "packaging", "Packaging"


class Tank(TimeStampedModel):
    facility = models.ForeignKey(
        Facility, on_delete=models.CASCADE, related_name="tanks",
    )
    name = models.CharField(max_length=50)
    capacity_liters = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(
        max_length=24, choices=TankStatus.choices, default=TankStatus.IDLE,
    )

    class Meta:
        unique_together = ("facility", "name")
        ordering = ["facility", "name"]

    def __str__(self):
        return f"{self.name} ({self.facility.code})"


class Recipe(TimeStampedModel):
    name = models.CharField(max_length=200)
    version = models.PositiveIntegerField(default=1)
    style = models.CharField(max_length=80, blank=True)
    target_og = models.DecimalField(max_digits=6, decimal_places=3, null=True, blank=True)
    target_fg = models.DecimalField(max_digits=6, decimal_places=3, null=True, blank=True)
    target_abv = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        unique_together = ("name", "version")
        ordering = ["name", "-version"]

    def __str__(self):
        return f"{self.name} v{self.version}"


class RecipeIngredient(models.Model):
    recipe = models.ForeignKey(
        Recipe, on_delete=models.CASCADE, related_name="ingredients",
    )
    item = models.ForeignKey(Item, on_delete=models.PROTECT)
    quantity = models.DecimalField(max_digits=12, decimal_places=3)
    stage = models.CharField(max_length=32, default="mash")
    notes = models.CharField(max_length=200, blank=True)

    class Meta:
        unique_together = ("recipe", "item", "stage")

    def __str__(self):
        return f"{self.recipe} — {self.item.sku} ({self.quantity} {self.item.unit})"


class BatchStatus(models.TextChoices):
    PLANNED = "planned", "Planned"
    BREWING = "brewing", "Brewing"
    FERMENTING = "fermenting", "Fermenting"
    CONDITIONING = "conditioning", "Conditioning"
    PACKAGED = "packaged", "Packaged"
    CLOSED = "closed", "Closed"
    CANCELLED = "cancelled", "Cancelled"


class Batch(TimeStampedModel):
    batch_number = models.CharField(max_length=50, unique=True)
    recipe = models.ForeignKey(
        Recipe, on_delete=models.PROTECT, related_name="batches",
    )
    facility = models.ForeignKey(
        Facility, on_delete=models.PROTECT, related_name="batches",
    )
    tank = models.ForeignKey(
        Tank, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="batches",
    )
    status = models.CharField(
        max_length=20, choices=BatchStatus.choices,
        default=BatchStatus.PLANNED,
    )
    planned_volume_liters = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal("0"),
    )
    actual_volume_liters = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal("0"),
    )
    brew_date = models.DateField(null=True, blank=True)
    packaged_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["facility", "status"]),
        ]

    def __str__(self):
        return self.batch_number
