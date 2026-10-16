from django.contrib import admin
from django.urls import include, path
from django.conf import settings
from django.conf.urls.static import static
from django.contrib.auth import views as auth_views

from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

urlpatterns = [
    # Auth
    path("accounts/login/", auth_views.LoginView.as_view(), name="login"),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),

    # Admin
    path("admin/", admin.site.urls),

    # DRF login/logout under /api-auth/
    # path("api-auth/", include("rest_framework.urls")),

    # API
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema")),
    path("api/barcodes/", include("apps.barcodes.api.urls")),
    path("api/inventory/", include("apps.inventory.api.urls")),
    path("api/production/", include("apps.production.api.urls")),

    # Panel
    path("inventory/", include("apps.inventory.web_urls")),
    path("production/", include("apps.production.web_urls")),
    path("sales/", include("apps.sales.web_urls")),
    path("", include("apps.reporting.web_urls")),
    path("", include("apps.core.web_urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
