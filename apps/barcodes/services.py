from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.apps import apps as django_apps

from .models import Barcode, BarcodeTarget


class BarcodeError(ValidationError):
    pass


_TARGET_MODELS = {
    BarcodeTarget.INVENTORY_LOT: ("inventory", "InventoryLot"),
    BarcodeTarget.BATCH: ("production", "Batch"),
    BarcodeTarget.ORDER: ("sales", "Order"),
    BarcodeTarget.ITEM: ("inventory", "Item"),
}


@transaction.atomic
def issue_barcode(target, *, note: str = "") -> Barcode:
    target_type = _target_type_for(target)
    existing = Barcode.objects.filter(
        target_type=target_type, target_id=target.pk, is_active=True,
    ).first()
    if existing:
        return existing
    return Barcode.objects.create(
        token=Barcode.new_token(),
        target_type=target_type,
        target_id=target.pk,
        note=note,
    )


@transaction.atomic
def revoke_barcode(barcode: Barcode) -> None:
    barcode.is_active = False
    barcode.save(update_fields=["is_active", "updated_at"])


@transaction.atomic
def mark_printed(barcode: Barcode) -> None:
    barcode.printed_at = timezone.now()
    barcode.save(update_fields=["printed_at", "updated_at"])


def resolve(token: str):
    try:
        barcode = Barcode.objects.get(token=token, is_active=True)
    except Barcode.DoesNotExist:
        raise BarcodeError(f"Unknown or revoked barcode: {token}")

    app_label, model_name = _TARGET_MODELS[barcode.target_type]
    model = django_apps.get_model(app_label, model_name)
    try:
        return model.objects.get(pk=barcode.target_id)
    except model.DoesNotExist:
        raise BarcodeError(
            f"Barcode {token} points to a missing {model_name}."
        )


def _target_type_for(target) -> str:
    name = type(target).__name__
    for target_type, (_app, model_name) in _TARGET_MODELS.items():
        if name == model_name:
            return target_type
    raise BarcodeError(f"No barcode target type registered for {name}.")
