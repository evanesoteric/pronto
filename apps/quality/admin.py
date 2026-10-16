# apps/quality/admin.py
from django.contrib import admin

from .models import FermentationReading, QCTest


@admin.register(FermentationReading)
class FermentationReadingAdmin(admin.ModelAdmin):
    list_display = (
        "batch", "reading_at", "gravity", "temperature_c", "ph",
        "recorded_by",
    )
    list_filter = ("batch__facility",)
    search_fields = ("batch__batch_number",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(QCTest)
class QCTestAdmin(admin.ModelAdmin):
    list_display = (
        "batch", "test_type", "is_gate", "passed",
        "result_value", "performed_at", "performed_by",
    )
    list_filter = ("test_type", "is_gate", "passed")
    search_fields = ("batch__batch_number", "notes")
    readonly_fields = ("created_at", "updated_at")
