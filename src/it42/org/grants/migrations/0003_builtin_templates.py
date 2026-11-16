from django.db import migrations

from it42.org.grants.templates import sync_builtins


def seed(apps, schema_editor):  # noqa: ANN001, ANN201
    sync_builtins(apps.get_model("org_grants", "FormTemplate"))


class Migration(migrations.Migration):
    dependencies = [("org_grants", "0002_form_templates_folders")]

    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
