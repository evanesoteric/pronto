from django.core.management.base import BaseCommand

from apps.inventory import selectors
from apps.inventory.models import InventoryLot


class Command(BaseCommand):
    help = "Detect (and optionally repair) inventory cache drift vs. the ledger."

    def add_arguments(self, parser):
        parser.add_argument(
            "--fix", action="store_true",
            help="Repair drifted lots automatically.",
        )

    def handle(self, *args, **options):
        drifted = 0
        for lot, cached, ledger in selectors.ledger_reconciliation():
            drifted += 1
            self.stdout.write(self.style.WARNING(
                f"DRIFT lot={lot.lot_number} item={lot.item.sku} "
                f"cache={cached} ledger={ledger}"
            ))
            if options["fix"]:
                InventoryLot.objects.filter(pk=lot.pk).update(
                    quantity_on_hand=ledger,
                )
                self.stdout.write(self.style.SUCCESS(f"  repaired to {ledger}"))

        if drifted == 0:
            self.stdout.write(self.style.SUCCESS("All lots reconcile."))
        else:
            self.stdout.write(f"{drifted} lot(s) drifted.")
