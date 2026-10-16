# apps/inventory/admin.py
from django.contrib import admin

from .models import (
    InventoryLot, Item, StockMovement, UnitConversion, UnitOfMeasure,
)


@admin.register(UnitOfMeasure)
class UnitOfMeasureAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "dimension", "is_base", "is_active")
    list_filter = ("dimension", "is_base", "is_active")
    search_fields = ("code", "name")
    readonly_fields = ("created_at", "updated_at")


@admin.register(UnitConversion)
class UnitConversionAdmin(admin.ModelAdmin):
    list_display = ("item", "from_unit", "to_unit", "factor")
    list_filter = ("from_unit__dimension",)
    search_fields = ("item__sku", "item__name")
    autocomplete_fields = ("item", "from_unit", "to_unit")


@admin.register(Item)
class ItemAdmin(admin.ModelAdmin):
    list_display = (
        "sku", "name", "category", "unit", "reorder_point", "is_active",
    )
    list_filter = ("category", "is_active", "unit__dimension")
    search_fields = ("sku", "name")
    autocomplete_fields = ("unit",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(InventoryLot)
class InventoryLotAdmin(admin.ModelAdmin):
    list_display = (
        "item", "lot_number", "facility",
        "quantity_on_hand", "unit_cost", "received_at",
    )
    list_filter = ("facility", "item__category")
    search_fields = ("lot_number", "item__sku", "item__name")
    readonly_fields = ("quantity_on_hand", "created_at", "updated_at")


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = (
        "id", "lot", "delta", "reason", "performed_by", "created_at",
    )
    list_filter = ("reason", "lot__facility")
    search_fields = ("lot__lot_number", "lot__item__sku", "reference", "note")
    readonly_fields = (
        "lot", "delta", "reason", "reference",
        "batch", "order_line", "performed_by",
        "note", "created_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
