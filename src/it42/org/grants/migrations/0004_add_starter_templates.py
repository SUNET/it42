from django.db import migrations


def seed(apps, schema_editor):
    from it42.org.grants.templates import sync_builtins

    sync_builtins(apps.get_model("org_grants", "FormTemplate"))


class Migration(migrations.Migration):
    dependencies = [("org_grants", "0003_builtin_templates")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
