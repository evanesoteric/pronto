from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    BatchViewSet,
    RecipeIngredientViewSet,
    RecipeViewSet,
    TankViewSet,
)

router = DefaultRouter()
router.register("tanks", TankViewSet, basename="tank")
router.register("recipes", RecipeViewSet, basename="recipe")
router.register(
    "recipe-ingredients",
    RecipeIngredientViewSet,
    basename="recipe-ingredient",
)
router.register("batches", BatchViewSet, basename="batch")

urlpatterns = [
    path("", include(router.urls)),
]
