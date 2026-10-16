from decimal import Decimal
from django.db import models

from apps.core.models import Facility, TimeStampedModel


class GLAccount(models.TextChoices):
    INVENTORY_RAW = "1200", "Inventory — Raw Materials"
    INVENTORY_WIP = "1210", "Inventory — WIP"
    INVENTORY_FG = "1220", "Inventory — Finished Goods"
    COGS = "5000", "Cost of Goods Sold"
    SHRINKAGE = "5100", "Shrinkage / Loss"
    AP = "2000", "Accounts Payable"
    AR = "1100", "Accounts Receivable"
    REVENUE = "4000", "Revenue"


class AccountingPeriod(TimeStampedModel):
    facility = models.ForeignKey(Facility, on_delete=models.PROTECT, related_name="periods")
    year = models.PositiveSmallIntegerField()
    month = models.PositiveSmallIntegerField()
    closed_at = models.DateTimeField(null=True, blank=True)
    closed_by = models.ForeignKey(
        "core.User", null=True, blank=True, on_delete=models.PROTECT,
    )

    class Meta:
        unique_together = ("facility", "year", "month")
        ordering = ["-year", "-month"]

    @property
    def is_closed(self):
        return self.closed_at is not None


class JournalEntry(TimeStampedModel):
    """
    Immutable once posted. Corrections are new entries that reverse
    and re-apply.
    """
    facility = models.ForeignKey(Facility, on_delete=models.PROTECT, related_name="entries")
    posted_at = models.DateTimeField(null=True, blank=True)
    memo = models.CharField(max_length=255)
    reference = models.CharField(max_length=128, blank=True)
    reversed_by = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="reversals",
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["facility", "posted_at"])]

    @property
    def total_debits(self):
        return self.lines.aggregate(t=models.Sum("debit"))["t"] or Decimal("0")

    @property
    def total_credits(self):
        return self.lines.aggregate(t=models.Sum("credit"))["t"] or Decimal("0")

    @property
    def is_balanced(self):
        return self.total_debits == self.total_credits


class JournalLine(models.Model):
    entry = models.ForeignKey(JournalEntry, on_delete=models.CASCADE, related_name="lines")
    account = models.CharField(max_length=10, choices=GLAccount.choices)
    debit = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"))
    credit = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"))
    description = models.CharField(max_length=255, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                check=~models.Q(debit=0) | ~models.Q(credit=0),
                name="journal_line_not_zero",
            ),
        ]


class BatchCost(TimeStampedModel):
    """Frozen COGS for a batch, computed once when it closes."""
    batch = models.OneToOneField(
        "production.Batch", on_delete=models.PROTECT, related_name="cost",
    )
    total_cost = models.DecimalField(max_digits=14, decimal_places=4)
    volume_liters = models.DecimalField(max_digits=12, decimal_places=3)
    cost_per_liter = models.DecimalField(max_digits=10, decimal_places=4)
    journal_entry = models.ForeignKey(
        JournalEntry, null=True, blank=True, on_delete=models.SET_NULL,
    )
    computed_at = models.DateTimeField(auto_now_add=True)
