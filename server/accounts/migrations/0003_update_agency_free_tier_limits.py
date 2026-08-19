from django.db import migrations


def update_free_tier_limits(apps, schema_editor):
    Agency = apps.get_model("accounts", "Agency")
    Agency.objects.filter(
        max_users=2,
        max_managers=1,
        max_agents_per_manager=1,
    ).update(max_users=3, max_agents_per_manager=2)


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0002_alter_agency_max_agents_per_manager_and_more"),
    ]

    operations = [
        migrations.RunPython(update_free_tier_limits, migrations.RunPython.noop),
    ]
