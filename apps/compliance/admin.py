# apps/compliance/admin.py
from django.contrib import admin

from .models import TaxFiling, TTBReport


@admin.register(TTBReport)
class TTBReportAdmin(admin.ModelAdmin):
    list_display = (
        "facility", "period_start", "period_end", "status", "filed_at",
    )
    list_filter = ("status", "facility")
    readonly_fields = ("created_at", "updated_at", "filed_at")
    search_fields = ("facility__name",)


@admin.register(TaxFiling)
class TaxFilingAdmin(admin.ModelAdmin):
    list_display = (
        "facility", "jurisdiction", "period", "amount_owed", "filed_at",
    )
    list_filter = ("jurisdiction", "facility")
    readonly_fields = ("created_at", "updated_at")
