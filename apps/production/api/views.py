from decimal import Decimal

from django.core.exceptions import ValidationError
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.core.permissions import HasFacilityAccess
from apps.inventory.models import Item
from apps.inventory.services import InsufficientStock
from apps.production import selectors, services
from apps.production.models import (
    Batch, BatchStatus, Recipe, RecipeIngredient, Tank,
)
from apps.production.services import BatchStateError

from .serializers import (
    AdvanceStatusSerializer,
    BatchConsumptionSerializer,
    BatchCostSerializer,
    BatchSerializer,
    PackageBatchSerializer,
    RecipeIngredientSerializer,
    RecipeSerializer,
    StartBrewSerializer,
    TankSerializer,
    TransferToTankSerializer,
)


class TankViewSet(viewsets.ModelViewSet):
    serializer_class = TankSerializer
    permission_classes = [IsAuthenticated, HasFacilityAccess]
    filterset_fields = ["facility", "status"]

    def get_queryset(self):
        qs = Tank.objects.select_related("facility")
        if not self.request.user.is_superuser:
            qs = qs.filter(facility__in=self.request.user.facilities.all())
        return qs.order_by("facility", "name")


class RecipeViewSet(viewsets.ModelViewSet):
    queryset = Recipe.objects.prefetch_related("ingredients__item")
    serializer_class = RecipeSerializer
    permission_classes = [IsAuthenticated]
    filterset_fields = ["style"]
    search_fields = ["name", "style"]


class RecipeIngredientViewSet(viewsets.ModelViewSet):
    """
    CRUD for recipe ingredients. Lets you add/remove/update individual
    ingredients on a recipe without touching the recipe itself.
    """
    queryset = RecipeIngredient.objects.select_related("item", "recipe")
    serializer_class = RecipeIngredientSerializer
    permission_classes = [IsAuthenticated]
    filterset_fields = ["recipe", "stage", "item"]


class BatchViewSet(viewsets.ModelViewSet):
    serializer_class = BatchSerializer
    permission_classes = [IsAuthenticated, HasFacilityAccess]
    filterset_fields = ["status", "facility", "recipe"]
    search_fields = ["batch_number", "recipe__name"]

    def get_queryset(self):
        qs = Batch.objects.select_related("recipe", "tank", "facility")
        if not self.request.user.is_superuser:
            qs = qs.filter(facility__in=self.request.user.facilities.all())
        return qs.order_by("-created_at")

    @action(
        detail=True, methods=["post"],
        permission_classes=[IsAuthenticated, HasFacilityAccess],
    )
    def start_brew(self, request, pk=None):
        batch = self.get_object()
        ser = StartBrewSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            movements = services.start_brew(
                batch=batch, performed_by=request.user,
                scaling_factor=ser.validated_data["scaling_factor"],
            )
        except (BatchStateError, InsufficientStock, ValidationError) as e:
            return Response({"detail": str(e)}, status=status.HTTP_409_CONFLICT)
        batch.refresh_from_db()
        return Response({
            "batch": BatchSerializer(batch).data,
            "movements_created": len(movements),
        })

    @action(
        detail=True, methods=["post"],
        permission_classes=[IsAuthenticated, HasFacilityAccess],
    )
    def transfer_to_tank(self, request, pk=None):
        batch = self.get_object()
        ser = TransferToTankSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            tank = Tank.objects.get(pk=ser.validated_data["tank_id"])
        except Tank.DoesNotExist:
            return Response(
                {"detail": "Tank not found."}, status=status.HTTP_404_NOT_FOUND,
            )
        try:
            services.transfer_to_tank(
                batch=batch, tank=tank, performed_by=request.user,
            )
        except BatchStateError as e:
            return Response({"detail": str(e)}, status=status.HTTP_409_CONFLICT)
        batch.refresh_from_db()
        return Response(BatchSerializer(batch).data)

    @action(
        detail=True, methods=["post"],
        permission_classes=[IsAuthenticated, HasFacilityAccess],
    )
    def advance(self, request, pk=None):
        batch = self.get_object()
        ser = AdvanceStatusSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            services.advance_status(
                batch=batch,
                to_status=ser.validated_data["to_status"],
                performed_by=request.user,
            )
        except BatchStateError as e:
            return Response({"detail": str(e)}, status=status.HTTP_409_CONFLICT)
        batch.refresh_from_db()
        return Response(BatchSerializer(batch).data)

    @action(
        detail=True, methods=["post"],
        permission_classes=[IsAuthenticated, HasFacilityAccess],
    )
    def package(self, request, pk=None):
        batch = self.get_object()
        ser = PackageBatchSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            finished = Item.objects.get(pk=ser.validated_data["finished_item_id"])
        except Item.DoesNotExist:
            return Response(
                {"detail": "Finished item not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        try:
            services.package_batch(
                batch=batch,
                finished_item=finished,
                packaged_volume_liters=ser.validated_data["packaged_volume_liters"],
                containers=ser.validated_data["containers"],
                lot_number=ser.validated_data["lot_number"],
                performed_by=request.user,
            )
        except (BatchStateError, ValidationError) as e:
            return Response({"detail": str(e)}, status=status.HTTP_409_CONFLICT)
        batch.refresh_from_db()
        return Response(BatchSerializer(batch).data)

    @action(detail=True, methods=["get"])
    def consumption(self, request, pk=None):
        batch = self.get_object()
        rows = selectors.batch_consumption(batch)
        return Response(BatchConsumptionSerializer(rows, many=True).data)

    @action(detail=True, methods=["get"])
    def cost(self, request, pk=None):
        batch = self.get_object()
        total = selectors.batch_cost(batch)
        volume = batch.actual_volume_liters or batch.planned_volume_liters
        cost_per_liter = (
            (total / volume).quantize(Decimal("0.0001"))
            if volume > 0 else Decimal("0")
        )
        return Response(BatchCostSerializer({
            "total_cost": total,
            "volume_liters": volume,
            "cost_per_liter": cost_per_liter,
        }).data)
