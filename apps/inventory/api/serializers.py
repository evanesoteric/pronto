from rest_framework import serializers

from apps.inventory.models import InventoryLot, Item, StockMovement


class ItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = Item
        fields = [
            "id", "sku", "name", "category", "unit",
            "reorder_point", "track_lot", "is_active",
            "created_at", "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]


class InventoryLotSerializer(serializers.ModelSerializer):
    item_sku = serializers.CharField(source="item.sku", read_only=True)
    item_name = serializers.CharField(source="item.name", read_only=True)
    facility_code = serializers.CharField(source="facility.code", read_only=True)

    class Meta:
        model = InventoryLot
        fields = [
            "id", "item", "item_sku", "item_name",
            "facility", "facility_code",
            "lot_number", "quantity_on_hand", "unit_cost",
            "received_at", "expires_at",
            "created_at", "updated_at",
        ]
        # quantity_on_hand is a cache — only services write it.
        read_only_fields = [
            "quantity_on_hand", "received_at",
            "created_at", "updated_at",
        ]


class StockMovementSerializer(serializers.ModelSerializer):
    item_sku = serializers.CharField(source="lot.item.sku", read_only=True)
    lot_number = serializers.CharField(source="lot.lot_number", read_only=True)
    performed_by_username = serializers.CharField(
        source="performed_by.username", read_only=True,
    )

    class Meta:
        model = StockMovement
        fields = [
            "id", "lot", "lot_number", "item_sku",
            "delta", "reason", "reference",
            "batch", "order_line",
            "performed_by", "performed_by_username",
            "note", "created_at",
        ]
        # Ledger rows are append-only via services, never created via API.
        read_only_fields = fields
