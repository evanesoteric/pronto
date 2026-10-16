from django.contrib.auth.models import AbstractUser
from django.db import models


class TimeStampedModel(models.Model):
    """
    Abstract base. Every transactional model in the project inherits this
    so we get created_at/updated_at for free.
    """
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Facility(TimeStampedModel):
    """
    A production site / brewery / taproom. Multi-facility is core to
    Ekos-style operations; every inventory lot, batch, order, and
    journal entry belongs to exactly one facility.
    """
    name = models.CharField(max_length=120)
    code = models.SlugField(unique=True)
    address = models.TextField(blank=True)
    ttb_registry_number = models.CharField(max_length=50, blank=True)
    timezone = models.CharField(max_length=64, default="UTC")

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "facilities"

    def __str__(self):
        return f"{self.name} ({self.code})"


class User(AbstractUser):
    """
    Custom user with a single role plus a facility M2M. Both are checked
    by the permission layer — see docs/PERMISSIONS.md.
    """
    ROLE_CHOICES = [
        ("admin", "Administrator"),
        ("brewer", "Brewer"),
        ("cellar", "Cellar Operator"),
        ("sales", "Sales"),
        ("finance", "Finance"),
        ("viewer", "Read-only"),
    ]
    role = models.CharField(
        max_length=20, choices=ROLE_CHOICES, default="viewer",
    )
    facilities = models.ManyToManyField(
        Facility,
        blank=True,
        related_name="members",
        help_text="Facilities this user can access. Superusers bypass this.",
    )

    def __str__(self):
        return self.username
