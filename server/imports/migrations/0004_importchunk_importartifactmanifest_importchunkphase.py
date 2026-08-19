from __future__ import annotations

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("imports", "0003_importrowaudit_importjob_inference_summary_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="ImportChunk",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                (
                    "ordinal",
                    models.IntegerField(),
                ),
                (
                    "chunk_role",
                    models.CharField(
                        choices=[("single", "Single"), ("root", "Root"), ("child", "Child")],
                        default="single",
                        max_length=20,
                    ),
                ),
                ("entity_type", models.CharField(blank=True, default="", max_length=50)),
                ("row_start", models.IntegerField(default=0)),
                ("row_end", models.IntegerField(default=0)),
                ("row_count", models.IntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "agency",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="import_chunks",
                        to="accounts.agency",
                    ),
                ),
                (
                    "job",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="chunks",
                        to="imports.importjob",
                    ),
                ),
            ],
            options={"ordering": ["job_id", "ordinal", "id"]},
        ),
        migrations.CreateModel(
            name="ImportArtifactManifest",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                (
                    "phase",
                    models.CharField(
                        choices=[
                            ("prepare", "Prepare"),
                            ("plan", "Plan"),
                            ("load", "Load"),
                            ("finalize", "Finalize"),
                        ],
                        max_length=20,
                    ),
                ),
                ("artifact_kind", models.CharField(max_length=50)),
                ("storage_id", models.CharField(max_length=255)),
                ("checksum", models.CharField(blank=True, default="", max_length=64)),
                ("row_count", models.IntegerField(default=0)),
                ("metadata", models.JSONField(default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "agency",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="import_artifact_manifests",
                        to="accounts.agency",
                    ),
                ),
                (
                    "chunk",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="artifact_manifests",
                        to="imports.importchunk",
                    ),
                ),
                (
                    "job",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="artifact_manifests",
                        to="imports.importjob",
                    ),
                ),
            ],
            options={"ordering": ["job_id", "chunk_id", "id"]},
        ),
        migrations.CreateModel(
            name="ImportChunkPhase",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                (
                    "phase",
                    models.CharField(
                        choices=[("plan", "Plan"), ("load", "Load")],
                        max_length=20,
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("blocked", "Blocked"),
                            ("pending", "Pending"),
                            ("queued", "Queued"),
                            ("running", "Running"),
                            ("completed", "Completed"),
                            ("failed", "Failed"),
                        ],
                        default="pending",
                        max_length=20,
                    ),
                ),
                ("attempt_count", models.IntegerField(default=0)),
                ("task_id", models.CharField(blank=True, default="", max_length=255)),
                ("lease_token", models.CharField(blank=True, default="", max_length=64)),
                ("lease_expires_at", models.DateTimeField(blank=True, null=True)),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                ("error_payload", models.JSONField(default=dict)),
                ("metrics_payload", models.JSONField(default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "chunk",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="phases",
                        to="imports.importchunk",
                    ),
                ),
            ],
            options={"ordering": ["chunk_id", "id"]},
        ),
        migrations.AddConstraint(
            model_name="importchunk",
            constraint=models.UniqueConstraint(
                fields=("job", "ordinal", "chunk_role"),
                name="uq_import_chunk_job_ord_role",
            ),
        ),
        migrations.AddConstraint(
            model_name="importchunkphase",
            constraint=models.UniqueConstraint(
                fields=("chunk", "phase"),
                name="uq_import_chunk_phase",
            ),
        ),
        migrations.AddIndex(
            model_name="importchunk",
            index=models.Index(fields=["job", "chunk_role"], name="idx_imp_chunk_job_role"),
        ),
        migrations.AddIndex(
            model_name="importchunk",
            index=models.Index(
                fields=["agency", "created_at"], name="idx_imp_chunk_agency_created"
            ),
        ),
        migrations.AddIndex(
            model_name="importartifactmanifest",
            index=models.Index(fields=["job", "phase"], name="idx_imp_art_job_phase"),
        ),
        migrations.AddIndex(
            model_name="importartifactmanifest",
            index=models.Index(fields=["chunk", "artifact_kind"], name="idx_imp_art_chunk_kind"),
        ),
        migrations.AddIndex(
            model_name="importartifactmanifest",
            index=models.Index(fields=["agency", "created_at"], name="idx_imp_art_agency_created"),
        ),
        migrations.AddIndex(
            model_name="importchunkphase",
            index=models.Index(fields=["status", "phase"], name="idx_imp_chunk_phase_status"),
        ),
        migrations.AddIndex(
            model_name="importchunkphase",
            index=models.Index(fields=["chunk", "status"], name="idx_imp_cphase_chunk_stat"),
        ),
    ]
