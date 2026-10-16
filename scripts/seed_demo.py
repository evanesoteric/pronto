# scripts/seed_demo.py
"""
Seed the database with a realistic set of demo data:
facilities, items, inventory lots, barcodes, print jobs,
plus a couple of recipes, tanks, and batches.

Idempotent — safe to run multiple times.

Usage:
    python manage.py shell < scripts/seed_demo.py
"""

from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.core.models import Facility
from apps.inventory.models import (
    InventoryLot, Item, ItemCategory, MovementReason,
    StockMovement, UnitOfMeasure,
)
from apps.inventory import services as inv_services
from apps.production.models import (
    Batch, BatchStatus, Recipe, RecipeIngredient, Tank,
)
from apps.production import services as prod_services
from apps.barcodes import services as barcode_services
from apps.barcodes.printing import PrintJob, PrintJobStatus


User = get_user_model()
user = User.objects.filter(is_superuser=True).first()
if user is None:
    raise SystemExit(
        "No superuser found. Run `python manage.py createsuperuser` first."
    )

# ---------------------------------------------------------------------------
# Reference data
# ---------------------------------------------------------------------------

kg = UnitOfMeasure.objects.get(code="kg")
liter = UnitOfMeasure.objects.get(code="L")
each = UnitOfMeasure.objects.get(code="each")
keg = UnitOfMeasure.objects.get(code="keg")
case = UnitOfMeasure.objects.get(code="case")
bottle = UnitOfMeasure.objects.get(code="bottle")
can = UnitOfMeasure.objects.get(code="can")

facility, _ = Facility.objects.get_or_create(
    code="main",
    defaults={
        "name": "Main Brewery",
        "ttb_registry_number": "TTB-DEMO-0001",
    },
)

print(f"Facility: {facility}")


# ---------------------------------------------------------------------------
# Items
# ---------------------------------------------------------------------------

ITEMS = [
    # (sku, name, category, unit_code, reorder_point)
    ("MALT-2ROW",       "2-Row Pale Malt",          "malt",      "kg",    "500"),
    ("MALT-PILS",       "Pilsner Malt",             "malt",      "kg",    "300"),
    ("MALT-CRYS",       "Crystal 60L Malt",         "malt",      "kg",    "100"),
    ("HOPS-CASCADE",    "Cascade Hops",             "hops",      "kg",    "20"),
    ("HOPS-CITRA",      "Citra Hops",               "hops",      "kg",    "15"),
    ("HOPS-MOSAIC",     "Mosaic Hops",              "hops",      "kg",    "10"),
    ("YEAST-US05",      "US-05 Ale Yeast",          "yeast",     "kg",    "5"),
    ("YEAST-WLP001",    "WLP001 California Ale",    "yeast",     "each",  "10"),
    ("ADJ-CORNSUGAR",   "Corn Sugar",               "adjunct",   "kg",    "50"),
    ("ADJ-LACTOSE",     "Lactose",                  "adjunct",   "kg",    "30"),

    ("PKG-KEG-1_2",     "1/2 BBL Keg Shell",        "packaging", "each",  "50"),
    ("PKG-CASE-24",     "Case Box (24ct)",          "packaging", "each",  "200"),
    ("PKG-BOTTLE-12OZ", "12oz Bottle",              "packaging", "each",  "1000"),
    ("PKG-CAN-16OZ",    "16oz Can",                 "packaging", "each",  "2000"),
    ("PKG-LABEL-PALE",  "Pale Ale Case Label",      "packaging", "each",  "500"),

    ("KEG-PALE",        "Pale Ale (1/2 BBL Keg)",   "finished",  "keg",   "20"),
    ("KEG-IPA",         "West Coast IPA (1/2 BBL Keg)", "finished", "keg", "10"),
    ("CASE-PALE",       "Pale Ale (24 × 12oz bottles)", "finished", "case", "30"),
    ("CASE-IPA",        "West Coast IPA (24 × 12oz bottles)", "finished", "case", "15"),
    ("CASE-LAGER",      "House Lager (24 × 12oz cans)", "finished", "case", "25"),
]

