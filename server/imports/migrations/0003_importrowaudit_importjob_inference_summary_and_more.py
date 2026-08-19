from __future__ import annotations

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("imports", "0002_importjob_review_rows_alter_importjob_stage"),
    ]

    operations = [
        migrations.AddField(
            model_name="importjob",
            name="inference_summary",
            field=models.JSONField(default=dict),
        ),
        migrations.AddField(
            model_name="importjob",
            name="progress_detail",
            field=models.JSONField(default=dict),
        ),
        migrations.AddField(
            model_name="importjob",
            name="ui_entity_hint",
            field=models.CharField(blank=True, max_length=50, null=True),
        ),
        migrations.CreateModel(
            name="ImportRowAudit",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("row_ordinal", models.IntegerField()),
                ("entity_type", models.CharField(max_length=50)),
                (
                    "action",
                    models.CharField(
                        choices=[
                            ("create", "Create"),
                            ("update", "Update"),
                            ("review", "Review"),
                            ("skip", "Skip"),
                        ],
                        max_length=20,
                    ),
                ),
                ("target_table", models.CharField(blank=True, default="", max_length=100)),
                ("target_id", models.IntegerField(default=0)),
                ("target_row_version", models.IntegerField(default=0)),
                ("before_payload", models.JSONField(default=dict)),
                ("after_payload", models.JSONField(default=dict)),
                ("diff_payload", models.JSONField(default=dict)),
                ("reasons", models.JSONField(default=list)),
                ("correction_payload", models.JSONField(default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "actor",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="import_row_audits",
                        to="accounts.user",
                    ),
                ),
                (
                    "agency",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="import_row_audits",
                        to="accounts.agency",
                    ),
                ),
                (
                    "job",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="row_audits",
                        to="imports.importjob",
                    ),
                ),
            ],
            options={"ordering": ["id"]},
        ),
        migrations.AddIndex(
            model_name="importrowaudit",
            index=models.Index(fields=["job", "row_ordinal"], name="idx_imp_audit_job_row"),
        ),
        migrations.AddIndex(
            model_name="importrowaudit",
            index=models.Index(
                fields=["agency", "created_at"], name="idx_imp_audit_agency_created"
            ),
        ),
    ]
