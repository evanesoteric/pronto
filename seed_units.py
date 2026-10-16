from apps.inventory.models import UnitOfMeasure

UNITS = [
    ("kg", "Kilogram", "mass", True),
    ("g", "Gram", "mass", False),
    ("L", "Liter", "volume", True),
    ("mL", "Milliliter", "volume", False),
    ("each", "Each", "count", True),
    ("keg", "Keg", "count", False),
    ("case", "Case", "count", False),
    ("pallet", "Pallet", "count", False),
    ("bottle", "Bottle", "count", False),
    ("can", "Can", "count", False),
]

for code, name, dimension, is_base in UNITS:
    uom, created = UnitOfMeasure.objects.get_or_create(
        code=code,
        defaults={"name": name, "dimension": dimension, "is_base": is_base},
    )
    print(f"{'CREATED' if created else 'exists '}: {uom}")
