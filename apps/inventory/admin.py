from django.contrib import admin
from .models import Item, InventoryLot, StockMovement


@admin.register(Item)
class ItemAdmin(admin.ModelAdmin):
    list_display = ("sku", "name", "category", "unit", "is_active")
    list_filter = ("category", "is_active")
    search_fields = ("sku", "name")


@admin.register(InventoryLot)
class InventoryLotAdmin(admin.ModelAdmin):
    list_display = ("item", "lot_number", "facility",
                    "quantity_on_hand", "unit_cost", "received_at")
    list_filter = ("facility", "item__category")
    search_fields = ("lot_number", "item__sku", "item__name")
    readonly_fields = ("quantity_on_hand",)


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = ("lot", "delta", "reason", "performed_by", "created_at")
    list_filter = ("reason",)
    search_fields = ("lot__lot_number", "lot__item__sku", "reference")
    readonly_fields = (
        "lot", "delta", "reason", "reference",
        "performed_by", "note", "created_at",
    )

    def has_add_permission(self, request):
        # Ledger is append-only via services, not admin.
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
