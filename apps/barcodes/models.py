import secrets
from django.db import models

from apps.core.models import TimeStampedModel


class BarcodeTarget(models.TextChoices):
    INVENTORY_LOT = "inventory_lot", "Inventory Lot"
    BATCH = "batch", "Batch"
    ORDER = "order", "Order"
    ITEM = "item", "Item"


class Barcode(TimeStampedModel):
    TOKEN_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"

    token = models.CharField(max_length=24, unique=True, db_index=True)
    target_type = models.CharField(max_length=24, choices=BarcodeTarget.choices)
    target_id = models.PositiveBigIntegerField()
    is_active = models.BooleanField(default=True)
    printed_at = models.DateTimeField(null=True, blank=True)
    note = models.CharField(max_length=255, blank=True)

    class Meta:
        indexes = [models.Index(fields=["target_type", "target_id"])]

    def __str__(self):
        return f"{self.token} → {self.target_type}:{self.target_id}"

    @classmethod
    def new_token(cls) -> str:
        for _ in range(10):
            token = "".join(
                secrets.choice(cls.TOKEN_ALPHABET) for _ in range(12)
            )
            if not cls.objects.filter(token=token).exists():
                return token
        raise RuntimeError("Could not generate unique barcode token.")
