from __future__ import annotations

import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("accounts", "0006_add_import_permission"),
    ]

    operations = [
        migrations.CreateModel(
            name="ImportJob",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        primary_key=True, default=uuid.uuid4, editable=False, serialize=False
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("parsing", "Parsing"),
                            ("ready", "Ready"),
                            ("running", "Running"),
                            ("completed", "Completed"),
                            ("failed", "Failed"),
                        ],
                        default="pending",
                        max_length=20,
                    ),
                ),
                (
                    "stage",
                    models.CharField(
                        choices=[
                            ("upload", "Upload"),
                            ("mapping", "Mapping"),
                            ("execution", "Execution"),
                        ],
                        default="upload",
                        max_length=20,
                    ),
                ),
                ("progress", models.IntegerField(default=0)),
                ("filename", models.CharField(max_length=255)),
                ("file_type", models.CharField(max_length=10)),
                ("source_path", models.CharField(blank=True, max_length=1024, null=True)),
                ("detected_entity", models.CharField(blank=True, max_length=50, null=True)),
                ("detected_columns", models.JSONField(default=list)),
                ("column_mapping", models.JSONField(default=dict)),
                ("preview_rows", models.JSONField(default=list)),
                ("result_summary", models.JSONField(default=dict)),
                ("error_message", models.TextField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("task_id", models.CharField(blank=True, max_length=255, null=True)),
                (
                    "agency",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="import_jobs",
                        to="accounts.agency",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="import_jobs",
                        to="accounts.user",
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="importjob",
            index=models.Index(fields=["user", "status"], name="idx_import_jobs_user_status"),
        ),
        migrations.AddIndex(
            model_name="importjob",
            index=models.Index(
                fields=["agency", "created_at"], name="idx_import_jobs_agency_created"
            ),
        ),
    ]
