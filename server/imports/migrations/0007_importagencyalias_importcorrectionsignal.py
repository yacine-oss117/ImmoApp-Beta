from __future__ import annotations

import django.db.models.deletion
from django.db import migrations, models

_CREATE_IMPORT_ALIAS_TABLE = """
CREATE TABLE IF NOT EXISTS imports_importagencyalias (
    id BIGSERIAL PRIMARY KEY,
    agency_id BIGINT NOT NULL REFERENCES accounts_agency(id) ON DELETE CASCADE,
    domain VARCHAR(32) NOT NULL,
    source_value_original TEXT NOT NULL DEFAULT '',
    source_value_normalized VARCHAR(255) NOT NULL,
    canonical_key VARCHAR(255) NOT NULL DEFAULT '',
    canonical_label VARCHAR(255) NOT NULL DEFAULT '',
    state VARCHAR(20) NOT NULL DEFAULT 'shadow',
    confirm_count INTEGER NOT NULL DEFAULT 0,
    reject_count INTEGER NOT NULL DEFAULT 0,
    distinct_job_count INTEGER NOT NULL DEFAULT 0,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    promoted_at TIMESTAMPTZ NULL,
    last_job_id UUID NULL REFERENCES imports_importjob(id) ON DELETE SET NULL,
    last_actor_id BIGINT NULL REFERENCES accounts_user(id) ON DELETE SET NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT uq_import_agency_alias_source
        UNIQUE (agency_id, domain, source_value_normalized)
);
"""

_CREATE_IMPORT_CORRECTION_SIGNAL_TABLE = """
CREATE TABLE IF NOT EXISTS imports_importcorrectionsignal (
    id BIGSERIAL PRIMARY KEY,
    agency_id BIGINT NOT NULL REFERENCES accounts_agency(id) ON DELETE CASCADE,
    job_id UUID NOT NULL REFERENCES imports_importjob(id) ON DELETE CASCADE,
    actor_id BIGINT NULL REFERENCES accounts_user(id) ON DELETE SET NULL,
    row_ordinal INTEGER NOT NULL,
    entity_type VARCHAR(50) NOT NULL,
    field_name VARCHAR(100) NOT NULL,
    domain VARCHAR(32) NOT NULL,
    source_value_original TEXT NOT NULL DEFAULT '',
    source_value_normalized VARCHAR(255) NOT NULL DEFAULT '',
    corrected_value_original TEXT NOT NULL DEFAULT '',
    corrected_value_normalized VARCHAR(255) NOT NULL DEFAULT '',
    canonical_key VARCHAR(255) NOT NULL DEFAULT '',
    canonical_label VARCHAR(255) NOT NULL DEFAULT '',
    decision_action VARCHAR(32) NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

_CREATE_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_imp_alias_ag_dom_state
ON imports_importagencyalias(agency_id, domain, state);
CREATE INDEX IF NOT EXISTS idx_imp_alias_ag_source
ON imports_importagencyalias(agency_id, source_value_normalized);
CREATE INDEX IF NOT EXISTS idx_imp_corrsig_ag_dom_src
ON imports_importcorrectionsignal(agency_id, domain, source_value_normalized);
CREATE INDEX IF NOT EXISTS idx_imp_corrsig_ag_field_ct
ON imports_importcorrectionsignal(agency_id, field_name, created_at);
CREATE INDEX IF NOT EXISTS idx_imp_corrsig_job_row
ON imports_importcorrectionsignal(job_id, row_ordinal);
"""

_DROP_INDEXES_AND_TABLES = """
DROP INDEX IF EXISTS idx_imp_corrsig_job_row;
DROP INDEX IF EXISTS idx_imp_corrsig_ag_field_ct;
DROP INDEX IF EXISTS idx_imp_corrsig_ag_dom_src;
DROP INDEX IF EXISTS idx_imp_alias_ag_source;
DROP INDEX IF EXISTS idx_imp_alias_ag_dom_state;
DROP TABLE IF EXISTS imports_importcorrectionsignal;
DROP TABLE IF EXISTS imports_importagencyalias;
"""