created_items = []
for sku, name, category, unit_code, reorder in ITEMS:
    unit = UnitOfMeasure.objects.get(code=unit_code)
    item, created = Item.objects.get_or_create(
        sku=sku,
        defaults={
            "name": name,
            "category": category,
            "unit": unit,
            "reorder_point": Decimal(reorder),
            "is_active": True,
        },
    )
    created_items.append(item)

print(f"Items: {Item.objects.count()} total ({len(created_items)} processed)")


# ---------------------------------------------------------------------------
# Inventory lots
# ---------------------------------------------------------------------------

# (sku, lot_number, quantity, unit_cost, days_ago_received, expires_in_days or None)
LOTS = [
    # Malts — several lots each, staggered arrivals
    ("MALT-2ROW",     "MALT-2026-001", "1000", "1.10", 30, 365),
    ("MALT-2ROW",     "MALT-2026-002", "1500", "1.15", 15, 400),
    ("MALT-2ROW",     "MALT-2026-003", "2000", "1.12",  5, 420),
    ("MALT-PILS",     "PILS-2026-001", "800",  "1.25", 20, 365),
    ("MALT-PILS",     "PILS-2026-002", "1200", "1.28",  7, 400),
    ("MALT-CRYS",     "CRYS-2026-001", "250",  "1.80", 45, 500),
    ("MALT-CRYS",     "CRYS-2026-002", "180",  "1.85", 10, 500),

    # Hops — often split into smaller lots
    ("HOPS-CASCADE",  "HOP-CAS-2025-A", "25", "18.50", 60, 180),
    ("HOPS-CASCADE",  "HOP-CAS-2026-A", "30", "19.00", 20, 240),
    ("HOPS-CITRA",    "HOP-CIT-2026-A", "20", "24.00", 25, 240),
    ("HOPS-MOSAIC",   "HOP-MOS-2026-A", "15", "26.00", 15, 240),

    # Yeast
    ("YEAST-US05",    "YST-US05-001",   "10", "45.00", 10, 180),
    ("YEAST-WLP001",  "YST-WLP-001",    "8",  "8.50",  20, 120),

    # Adjuncts
    ("ADJ-CORNSUGAR", "SUGAR-2026-001", "200", "0.95", 30, 730),
    ("ADJ-LACTOSE",   "LACT-2026-001",  "100", "2.40", 45, 730),

    # Packaging — lots of empty containers
    ("PKG-KEG-1_2",   "KEGS-2026-001",  "300", "85.00", 90, None),
    ("PKG-CASE-24",   "CASES-2026-001", "5000", "0.35", 90, None),
    ("PKG-BOTTLE-12OZ","BOTTLES-2026-001","20000","0.12",90, None),
    ("PKG-CAN-16OZ",  "CANS-2026-001",  "30000","0.18", 60, None),
    ("PKG-LABEL-PALE","LBL-PALE-001",   "5000", "0.05", 45, None),

    # Finished goods — Pale Ale kegs
    ("KEG-PALE",      "PALE-KEG-2026-W40-1", "120", "28.00", 7, 90),
    ("KEG-PALE",      "PALE-KEG-2026-W41-1", "100", "28.00", 3, 90),
    ("KEG-IPA",       "IPA-KEG-2026-W40-1",  "80",  "34.00", 6, 90),
    ("KEG-IPA",       "IPA-KEG-2026-W41-1",  "60",  "34.00", 2, 90),

    # Finished goods — Cases
    ("CASE-PALE",     "PALE-CASE-2026-W40-1", "150", "32.00", 7, 180),
    ("CASE-PALE",     "PALE-CASE-2026-W41-1", "180", "32.00", 3, 180),
    ("CASE-IPA",      "IPA-CASE-2026-W40-1",  "100", "38.00", 6, 180),
    ("CASE-LAGER",    "LAGER-CASE-2026-W41-1", "200", "28.00", 4, 180),
]

created_lots = 0
now = timezone.now()

