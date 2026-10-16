from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register("tokens", views.BarcodeViewSet, basename="barcode")

urlpatterns = [
    path("", include(router.urls)),
    path("scan/", views.resolve_scan, name="resolve_scan"),
    path("labels/lot/<int:lot_id>/", views.lot_label, name="lot_label"),
    path("labels/batch/<int:batch_id>/", views.batch_label, name="batch_label"),
    path("labels/order/<int:order_id>/", views.order_label, name="order_label"),
    path("labels/item/<int:item_id>/", views.item_label, name="item_label"),
]
