"""Give any pre-existing items a default project before making the FK required."""

from django.db import migrations


def assign_default_project(apps, schema_editor):
    Item = apps.get_model("vault", "Item")
    Project = apps.get_model("vault", "Project")
    owner_ids = (
        Item.objects.filter(project__isnull=True)
        .values_list("owner_id", flat=True)
        .distinct()
    )
    for owner_id in owner_ids:
        project, _ = Project.objects.get_or_create(
            owner_id=owner_id,
            slug="general",
            defaults={"name": "General", "description": "Items created before projects existed."},
        )
        Item.objects.filter(project__isnull=True, owner_id=owner_id).update(
            project=project
        )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("vault", "0002_project_and_dependencies"),
    ]

    operations = [
        migrations.RunPython(assign_default_project, noop),
    ]
