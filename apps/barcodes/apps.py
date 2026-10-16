from django.apps import AppConfig


class BarcodesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.barcodes"
    label = "barcodes"

    def ready(self):
        from . import handlers  # noqa: F401
