from django.db import models
from apps.core.models import Facility, TimeStampedModel


class TTBReport(TimeStampedModel):
    STATUS = [("draft", "Draft"), ("filed", "Filed"), ("amended", "Amended")]

    facility = models.ForeignKey(Facility, on_delete=models.PROTECT, related_name="ttb_reports")
    period_start = models.DateField()
    period_end = models.DateField()
    status = models.CharField(max_length=16, choices=STATUS, default="draft")
    payload_json = models.JSONField(default=dict)
    filed_at = models.DateTimeField(null=True, blank=True)
    filed_by = models.ForeignKey(
        "core.User", null=True, blank=True, on_delete=models.PROTECT,
    )

    class Meta:
        unique_together = ("facility", "period_start", "period_end")
        ordering = ["-period_start"]


class TaxFiling(TimeStampedModel):
    facility = models.ForeignKey(Facility, on_delete=models.PROTECT, related_name="tax_filings")
    jurisdiction = models.CharField(max_length=64)
    period = models.CharField(max_length=20)  # "2026-09"
    amount_owed = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    payload_json = models.JSONField(default=dict)
    filed_at = models.DateTimeField(null=True, blank=True)
