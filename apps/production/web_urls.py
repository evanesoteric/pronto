# apps/production/web_urls.py
from django.urls import path

from . import web_views

app_name = "production"

urlpatterns = [
    # Batches
    path("batches/", web_views.batches_list, name="batches_list"),
    path("batches/new/", web_views.batch_create, name="batch_create"),
    path("batches/<int:pk>/", web_views.batch_detail, name="batch_detail"),
    path("batches/<int:pk>/start-brew/", web_views.batch_start_brew, name="batch_start_brew"),
    path("batches/<int:pk>/transfer/", web_views.batch_transfer, name="batch_transfer"),
    path("batches/<int:pk>/advance/", web_views.batch_advance, name="batch_advance"),
    path("batches/<int:pk>/package/", web_views.batch_package, name="batch_package"),
    path("batches/<int:pk>/scan-brew/", web_views.scan_brew, name="scan_brew"),

    # Tanks
    path("tanks/", web_views.tanks_list, name="tanks_list"),
    path("tanks/<int:pk>/", web_views.tank_detail, name="tank_detail"),

    # Recipes
    path("recipes/", web_views.recipes_list, name="recipes_list"),
    path("recipes/new/", web_views.recipe_create, name="recipe_create"),
    path("recipes/<int:pk>/", web_views.recipe_detail, name="recipe_detail"),
    path("recipes/<int:pk>/edit/", web_views.recipe_edit, name="recipe_edit"),
]
