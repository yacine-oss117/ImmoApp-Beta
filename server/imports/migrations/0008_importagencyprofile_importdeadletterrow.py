from __future__ import annotations

import django.db.models.deletion
from django.db import migrations, models

_CREATE_IMPORT_AGENCY_PROFILE_TABLE = """
CREATE TABLE IF NOT EXISTS imports_importagencyprofile (
    agency_id BIGINT PRIMARY KEY REFERENCES accounts_agency(id) ON DELETE CASCADE,
    memory_version VARCHAR(64) NOT NULL DEFAULT '',
    preferred_language VARCHAR(16) NOT NULL DEFAULT '',
    default_wilaya_code VARCHAR(8) NOT NULL DEFAULT '',
    common_bundle_shape VARCHAR(64) NOT NULL DEFAULT '',
    property_vocab JSONB NOT NULL DEFAULT '{}'::jsonb,
    location_abbreviations JSONB NOT NULL DEFAULT '{}'::jsonb,
    action_vocab JSONB NOT NULL DEFAULT '{}'::jsonb,
    header_vocab JSONB NOT NULL DEFAULT '{}'::jsonb,
    common_missing_fields JSONB NOT NULL DEFAULT '[]'::jsonb,
    last_imported_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

_CREATE_IMPORT_DEAD_LETTER_TABLE = """
CREATE TABLE IF NOT EXISTS imports_importdeadletterrow (
    id BIGSERIAL PRIMARY KEY,
    job_id UUID NOT NULL REFERENCES imports_importjob(id) ON DELETE CASCADE,
    agency_id BIGINT NOT NULL REFERENCES accounts_agency(id) ON DELETE CASCADE,
    actor_id BIGINT NULL REFERENCES accounts_user(id) ON DELETE SET NULL,
    row_ordinal INTEGER NOT NULL,
    entity_type VARCHAR(50) NOT NULL DEFAULT '',
    topology_side VARCHAR(32) NOT NULL DEFAULT '',
    disposition VARCHAR(32) NOT NULL,
    phase VARCHAR(32) NOT NULL DEFAULT '',
    reason_codes JSONB NOT NULL DEFAULT '[]'::jsonb,
    reason_messages JSONB NOT NULL DEFAULT '[]'::jsonb,
    raw_data JSONB NOT NULL DEFAULT '{}'::jsonb,
    normalized_data JSONB NOT NULL DEFAULT '{}'::jsonb,
    recoverability_class VARCHAR(32) NOT NULL DEFAULT '',
    recovered_fields JSONB NOT NULL DEFAULT '[]'::jsonb,
    recovery_candidates JSONB NOT NULL DEFAULT '[]'::jsonb,
    blocking_reasons JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

_CREATE_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_imp_dead_ag_created
ON imports_importdeadletterrow(agency_id, created_at);
CREATE INDEX IF NOT EXISTS idx_imp_dead_job_row
ON imports_importdeadletterrow(job_id, row_ordinal);
CREATE INDEX IF NOT EXISTS idx_imp_dead_ag_disp_ct
ON imports_importdeadletterrow(agency_id, disposition, created_at);
"""

_DROP_INDEXES_AND_TABLES = """
DROP INDEX IF EXISTS idx_imp_dead_ag_disp_ct;
DROP INDEX IF EXISTS idx_imp_dead_job_row;
DROP INDEX IF EXISTS idx_imp_dead_ag_created;
DROP TABLE IF EXISTS imports_importdeadletterrow;
DROP TABLE IF EXISTS imports_importagencyprofile;
"""


class Migration(migrations.Migration):

    dependencies = [
        ("imports", "0007_importagencyalias_importcorrectionsignal"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(
                    sql=_CREATE_IMPORT_AGENCY_PROFILE_TABLE,
                    reverse_sql=migrations.RunSQL.noop,
                ),
                migrations.RunSQL(
                    sql=_CREATE_IMPORT_DEAD_LETTER_TABLE,
                    reverse_sql=migrations.RunSQL.noop,
                ),
                migrations.RunSQL(
                    sql=_CREATE_INDEXES,
                    reverse_sql=_DROP_INDEXES_AND_TABLES,
                ),
            ],
            state_operations=[
                migrations.CreateModel(
                    name="ImportAgencyProfile",
                    fields=[
                        (
                            "agency",
                            models.OneToOneField(
                                on_delete=django.db.models.deletion.CASCADE,
                                primary_key=True,
                                related_name="import_agency_profile",
                                serialize=False,
                                to="accounts.agency",
                            ),
                        ),
                        ("memory_version", models.CharField(blank=True, default="", max_length=64)),
                        (
                            "preferred_language",
                            models.CharField(blank=True, default="", max_length=16),
                        ),
                        (
                            "default_wilaya_code",
                            models.CharField(blank=True, default="", max_length=8),
                        ),
                        (
                            "common_bundle_shape",
                            models.CharField(blank=True, default="", max_length=64),
                        ),
                        ("property_vocab", models.JSONField(default=dict)),
                        ("location_abbreviations", models.JSONField(default=dict)),
                        ("action_vocab", models.JSONField(default=dict)),
                        ("header_vocab", models.JSONField(default=dict)),
                        ("common_missing_fields", models.JSONField(default=list)),
                        ("last_imported_at", models.DateTimeField(blank=True, null=True)),
                        ("created_at", models.DateTimeField(auto_now_add=True)),
                        ("updated_at", models.DateTimeField(auto_now=True)),
                    ],
                    options={
                        "ordering": ["agency_id"],
                    },
                ),
                migrations.CreateModel(
                    name="ImportDeadLetterRow",
                    fields=[
                        ("id", models.BigAutoField(primary_key=True, serialize=False)),
                        ("row_ordinal", models.IntegerField()),
                        ("entity_type", models.CharField(blank=True, default="", max_length=50)),
                        ("topology_side", models.CharField(blank=True, default="", max_length=32)),
                        (
                            "disposition",
                            models.CharField(
                                choices=[
                                    ("auto_skipped", "Auto Skipped"),
                                    ("human_skipped", "Human Skipped"),
                                    ("blocking_discarded", "Blocking Discarded"),
                                ],
                                max_length=32,
                            ),
                        ),
                        ("phase", models.CharField(blank=True, default="", max_length=32)),
                        ("reason_codes", models.JSONField(default=list)),
                        ("reason_messages", models.JSONField(default=list)),
                        ("raw_data", models.JSONField(default=dict)),
                        ("normalized_data", models.JSONField(default=dict)),
                        (
                            "recoverability_class",
                            models.CharField(blank=True, default="", max_length=32),
                        ),
                        ("recovered_fields", models.JSONField(default=list)),
                        ("recovery_candidates", models.JSONField(default=list)),
                        ("blocking_reasons", models.JSONField(default=list)),
                        ("created_at", models.DateTimeField(auto_now_add=True)),
                        (
                            "actor",
                            models.ForeignKey(
                                blank=True,
                                null=True,
                                on_delete=django.db.models.deletion.SET_NULL,
                                related_name="import_dead_letter_rows",
                                to="accounts.user",
                            ),
                        ),
                        (
                            "agency",
                            models.ForeignKey(
                                on_delete=django.db.models.deletion.CASCADE,
                                related_name="import_dead_letter_rows",
                                to="accounts.agency",
                            ),
                        ),
                        (
                            "job",
                            models.ForeignKey(
                                on_delete=django.db.models.deletion.CASCADE,
                                related_name="dead_letter_rows",
                                to="imports.importjob",
                            ),
                        ),
                    ],
                    options={
                        "ordering": ["id"],
                    },
                ),
                migrations.AddIndex(
                    model_name="importdeadletterrow",
                    index=models.Index(
                        fields=["agency", "created_at"],
                        name="idx_imp_dead_ag_created",
                    ),
                ),
                migrations.AddIndex(
                    model_name="importdeadletterrow",
                    index=models.Index(
                        fields=["job", "row_ordinal"],
                        name="idx_imp_dead_job_row",
                    ),
                ),
                migrations.AddIndex(
                    model_name="importdeadletterrow",
                    index=models.Index(
                        fields=["agency", "disposition", "created_at"],
                        name="idx_imp_dead_ag_disp_ct",
                    ),
                ),
            ],
        ),
    ]
