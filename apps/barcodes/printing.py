from django.db import models

from apps.core.models import TimeStampedModel


class PrintJobStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    PRINTED = "printed", "Printed"
    FAILED = "failed", "Failed"
    CANCELLED = "cancelled", "Cancelled"


class PrintJob(TimeStampedModel):
    barcode = models.ForeignKey(
        "barcodes.Barcode", on_delete=models.CASCADE, related_name="print_jobs",
    )
    copies = models.PositiveSmallIntegerField(default=1)
    status = models.CharField(
        max_length=16, choices=PrintJobStatus.choices,
        default=PrintJobStatus.PENDING,
    )
    printer_name = models.CharField(max_length=64, blank=True)
    printed_at = models.DateTimeField(null=True, blank=True)
    error = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["status"])]
