from decimal import Decimal

from django.db import models
from django.db.models import Sum

from apps.core.models import Facility, TimeStampedModel
from apps.inventory.models import InventoryLot, Item


class Customer(TimeStampedModel):
    name = models.CharField(max_length=200)
    account_number = models.CharField(max_length=40, unique=True)
    email = models.EmailField(blank=True)
    price_tier = models.CharField(max_length=40, default="standard")
    tax_exempt = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.account_number} — {self.name}"


class OrderStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    CONFIRMED = "confirmed", "Confirmed"
    ALLOCATED = "allocated", "Allocated"
    FULFILLED = "fulfilled", "Fulfilled"
    INVOICED = "invoiced", "Invoiced"
    CANCELLED = "cancelled", "Cancelled"


class Order(TimeStampedModel):
    number = models.CharField(max_length=40, unique=True)
    customer = models.ForeignKey(
        Customer, on_delete=models.PROTECT, related_name="orders",
    )
    facility = models.ForeignKey(
        Facility, on_delete=models.PROTECT, related_name="orders",
    )
    status = models.CharField(
        max_length=20, choices=OrderStatus.choices, default=OrderStatus.DRAFT,
    )
    order_date = models.DateField()
    ship_by = models.DateField(null=True, blank=True)
    shipped_at = models.DateTimeField(null=True, blank=True)
    invoiced_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-order_date", "-id"]
        indexes = [models.Index(fields=["status", "facility"])]

    def __str__(self):
        return self.number

    @property
    def total(self):
        return sum(
            (line.quantity * line.unit_price for line in self.lines.all()),
            Decimal("0"),
        )


class OrderLine(TimeStampedModel):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="lines")
    item = models.ForeignKey(Item, on_delete=models.PROTECT)
    quantity = models.DecimalField(max_digits=12, decimal_places=3)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    backordered = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.order.number} — {self.item.sku}"

    @property
    def allocated_quantity(self):
        return (
            self.allocations.aggregate(t=Sum("quantity"))["t"]
            or Decimal("0")
        )

    @property
    def remaining_to_ship(self):
        return self.quantity - self.allocated_quantity

    @property
    def total(self):
        return (self.quantity * self.unit_price).quantize(Decimal("0.01"))


class StockAllocation(TimeStampedModel):
    """
    Reserves a specific lot for a specific order line.
    Inventory does NOT move on allocation — only on ship.
    """
    order_line = models.ForeignKey(
        OrderLine, on_delete=models.CASCADE, related_name="allocations",
    )
    lot = models.ForeignKey(
        InventoryLot, on_delete=models.PROTECT, related_name="allocations",
    )
    quantity = models.DecimalField(max_digits=12, decimal_places=3)
    released_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["lot", "released_at"])]

    @classmethod
    def open_for_lot(cls, lot):
        return cls.objects.filter(lot=lot, released_at__isnull=True)
