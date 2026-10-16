from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import InventoryLotViewSet, ItemViewSet, StockMovementViewSet
# scan_views is optional for now — wire it once services are proven.
# from . import scan_views

router = DefaultRouter()
router.register("items", ItemViewSet, basename="item")
router.register("lots", InventoryLotViewSet, basename="lot")
router.register("movements", StockMovementViewSet, basename="movement")

urlpatterns = [
    path("", include(router.urls)),
    # path("scan/consume/", scan_views.scan_consume, name="scan_consume"),
    # path("scan/adjust/", scan_views.scan_adjust, name="scan_adjust"),
]
