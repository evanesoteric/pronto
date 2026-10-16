from django.db import migrations, models


def reclassify_packaging_units(apps, schema_editor):
    UnitOfMeasure = apps.get_model("inventory", "UnitOfMeasure")
    UnitOfMeasure.objects.filter(
        code__in=["keg", "case", "pallet", "bottle", "can"],
    ).update(dimension="packaging")


class Migration(migrations.Migration):
    dependencies = [
        ("inventory", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="unitofmeasure",
            name="dimension",
            field=models.CharField(
                choices=[
                    ("mass", "Mass"),
                    ("volume", "Volume"),
                    ("count", "Count"),
                    ("packaging", "Packaging"),
                ],
                max_length=16,
            ),
        ),
        migrations.RunPython(reclassify_packaging_units, migrations.RunPython.noop),
    ]
