from decimal import Decimal

from rest_framework import serializers

from apps.production.models import Batch, Recipe, RecipeIngredient, Tank


class TankSerializer(serializers.ModelSerializer):
    facility_code = serializers.CharField(source="facility.code", read_only=True)

    class Meta:
        model = Tank
        fields = [
            "id", "facility", "facility_code",
            "name", "capacity_liters", "status",
            "created_at", "updated_at",
        ]
        read_only_fields = ["status", "created_at", "updated_at"]


class RecipeIngredientSerializer(serializers.ModelSerializer):
    item_sku = serializers.CharField(source="item.sku", read_only=True)
    item_name = serializers.CharField(source="item.name", read_only=True)
    item_unit = serializers.CharField(source="item.unit.code", read_only=True)

    class Meta:
        model = RecipeIngredient
        fields = [
            "id", "recipe", "item",
            "item_sku", "item_name", "item_unit",
            "quantity", "stage", "notes",
        ]


class RecipeSerializer(serializers.ModelSerializer):
    ingredients = RecipeIngredientSerializer(many=True, read_only=True)

    class Meta:
        model = Recipe
        fields = [
            "id", "name", "version", "style",
            "target_og", "target_fg", "target_abv", "notes",
            "ingredients", "created_at", "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]


class BatchSerializer(serializers.ModelSerializer):
    recipe_name = serializers.CharField(source="recipe.name", read_only=True)
    recipe_version = serializers.IntegerField(source="recipe.version", read_only=True)
    facility_code = serializers.CharField(source="facility.code", read_only=True)
    tank_name = serializers.CharField(source="tank.name", read_only=True, default=None)
    status_display = serializers.CharField(
        source="get_status_display", read_only=True,
    )

    class Meta:
        model = Batch
        fields = [
            "id", "batch_number",
            "recipe", "recipe_name", "recipe_version",
            "facility", "facility_code",
            "tank", "tank_name",
            "status", "status_display",
            "planned_volume_liters", "actual_volume_liters",
            "brew_date", "packaged_at", "closed_at",
            "notes",
            "created_at", "updated_at",
        ]
        read_only_fields = [
            "status", "actual_volume_liters",
            "brew_date", "packaged_at", "closed_at",
            "created_at", "updated_at",
        ]


class StartBrewSerializer(serializers.Serializer):
    scaling_factor = serializers.DecimalField(
        max_digits=6, decimal_places=3, default=Decimal("1.0"),
        min_value=Decimal("0.001"),
    )


class TransferToTankSerializer(serializers.Serializer):
    tank_id = serializers.IntegerField()


class AdvanceStatusSerializer(serializers.Serializer):
    to_status = serializers.ChoiceField(choices=[
        "brewing", "fermenting", "conditioning", "packaged", "closed",
    ])


class PackageBatchSerializer(serializers.Serializer):
    finished_item_id = serializers.IntegerField()
    packaged_volume_liters = serializers.DecimalField(
        max_digits=10, decimal_places=2, min_value=Decimal("0.01"),
    )
    containers = serializers.IntegerField(min_value=0)
    lot_number = serializers.CharField(max_length=80)


class BatchConsumptionSerializer(serializers.Serializer):
    lot__item__sku = serializers.CharField()
    lot__item__name = serializers.CharField()
    lot__item__unit__code = serializers.CharField()
    total = serializers.DecimalField(max_digits=14, decimal_places=3)


class BatchCostSerializer(serializers.Serializer):
    total_cost = serializers.DecimalField(max_digits=14, decimal_places=4)
    volume_liters = serializers.DecimalField(max_digits=10, decimal_places=2)
    cost_per_liter = serializers.DecimalField(max_digits=10, decimal_places=4)
