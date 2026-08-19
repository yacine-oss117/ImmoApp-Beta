from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0004_revoke_manager_hard_delete"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="timezone",
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name="user",
            name="locale",
            field=models.CharField(blank=True, max_length=32),
        ),
    ]
