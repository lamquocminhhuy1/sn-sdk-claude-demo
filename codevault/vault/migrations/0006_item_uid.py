"""Add a UUID to every item: nullable first, fill, then enforce unique."""

import uuid

from django.db import migrations, models


def fill_uids(apps, schema_editor):
    Item = apps.get_model("vault", "Item")
    for item in Item.objects.filter(uid__isnull=True):
        item.uid = uuid.uuid4()
        item.save(update_fields=["uid"])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("vault", "0005_identifier_is_manual"),
    ]

    operations = [
        migrations.AddField(
            model_name="item",
            name="uid",
            field=models.UUIDField(editable=False, null=True),
        ),
        migrations.RunPython(fill_uids, noop),
        migrations.AlterField(
            model_name="item",
            name="uid",
            field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
        ),
    ]
