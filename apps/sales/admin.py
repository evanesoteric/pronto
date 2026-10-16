# apps/sales/admin.py
from django.contrib import admin

from .models import Customer, Order, OrderLine, StockAllocation


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ("account_number", "name", "email", "price_tier", "is_active")
    list_filter = ("is_active", "price_tier", "tax_exempt")
    search_fields = ("account_number", "name", "email")
    readonly_fields = ("created_at", "updated_at")


class OrderLineInline(admin.TabularInline):
    model = OrderLine
    extra = 0
    readonly_fields = ("created_at", "updated_at")


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = (
        "number", "customer", "facility", "status",
        "order_date", "shipped_at",
    )
    list_filter = ("status", "facility")
    search_fields = ("number", "customer__name", "customer__account_number")
    readonly_fields = ("created_at", "updated_at", "shipped_at", "invoiced_at")
    inlines = [OrderLineInline]


@admin.register(OrderLine)
class OrderLineAdmin(admin.ModelAdmin):
    list_display = ("order", "item", "quantity", "unit_price", "backordered")
    list_filter = ("backordered",)
    search_fields = ("order__number", "item__sku", "item__name")


@admin.register(StockAllocation)
class StockAllocationAdmin(admin.ModelAdmin):
    list_display = (
        "order_line", "lot", "quantity", "released_at", "created_at",
    )
    list_filter = ("released_at",)
    search_fields = (
        "order_line__order__number",
        "lot__lot_number",
        "lot__item__sku",
    )
    readonly_fields = ("created_at", "updated_at")
