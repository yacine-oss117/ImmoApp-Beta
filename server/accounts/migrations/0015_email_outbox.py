from __future__ import annotations

import uuid

import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0014_encrypt_account_pii"),
    ]

    operations = [
        migrations.CreateModel(
            name="EmailOutbox",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("to_email", models.EmailField(max_length=254)),
                ("subject", models.CharField(max_length=500)),
                ("body_text", models.TextField()),
                ("body_html", models.TextField(blank=True)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("sent", "Sent"),
                            ("failed_permanent", "Failed Permanent"),
                        ],
                        default="pending",
                        max_length=32,
                    ),
                ),
                ("attempts", models.PositiveIntegerField(default=0)),
                (
                    "created_at",
                    models.DateTimeField(default=django.utils.timezone.now, editable=False),
                ),
                ("last_attempt_at", models.DateTimeField(blank=True, null=True)),
                ("sent_at", models.DateTimeField(blank=True, null=True)),
                ("error_message", models.TextField(blank=True)),
            ],
            options={
                "indexes": [
                    models.Index(fields=["status", "created_at"], name="email_outbox_status_idx")
                ],
            },
        ),
    ]
