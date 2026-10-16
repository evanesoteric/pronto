from django.http import HttpResponse
from rest_framework import status, viewsets
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.barcodes import services as barcode_services
from apps.barcodes.labels import (
    render_lot_label_pdf, render_batch_label_pdf,
    render_order_label_pdf, render_sku_shelf_label_pdf,
)
from apps.barcodes.models import Barcode
from apps.barcodes.services import BarcodeError
from .serializers import BarcodeSerializer, ScanRequestSerializer


class BarcodeViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Barcode.objects.all()
    serializer_class = BarcodeSerializer
    filterset_fields = ["target_type", "target_id", "is_active"]


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def resolve_scan(request):
    ser = ScanRequestSerializer(data=request.data)
    ser.is_valid(raise_exception=True)
    try:
        target = barcode_services.resolve(ser.validated_data["token"])
    except BarcodeError as e:
        return Response({"detail": str(e)}, status=status.HTTP_404_NOT_FOUND)

    facility = getattr(target, "facility", None)
    if facility and not request.user.is_superuser:
        if not request.user.facilities.filter(pk=facility.pk).exists():
            return Response(
                {"detail": "Barcode is for a different facility."},
                status=status.HTTP_404_NOT_FOUND,
            )

    return Response({
        "target_type": type(target).__name__,
        "target_id": target.pk,
        "display": str(target),
    })


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def lot_label(request, lot_id):
    from apps.inventory.models import InventoryLot
    lot = InventoryLot.objects.select_related("item", "facility").get(pk=lot_id)
    if not _can_access(request.user, lot):
        return Response(status=status.HTTP_404_NOT_FOUND)
    pdf = render_lot_label_pdf(lot)
    return _pdf_response(pdf, f"lot-{lot.lot_number}.pdf")


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def batch_label(request, batch_id):
    from apps.production.models import Batch
    batch = Batch.objects.select_related("recipe", "facility", "tank").get(pk=batch_id)
    if not _can_access(request.user, batch):
        return Response(status=status.HTTP_404_NOT_FOUND)
    pdf = render_batch_label_pdf(batch)
    return _pdf_response(pdf, f"batch-{batch.batch_number}.pdf")


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def order_label(request, order_id):
    from apps.sales.models import Order
    order = Order.objects.select_related("customer", "facility").get(pk=order_id)
    if not _can_access(request.user, order):
        return Response(status=status.HTTP_404_NOT_FOUND)
    pdf = render_order_label_pdf(order)
    return _pdf_response(pdf, f"order-{order.number}.pdf")


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def item_label(request, item_id):
    from apps.inventory.models import Item
    item = Item.objects.get(pk=item_id)
    pdf = render_sku_shelf_label_pdf(item)
    return _pdf_response(pdf, f"item-{item.sku}.pdf")


def _pdf_response(pdf_bytes: bytes, filename: str) -> HttpResponse:
    resp = HttpResponse(pdf_bytes, content_type="application/pdf")
    resp["Content-Disposition"] = f'inline; filename="{filename}"'
    return resp


def _can_access(user, obj) -> bool:
    if user.is_superuser:
        return True
    facility = getattr(obj, "facility", None)
    if facility is None:
        return True
    return user.facilities.filter(pk=facility.pk).exists()