class Migration(migrations.Migration):

    dependencies = [
        ("imports", "0006_importworkflowstate_importchunkphase_heartbeat_at"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(
                    sql=_CREATE_IMPORT_ALIAS_TABLE,
                    reverse_sql=migrations.RunSQL.noop,
                ),
                migrations.RunSQL(
                    sql=_CREATE_IMPORT_CORRECTION_SIGNAL_TABLE,
                    reverse_sql=migrations.RunSQL.noop,
                ),
                migrations.RunSQL(
                    sql=_CREATE_INDEXES,
                    reverse_sql=_DROP_INDEXES_AND_TABLES,
                ),
            ],
            state_operations=[
                migrations.CreateModel(
                    name="ImportAgencyAlias",
                    fields=[
                        ("id", models.BigAutoField(primary_key=True, serialize=False)),
                        (
                            "domain",
                            models.CharField(
                                choices=[
                                    ("location", "Location"),
                                    ("property_type", "Property Type"),
                                    ("action", "Action"),
                                    ("header", "Header"),
                                ],
                                max_length=32,
                            ),
                        ),
                        ("source_value_original", models.TextField(blank=True, default="")),
                        ("source_value_normalized", models.CharField(max_length=255)),
                        ("canonical_key", models.CharField(blank=True, default="", max_length=255)),
                        (
                            "canonical_label",
                            models.CharField(blank=True, default="", max_length=255),
                        ),
                        (
                            "state",
                            models.CharField(
                                choices=[
                                    ("shadow", "Shadow"),
                                    ("trusted", "Trusted"),
                                    ("rejected", "Rejected"),
                                ],
                                default="shadow",
                                max_length=20,
                            ),
                        ),
                        ("confirm_count", models.IntegerField(default=0)),
                        ("reject_count", models.IntegerField(default=0)),
                        ("distinct_job_count", models.IntegerField(default=0)),
                        ("first_seen_at", models.DateTimeField(auto_now_add=True)),
                        ("last_seen_at", models.DateTimeField(auto_now=True)),
                        ("promoted_at", models.DateTimeField(blank=True, null=True)),
                        ("metadata", models.JSONField(default=dict)),
                        (
                            "agency",
                            models.ForeignKey(
                                on_delete=django.db.models.deletion.CASCADE,
                                related_name="import_agency_aliases",
                                to="accounts.agency",
                            ),
                        ),
                        (
                            "last_actor",
                            models.ForeignKey(
                                blank=True,
                                null=True,
                                on_delete=django.db.models.deletion.SET_NULL,
                                related_name="agency_alias_updates",
                                to="accounts.user",
                            ),
                        ),
                        (
                            "last_job",
                            models.ForeignKey(
                                blank=True,
                                null=True,
                                on_delete=django.db.models.deletion.SET_NULL,
                                related_name="agency_alias_updates",
                                to="imports.importjob",
                            ),
                        ),
                    ],
                    options={
                        "ordering": ["agency_id", "domain", "source_value_normalized"],
                    },
                ),
                migrations.CreateModel(
                    name="ImportCorrectionSignal",
                    fields=[
                        ("id", models.BigAutoField(primary_key=True, serialize=False)),
                        ("row_ordinal", models.IntegerField()),
                        ("entity_type", models.CharField(max_length=50)),
                        ("field_name", models.CharField(max_length=100)),
                        ("domain", models.CharField(max_length=32)),
                        ("source_value_original", models.TextField(blank=True, default="")),
                        (
                            "source_value_normalized",
                            models.CharField(blank=True, default="", max_length=255),
                        ),
                        ("corrected_value_original", models.TextField(blank=True, default="")),
                        (
                            "corrected_value_normalized",
                            models.CharField(blank=True, default="", max_length=255),
                        ),
                        ("canonical_key", models.CharField(blank=True, default="", max_length=255)),
                        (
                            "canonical_label",
                            models.CharField(blank=True, default="", max_length=255),
                        ),
                        (
                            "decision_action",
                            models.CharField(blank=True, default="", max_length=32),
                        ),
                        ("created_at", models.DateTimeField(auto_now_add=True)),
                        (
                            "actor",
                            models.ForeignKey(
                                blank=True,
                                null=True,
                                on_delete=django.db.models.deletion.SET_NULL,
                                related_name="import_correction_signals",
                                to="accounts.user",
                            ),
                        ),
                        (
                            "agency",
                            models.ForeignKey(
                                on_delete=django.db.models.deletion.CASCADE,
                                related_name="import_correction_signals",
                                to="accounts.agency",
                            ),
                        ),
                        (
                            "job",
                            models.ForeignKey(
                                on_delete=django.db.models.deletion.CASCADE,
                                related_name="correction_signals",
                                to="imports.importjob",
                            ),
                        ),
                    ],
                    options={"ordering": ["id"]},
                ),
                migrations.AddConstraint(
                    model_name="importagencyalias",
                    constraint=models.UniqueConstraint(
                        fields=("agency", "domain", "source_value_normalized"),
                        name="uq_import_agency_alias_source",
                    ),
                ),
                migrations.AddIndex(
                    model_name="importagencyalias",
                    index=models.Index(
                        fields=["agency", "domain", "state"],
                        name="idx_imp_alias_ag_dom_state",
                    ),
                ),
                migrations.AddIndex(
                    model_name="importagencyalias",
                    index=models.Index(
                        fields=["agency", "source_value_normalized"],
                        name="idx_imp_alias_ag_source",
                    ),
                ),
                migrations.AddIndex(
                    model_name="importcorrectionsignal",
                    index=models.Index(
                        fields=["agency", "domain", "source_value_normalized"],
                        name="idx_imp_corrsig_ag_dom_src",
                    ),
                ),
                migrations.AddIndex(
                    model_name="importcorrectionsignal",
                    index=models.Index(
                        fields=["agency", "field_name", "created_at"],
                        name="idx_imp_corrsig_ag_field_ct",
                    ),
                ),
                migrations.AddIndex(
                    model_name="importcorrectionsignal",
                    index=models.Index(
                        fields=["job", "row_ordinal"],
                        name="idx_imp_corrsig_job_row",
                    ),
                ),
            ],
        ),
    ]
