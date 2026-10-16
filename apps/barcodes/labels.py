import io

import barcode as barcode_lib
from barcode.writer import ImageWriter
from reportlab.lib.pagesizes import inch
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from . import services as barcode_services


LABEL_WIDTH = 2.25 * inch
LABEL_HEIGHT = 1.25 * inch


def render_lot_label_pdf(lot) -> bytes:
    barcode = barcode_services.issue_barcode(lot)
    barcode_services.mark_printed(barcode)

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(LABEL_WIDTH, LABEL_HEIGHT))

    c.setFont("Helvetica-Bold", 8)
    c.drawString(4 * mm, LABEL_HEIGHT - 5 * mm, lot.item.name[:30])
    c.setFont("Helvetica", 7)
    c.drawString(4 * mm, LABEL_HEIGHT - 9 * mm, f"SKU: {lot.item.sku}")
    c.setFont("Helvetica-Bold", 9)
    c.drawString(4 * mm, LABEL_HEIGHT - 14 * mm, f"LOT: {lot.lot_number}")
    c.setFont("Helvetica", 6)
    received = lot.received_at.strftime("%Y-%m-%d") if lot.received_at else "—"
    c.drawString(
        4 * mm, LABEL_HEIGHT - 18 * mm,
        f"Facility: {lot.facility.code}  |  Recv: {received}",
    )

    _draw_barcode(c, barcode.token, x=4 * mm, y=4 * mm, width=42 * mm, height=10 * mm)
    c.showPage()
    c.save()
    return buf.getvalue()


def render_batch_label_pdf(batch) -> bytes:
    barcode = barcode_services.issue_barcode(batch)
    barcode_services.mark_printed(barcode)

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(LABEL_WIDTH, LABEL_HEIGHT))

    c.setFont("Helvetica-Bold", 8)
    c.drawString(4 * mm, LABEL_HEIGHT - 5 * mm, batch.recipe.name[:30])
    c.setFont("Helvetica-Bold", 10)
    c.drawString(4 * mm, LABEL_HEIGHT - 11 * mm, f"BATCH: {batch.batch_number}")
    c.setFont("Helvetica", 6)
    brew = batch.brew_date.isoformat() if batch.brew_date else "—"
    tank = batch.tank.name if batch.tank else "—"
    c.drawString(
        4 * mm, LABEL_HEIGHT - 15 * mm,
        f"Facility: {batch.facility.code}  |  Brew: {brew}  |  Tank: {tank}",
    )

    _draw_barcode(c, barcode.token, x=4 * mm, y=4 * mm, width=42 * mm, height=10 * mm)
    c.showPage()
    c.save()
    return buf.getvalue()


def render_order_label_pdf(order) -> bytes:
    barcode = barcode_services.issue_barcode(order)
    barcode_services.mark_printed(barcode)

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(LABEL_WIDTH, LABEL_HEIGHT))

    c.setFont("Helvetica-Bold", 8)
    c.drawString(4 * mm, LABEL_HEIGHT - 5 * mm, order.customer.name[:30])
    c.setFont("Helvetica-Bold", 10)
    c.drawString(4 * mm, LABEL_HEIGHT - 11 * mm, f"ORDER: {order.number}")
    c.setFont("Helvetica", 6)
    c.drawString(
        4 * mm, LABEL_HEIGHT - 15 * mm,
        f"Facility: {order.facility.code}  |  Date: {order.order_date}",
    )

    _draw_barcode(c, barcode.token, x=4 * mm, y=4 * mm, width=42 * mm, height=10 * mm)
    c.showPage()
    c.save()
    return buf.getvalue()


def render_sku_shelf_label_pdf(item) -> bytes:
    barcode = barcode_services.issue_barcode(item)
    barcode_services.mark_printed(barcode)

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(LABEL_WIDTH, LABEL_HEIGHT))

    c.setFont("Helvetica-Bold", 9)
    c.drawString(4 * mm, LABEL_HEIGHT - 6 * mm, item.name[:32])
    c.setFont("Helvetica", 7)
    c.drawString(4 * mm, LABEL_HEIGHT - 11 * mm, f"SKU: {item.sku}")
    c.drawString(4 * mm, LABEL_HEIGHT - 15 * mm, f"Unit: {item.unit}")

    _draw_barcode(c, barcode.token, x=4 * mm, y=4 * mm, width=42 * mm, height=10 * mm)
    c.showPage()
    c.save()
    return buf.getvalue()


def _draw_barcode(c, token: str, *, x, y, width, height):
    code = barcode_lib.get("code128", token, writer=ImageWriter())
    png_buf = io.BytesIO()
    code.write(png_buf, options={"module_height": 8.0, "font_size": 0})
    png_buf.seek(0)

    c.drawImage(
        ImageReader(png_buf), x, y, width=width, height=height,
        preserveAspectRatio=True, anchor="sw",
    )
    c.setFont("Helvetica", 5)
    c.drawString(x, y - 3 * mm, token)
