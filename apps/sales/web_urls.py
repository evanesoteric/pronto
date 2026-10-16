# apps/sales/web_urls.py
from django.urls import path

from . import web_views

app_name = "sales"

urlpatterns = [
    path("orders/", web_views.orders_list, name="orders_list"),
    path("orders/new/", web_views.order_create, name="order_create"),
    path("orders/<int:pk>/", web_views.order_detail, name="order_detail"),
    path("orders/<int:pk>/confirm/", web_views.order_confirm, name="order_confirm"),
    path("orders/<int:pk>/allocate/", web_views.order_allocate, name="order_allocate"),
    path("orders/<int:pk>/ship/", web_views.order_ship, name="order_ship"),
    path("orders/<int:pk>/cancel/", web_views.order_cancel, name="order_cancel"),

    path("customers/", web_views.customers_list, name="customers_list"),
    path("customers/<int:pk>/", web_views.customer_detail, name="customer_detail"),
]
