from django.core.management.base import BaseCommand

from apps.inventory import selectors


class Command(BaseCommand):
    help = "Print items below their reorder point."

    def handle(self, *args, **options):
        rows = list(selectors.low_stock_items())
        if not rows:
            self.stdout.write(self.style.SUCCESS("Nothing low on stock."))
            return
        for item in rows:
            self.stdout.write(
                f"{item.sku:>14}  on_hand={item.on_hand or 0}  "
                f"reorder={item.reorder_point} {item.unit}"
            )
