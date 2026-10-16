# apps/inventory/api/serializers.py
from rest_framework import serializers

from apps.inventory.models import (
    InventoryLot, Item, StockMovement, UnitConversion, UnitOfMeasure,
)


class UnitOfMeasureSerializer(serializers.ModelSerializer):
    dimension_display = serializers.CharField(
        source="get_dimension_display", read_only=True,
    )

    class Meta:
        model = UnitOfMeasure
        fields = [
            "id", "code", "name", "dimension", "dimension_display",
            "is_base", "is_active",
        ]


class UnitConversionSerializer(serializers.ModelSerializer):
    item_sku = serializers.CharField(source="item.sku", read_only=True)
    from_code = serializers.CharField(source="from_unit.code", read_only=True)
    to_code = serializers.CharField(source="to_unit.code", read_only=True)

    class Meta:
        model = UnitConversion
        fields = [
            "id", "item", "item_sku",
            "from_unit", "from_code",
            "to_unit", "to_code",
            "factor",
        ]


class ItemSerializer(serializers.ModelSerializer):
    unit_code = serializers.CharField(source="unit.code", read_only=True)
    unit_name = serializers.CharField(source="unit.name", read_only=True)
    unit_dimension = serializers.CharField(
        source="unit.dimension", read_only=True,
    )

    class Meta:
        model = Item
        fields = [
            "id", "sku", "name", "category",
            "unit", "unit_code", "unit_name", "unit_dimension",
            "reorder_point", "track_lot", "is_active",
            "created_at", "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]


class InventoryLotSerializer(serializers.ModelSerializer):
    item_sku = serializers.CharField(source="item.sku", read_only=True)
    item_name = serializers.CharField(source="item.name", read_only=True)
    item_unit = serializers.CharField(source="item.unit.code", read_only=True)
    facility_code = serializers.CharField(source="facility.code", read_only=True)

    class Meta:
        model = InventoryLot
        fields = [
            "id", "item", "item_sku", "item_name", "item_unit",
            "facility", "facility_code",
            "lot_number", "quantity_on_hand", "unit_cost",
            "received_at", "expires_at",
            "created_at", "updated_at",
        ]
        read_only_fields = [
            "quantity_on_hand", "received_at",
            "created_at", "updated_at",
        ]


class StockMovementSerializer(serializers.ModelSerializer):
    item_sku = serializers.CharField(source="lot.item.sku", read_only=True)
    item_unit = serializers.CharField(source="lot.item.unit.code", read_only=True)
    lot_number = serializers.CharField(source="lot.lot_number", read_only=True)
    performed_by_username = serializers.CharField(
        source="performed_by.username", read_only=True,
    )

    class Meta:
        model = StockMovement
        fields = [
            "id", "lot", "lot_number", "item_sku", "item_unit",
            "delta", "reason", "reference",
            "batch", "order_line",
            "performed_by", "performed_by_username",
            "note", "created_at",
        ]
        read_only_fields = fields
