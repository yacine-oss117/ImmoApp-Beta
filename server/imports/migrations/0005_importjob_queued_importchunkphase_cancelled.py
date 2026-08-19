from __future__ import annotations

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("imports", "0004_importchunk_importartifactmanifest_importchunkphase"),
    ]

    operations = [
        migrations.AlterField(
            model_name="importjob",
            name="status",
            field=models.CharField(
                choices=[
                    ("pending", "Pending"),
                    ("parsing", "Parsing"),
                    ("ready", "Ready"),
                    ("queued", "Queued"),
                    ("running", "Running"),
                    ("completed", "Completed"),
                    ("failed", "Failed"),
                ],
                default="pending",
                max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name="importchunkphase",
            name="status",
            field=models.CharField(
                choices=[
                    ("blocked", "Blocked"),
                    ("pending", "Pending"),
                    ("queued", "Queued"),
                    ("running", "Running"),
                    ("cancelled", "Cancelled"),
                    ("completed", "Completed"),
                    ("failed", "Failed"),
                ],
                default="pending",
                max_length=20,
            ),
        ),
    ]
