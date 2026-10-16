from .signals import on
from . import services as barcode_services
from .printing import PrintJob


@on("inventory.lot.received")
def queue_lot_label(lot, copies=1, printer_name="", **_):
    barcode = barcode_services.issue_barcode(lot)
    PrintJob.objects.create(
        barcode=barcode, copies=copies, printer_name=printer_name,
    )


@on("production.batch.packaged")
def queue_finished_labels(batch, **kwargs):
    barcode = barcode_services.issue_barcode(batch)
    PrintJob.objects.create(barcode=barcode, copies=1)
