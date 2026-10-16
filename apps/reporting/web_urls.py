# apps/reporting/web_urls.py
from django.urls import path

from . import web_views

app_name = "reporting"

urlpatterns = [
    path("scan/", web_views.scan_anything, name="scan_anything"),
    path("print-queue/", web_views.print_queue, name="print_queue"),
    path("print-jobs/<int:pk>/pdf/", web_views.print_job_pdf, name="print_job_pdf"),
    path("print-jobs/<int:pk>/cancel/", web_views.print_job_cancel, name="print_job_cancel"),
    path("labels/lot/<int:pk>/", web_views.print_label_lot, name="print_label_lot"),
    path("labels/batch/<int:pk>/", web_views.print_label_batch, name="print_label_batch"),
    path("labels/order/<int:pk>/", web_views.print_label_order, name="print_label_order"),
    path("labels/item/<int:pk>/", web_views.print_label_item, name="print_label_item"),
]