for sku, lot_number, qty, cost, days_ago, expires_in in LOTS:
    item = Item.objects.get(sku=sku)

    # Skip if this lot already exists (idempotent)
    if InventoryLot.objects.filter(
        item=item, facility=facility, lot_number=lot_number,
    ).exists():
        continue

    received_at = now - timedelta(days=days_ago)
    expires_at = now + timedelta(days=expires_in) if expires_in else None

    inv_services.receive_stock(
        item=item,
        facility=facility,
        lot_number=lot_number,
        quantity=Decimal(qty),
        unit_cost=Decimal(cost),
        performed_by=user,
        received_at=received_at,
        expires_at=expires_at,
        reference=f"SEED-{lot_number}",
        auto_print_label=True,
    )
    created_lots += 1

print(f"Lots created this run: {created_lots}")
print(f"Total lots: {InventoryLot.objects.count()}")


# ---------------------------------------------------------------------------
# Item barcodes (shelf labels)
# ---------------------------------------------------------------------------

item_barcodes = 0
for item in Item.objects.all():
    b = barcode_services.issue_barcode(item)
    if b.created_at >= now - timedelta(minutes=5):
        item_barcodes += 1

print(f"Item barcodes: {item_barcodes} new")


# ---------------------------------------------------------------------------
# Sample tanks, recipes, batches
# ---------------------------------------------------------------------------

TANKS = ["FV-1", "FV-2", "FV-3", "FV-4", "BRIGHT-1", "BRIGHT-2"]
for name in TANKS:
    Tank.objects.get_or_create(
        facility=facility, name=name,
        defaults={"capacity_liters": Decimal("1200" if name.startswith("FV") else "2000")},
    )

print(f"Tanks: {Tank.objects.count()}")


# Pale Ale recipe
pale_recipe, _ = Recipe.objects.get_or_create(
    name="Pale Ale", version=1,
    defaults={
        "style": "American Pale Ale",
        "target_og": Decimal("1.052"),
        "target_fg": Decimal("1.012"),
        "target_abv": Decimal("5.25"),
        "notes": "House pale ale. Cascade-forward, clean fermentation.",
    },
)

if not pale_recipe.ingredients.exists():
    RecipeIngredient.objects.create(
        recipe=pale_recipe,
        item=Item.objects.get(sku="MALT-2ROW"),
        quantity=Decimal("20"),
        stage="mash",
    )
    RecipeIngredient.objects.create(
        recipe=pale_recipe,
        item=Item.objects.get(sku="MALT-CRYS"),
        quantity=Decimal("2"),
        stage="mash",
    )
    RecipeIngredient.objects.create(
        recipe=pale_recipe,
        item=Item.objects.get(sku="HOPS-CASCADE"),
        quantity=Decimal("0.5"),
        stage="boil",
    )
    RecipeIngredient.objects.create(
        recipe=pale_recipe,
        item=Item.objects.get(sku="YEAST-US05"),
        quantity=Decimal("0.1"),
        stage="ferment",
    )


# West Coast IPA recipe
ipa_recipe, _ = Recipe.objects.get_or_create(
    name="West Coast IPA", version=1,
    defaults={
        "style": "American IPA",
        "target_og": Decimal("1.068"),
        "target_fg": Decimal("1.012"),
        "target_abv": Decimal("7.35"),
        "notes": "Dry, bitter, hop-forward.",
    },
)

if not ipa_recipe.ingredients.exists():
    RecipeIngredient.objects.create(
        recipe=ipa_recipe,
        item=Item.objects.get(sku="MALT-2ROW"),
        quantity=Decimal("25"),
        stage="mash",
    )
    RecipeIngredient.objects.create(
        recipe=ipa_recipe,
        item=Item.objects.get(sku="HOPS-CITRA"),
        quantity=Decimal("0.7"),
        stage="boil",
    )
    RecipeIngredient.objects.create(
        recipe=ipa_recipe,
        item=Item.objects.get(sku="HOPS-MOSAIC"),
        quantity=Decimal("0.5"),
        stage="whirlpool",
    )
    RecipeIngredient.objects.create(
        recipe=ipa_recipe,
        item=Item.objects.get(sku="YEAST-WLP001"),
        quantity=Decimal("1"),
        stage="ferment",
    )


print(f"Recipes: {Recipe.objects.count()}")


# ---------------------------------------------------------------------------
# Sample batches (leave them in various states so the panel has content)
# ---------------------------------------------------------------------------

