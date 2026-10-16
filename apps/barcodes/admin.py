from django.contrib import admin
from .models import Barcode
from .printing import PrintJob


@admin.register(Barcode)
class BarcodeAdmin(admin.ModelAdmin):
    list_display = ("token", "target_type", "target_id", "is_active", "printed_at")
    list_filter = ("target_type", "is_active")
    search_fields = ("token",)
    readonly_fields = ("token", "created_at", "updated_at")


@admin.register(PrintJob)
class PrintJobAdmin(admin.ModelAdmin):
    list_display = ("id", "barcode", "copies", "status", "created_at", "printed_at")
    list_filter = ("status",)
    readonly_fields = ("created_at", "updated_at")
