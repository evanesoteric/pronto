from decimal import Decimal
from django.core.exceptions import ValidationError

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.core.permissions import HasFacilityAccess
from apps.inventory import services, selectors

from apps.inventory.models import (
    InventoryLot, Item, StockMovement, UnitConversion, UnitOfMeasure,
)
from .serializers import (
    InventoryLotSerializer, ItemSerializer, StockMovementSerializer,
    UnitConversionSerializer, UnitOfMeasureSerializer,
)


class UnitOfMeasureViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = UnitOfMeasure.objects.all()
    serializer_class = UnitOfMeasureSerializer
    permission_classes = [IsAuthenticated]
    filterset_fields = ["dimension", "is_base", "is_active"]


class UnitConversionViewSet(viewsets.ModelViewSet):
    queryset = UnitConversion.objects.select_related(
        "item", "from_unit", "to_unit",
    )
    serializer_class = UnitConversionSerializer
    permission_classes = [IsAuthenticated]
    filterset_fields = ["item", "from_unit", "to_unit"]


class ItemViewSet(viewsets.ModelViewSet):
    """
    Items are global (not facility-scoped) — the same SKU exists at
    every facility. Facility scoping happens at the lot level.
    """
    queryset = Item.objects.all().order_by("sku")
    serializer_class = ItemSerializer
    permission_classes = [IsAuthenticated]
    filterset_fields = ["category", "is_active", "track_lot"]
    search_fields = ["sku", "name"]

    @action(detail=False, methods=["get"])
    def low_stock(self, request):
        facility_code = request.query_params.get("facility")
        facility = None
        if facility_code:
            from apps.core.models import Facility
            facility = Facility.objects.filter(code=facility_code).first()
            if facility and not request.user.is_superuser:
                if not request.user.facilities.filter(pk=facility.pk).exists():
                    return Response({"detail": "Not your facility."},
                                    status=status.HTTP_404_NOT_FOUND)
        qs = selectors.low_stock_items(facility=facility)
        return Response(ItemSerializer(qs, many=True).data)


class InventoryLotViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Lots are read-only via API. Creation and mutation happen through
    services (receive_stock, consume_stock, adjust_stock) via scan
    endpoints or admin actions. The API surfaces state; it does not
    create it.
    """
    serializer_class = InventoryLotSerializer
    permission_classes = [IsAuthenticated, HasFacilityAccess]
    filterset_fields = ["item", "facility", "lot_number"]
    search_fields = ["lot_number", "item__sku", "item__name"]

    def get_queryset(self):
        qs = InventoryLot.objects.select_related("item", "facility")
        if not self.request.user.is_superuser:
            qs = qs.filter(facility__in=self.request.user.facilities.all())
        return qs.order_by("-created_at")

    @action(detail=True, methods=["get"])
    def history(self, request, pk=None):
        lot = self.get_object()
        movements = selectors.lot_history(lot)
        return Response(StockMovementSerializer(movements, many=True).data)

    @action(
        detail=False, methods=["post"],
        permission_classes=[IsAuthenticated],
    )
    def receive(self, request):
        """
        Receive stock via API. Body:
            {item_id, facility_id, lot_number, quantity, unit_cost,
            reference?, expires_at?}
        """
        data = request.data
        try:
            item = Item.objects.get(pk=data["item_id"])
            from apps.core.models import Facility
            facility = Facility.objects.get(pk=data["facility_id"])
        except (KeyError, Item.DoesNotExist, Facility.DoesNotExist) as e:
            return Response(
                {"detail": f"Invalid item or facility: {e}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not request.user.is_superuser:
            if not request.user.facilities.filter(pk=facility.pk).exists():
                return Response(
                    {"detail": "Not your facility."},
                    status=status.HTTP_404_NOT_FOUND,
                )

        try:
            movement = services.receive_stock(
                item=item,
                facility=facility,
                lot_number=data["lot_number"],
                quantity=Decimal(str(data["quantity"])),
                unit_cost=Decimal(str(data["unit_cost"])),
                performed_by=request.user,
                reference=data.get("reference", ""),
                note=data.get("note", ""),
            )
        except (KeyError, ValidationError) as e:
            return Response(
                {"detail": str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            StockMovementSerializer(movement).data,
            status=status.HTTP_201_CREATED,
        )


class StockMovementViewSet(viewsets.ReadOnlyModelViewSet):
    """Ledger is read-only through the API, always."""
    serializer_class = StockMovementSerializer
    permission_classes = [IsAuthenticated]
    filterset_fields = ["reason", "batch", "order_line", "lot"]
    search_fields = ["reference", "note", "lot__lot_number", "lot__item__sku"]

    def get_queryset(self):
        qs = StockMovement.objects.select_related(
            "lot__item", "lot__facility", "performed_by",
        )
        if not self.request.user.is_superuser:
            qs = qs.filter(lot__facility__in=self.request.user.facilities.all())
        return qs.order_by("-created_at")
