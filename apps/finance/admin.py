# apps/finance/admin.py
from django.contrib import admin

from .models import AccountingPeriod, BatchCost, JournalEntry, JournalLine


class JournalLineInline(admin.TabularInline):
    model = JournalLine
    extra = 0


@admin.register(JournalEntry)
class JournalEntryAdmin(admin.ModelAdmin):
    list_display = ("id", "facility", "memo", "posted_at", "reference")
    list_filter = ("facility",)
    search_fields = ("memo", "reference")
    readonly_fields = ("created_at", "updated_at", "posted_at")
    inlines = [JournalLineInline]


@admin.register(BatchCost)
class BatchCostAdmin(admin.ModelAdmin):
    list_display = (
        "batch", "total_cost", "volume_liters",
        "cost_per_liter", "computed_at",
    )
    search_fields = ("batch__batch_number",)
    readonly_fields = ("computed_at",)


@admin.register(AccountingPeriod)
class AccountingPeriodAdmin(admin.ModelAdmin):
    list_display = ("facility", "year", "month", "closed_at", "closed_by")
    list_filter = ("facility", "year")
    readonly_fields = ("created_at", "updated_at")
