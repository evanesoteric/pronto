# apps/inventory/web_urls.py
from django.urls import path

from . import web_views

app_name = "inventory"

urlpatterns = [
    path("lots/", web_views.lots_list, name="lots_list"),
    path("lots/<int:pk>/", web_views.lot_detail, name="lot_detail"),
    path("receive/", web_views.receive_form, name="receive_form"),
    path("receive/success/", web_views.receive_success, name="receive_success"),
]
