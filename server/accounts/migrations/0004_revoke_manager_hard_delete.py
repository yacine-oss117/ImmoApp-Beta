from django.db import migrations


def revoke_manager_hard_delete(apps, schema_editor) -> None:
    User = apps.get_model("accounts", "User")
    User.objects.filter(
        is_superuser=False,
        role="manager",
        can_hard_delete=True,
    ).update(can_hard_delete=False)


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0003_update_agency_free_tier_limits"),
    ]

    operations = [
        migrations.RunPython(revoke_manager_hard_delete, reverse_code=migrations.RunPython.noop),
    ]