# Batch 1 — closed, fully processed (in the past)
batch_1, created_1 = Batch.objects.get_or_create(
    batch_number="2026-PALE-040",
    defaults={
        "recipe": pale_recipe,
        "facility": facility,
        "planned_volume_liters": Decimal("500"),
        "status": BatchStatus.PLANNED,
        "brew_date": (now - timedelta(days=20)).date(),
    },
)
if created_1:
    try:
        prod_services.start_brew(batch=batch_1, performed_by=user)
        tank = Tank.objects.get(facility=facility, name="FV-1")
        prod_services.transfer_to_tank(batch=batch_1, tank=tank, performed_by=user)
        prod_services.advance_status(batch=batch_1, to_status=BatchStatus.CONDITIONING, performed_by=user)
        finished = Item.objects.get(sku="KEG-PALE")
        prod_services.package_batch(
            batch=batch_1,
            finished_item=finished,
            packaged_volume_liters=Decimal("490"),
            containers=20,
            lot_number="PALE-KEG-2026-W40-2",
            performed_by=user,
        )
        prod_services.advance_status(batch=batch_1, to_status=BatchStatus.CLOSED, performed_by=user)
        print(f"Batch {batch_1.batch_number}: closed")
    except Exception as e:
        print(f"Batch {batch_1.batch_number}: FAILED — {e}")


# Batch 2 — conditioning (in flight)
batch_2, created_2 = Batch.objects.get_or_create(
    batch_number="2026-IPA-041",
    defaults={
        "recipe": ipa_recipe,
        "facility": facility,
        "planned_volume_liters": Decimal("600"),
        "status": BatchStatus.PLANNED,
        "brew_date": (now - timedelta(days=6)).date(),
    },
)
if created_2:
    try:
        prod_services.start_brew(batch=batch_2, performed_by=user)
        tank = Tank.objects.get(facility=facility, name="FV-2")
        prod_services.transfer_to_tank(batch=batch_2, tank=tank, performed_by=user)
        prod_services.advance_status(batch=batch_2, to_status=BatchStatus.CONDITIONING, performed_by=user)
        print(f"Batch {batch_2.batch_number}: conditioning")
    except Exception as e:
        print(f"Batch {batch_2.batch_number}: FAILED — {e}")


# Batch 3 — planned (not yet started)
batch_3, created_3 = Batch.objects.get_or_create(
    batch_number="2026-PALE-042",
    defaults={
        "recipe": pale_recipe,
        "facility": facility,
        "planned_volume_liters": Decimal("500"),
        "status": BatchStatus.PLANNED,
    },
)
if created_3:
    print(f"Batch {batch_3.batch_number}: planned")


print(f"Batches: {Batch.objects.count()}")


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

print()
print("=" * 60)
print("SEED COMPLETE")
print("=" * 60)
print(f"Facilities:       {Facility.objects.count()}")
print(f"Items:            {Item.objects.count()}")
print(f"Barcodes (item):  {Barcode.objects.filter(target_type='item').count()}")
print(f"Barcodes (lot):   {Barcode.objects.filter(target_type='inventory_lot').count()}")
print(f"Inventory lots:   {InventoryLot.objects.count()}")
print(f"Stock movements:  {StockMovement.objects.count()}")
print(f"Recipes:          {Recipe.objects.count()}")
print(f"Tanks:            {Tank.objects.count()}")
print(f"Batches:          {Batch.objects.count()}")
print(f"Print jobs:       {PrintJob.objects.count()} "
      f"({PrintJob.objects.filter(status='pending').count()} pending)")
print()
print("Sample barcodes to scan:")
for b in Barcode.objects.filter(target_type="inventory_lot").order_by("?")[:5]:
    lot = InventoryLot.objects.get(pk=b.target_id)
    print(f"  {b.token}  →  lot {lot.lot_number} ({lot.item.sku})")
print()
for b in Barcode.objects.filter(target_type="item").order_by("?")[:3]:
    item = Item.objects.get(pk=b.target_id)
    print(f"  {b.token}  →  item {item.sku}")
print()
print("Visit /scan/ and try one of these tokens.")
