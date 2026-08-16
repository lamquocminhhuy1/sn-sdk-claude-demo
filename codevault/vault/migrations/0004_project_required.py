"""Make Item.project required (nulls were filled in 0003)."""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("vault", "0003_assign_default_project"),
    ]

    operations = [
        migrations.AlterField(
            model_name="item",
            name="project",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="items",
                to="vault.project",
            ),
        ),
    ]
