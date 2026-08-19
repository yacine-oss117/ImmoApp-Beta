import uuid

import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0011_user_mfa_db_defaults"),
    ]

    operations = [
        migrations.CreateModel(
            name="ComplianceJob",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("job_id", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                (
                    "job_type",
                    models.CharField(
                        choices=[("export", "Export"), ("delete", "Delete")],
                        max_length=32,
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("queued", "Queued"),
                            ("running", "Running"),
                            ("succeeded", "Succeeded"),
                            ("failed", "Failed"),
                            ("canceled", "Canceled"),
                        ],
                        default="queued",
                        max_length=32,
                    ),
                ),
                ("step_up_verified_at", models.DateTimeField()),
                ("payload_json", models.JSONField(blank=True, default=dict)),
                ("result_json", models.JSONField(blank=True, default=dict)),
                ("error_code", models.CharField(blank=True, max_length=128)),
                ("artifact_path", models.CharField(blank=True, max_length=512)),
                ("artifact_sha256", models.CharField(blank=True, max_length=64)),
                ("artifact_size_bytes", models.BigIntegerField(default=0)),
                ("artifact_content_type", models.CharField(blank=True, max_length=128)),
                (
                    "created_at",
                    models.DateTimeField(default=django.utils.timezone.now, editable=False),
                ),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                ("expires_at", models.DateTimeField(blank=True, null=True)),
                (
                    "agency",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="compliance_jobs",
                        to="accounts.agency",
                    ),
                ),
                (
                    "requested_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="compliance_jobs_requested",
                        to="accounts.user",
                    ),
                ),
                (
                    "target_user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="compliance_jobs_targeted",
                        to="accounts.user",
                    ),
                ),
            ],
            options={
                "indexes": [
                    models.Index(
                        fields=("agency", "job_type", "status", "created_at"),
                        name="acct_comp_job_status_idx",
                    ),
                    models.Index(fields=("expires_at",), name="acct_comp_job_exp_idx"),
                ],
            },
        ),
        migrations.AddConstraint(
            model_name="compliancejob",
            constraint=models.UniqueConstraint(
                condition=models.Q(("status__in", ("queued", "running"))),
                fields=("agency", "target_user", "job_type"),
                name="acct_comp_job_one_active",
            ),
        ),
    ]
