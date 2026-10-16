# apps/core/web_urls.py
from django.urls import path

from . import web_views

app_name = "core"

urlpatterns = [
    path("", web_views.dashboard, name="dashboard"),
]
