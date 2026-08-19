from __future__ import annotations

import django.db.models.deletion
from django.db import migrations, models

_CREATE_IMPORT_WORKFLOW_STATE_TABLE = """
CREATE TABLE IF NOT EXISTS imports_importworkflowstate (
    id BIGSERIAL PRIMARY KEY,
    job_id UUID NOT NULL UNIQUE REFERENCES imports_importjob(id) ON DELETE CASCADE,
    run_id VARCHAR(64) NOT NULL DEFAULT '',
    status VARCHAR(20) NOT NULL DEFAULT '',
    fingerprint VARCHAR(128) NOT NULL DEFAULT '',
    cancel_requested BOOLEAN NOT NULL DEFAULT FALSE,
    prepare_completed BOOLEAN NOT NULL DEFAULT FALSE,
    finalize_queued BOOLEAN NOT NULL DEFAULT FALSE,
    finalized BOOLEAN NOT NULL DEFAULT FALSE,
    queue_position INTEGER NOT NULL DEFAULT 0,
    queued_at TIMESTAMPTZ NULL,
    execution_profile VARCHAR(20) NOT NULL DEFAULT '',
    admission_mode VARCHAR(20) NOT NULL DEFAULT '',
    pressure_reason VARCHAR(64) NOT NULL DEFAULT '',
    bundle_mode VARCHAR(32) NOT NULL DEFAULT '',
    topology_side VARCHAR(32) NOT NULL DEFAULT '',
    params JSONB NOT NULL DEFAULT '{}'::jsonb,
    prepare_counts JSONB NOT NULL DEFAULT '{}'::jsonb,
    load_counts JSONB NOT NULL DEFAULT '{}'::jsonb,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    root_plan_index_ready BOOLEAN NOT NULL DEFAULT FALSE,
    root_plan_index_manifest_id BIGINT NOT NULL DEFAULT 0,
    root_plan_index_checksum VARCHAR(64) NOT NULL DEFAULT '',
    root_plan_index_key_count INTEGER NOT NULL DEFAULT 0,
    root_load_anchor_map_ready BOOLEAN NOT NULL DEFAULT FALSE,
    root_load_anchor_map_manifest_id BIGINT NOT NULL DEFAULT 0,
    root_load_anchor_map_checksum VARCHAR(64) NOT NULL DEFAULT '',
    root_load_anchor_map_key_count INTEGER NOT NULL DEFAULT 0,
    started_at TIMESTAMPTZ NULL,
    finished_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

_CREATE_INDEXES_AND_HEARTBEAT = """
CREATE INDEX IF NOT EXISTS idx_imp_wf_status_queue
ON imports_importworkflowstate(status, queued_at);
CREATE INDEX IF NOT EXISTS idx_imp_wf_exec_profile
ON imports_importworkflowstate(execution_profile);
ALTER TABLE imports_importchunkphase
ADD COLUMN IF NOT EXISTS heartbeat_at TIMESTAMPTZ NULL;
"""

_DROP_INDEXES_AND_TABLE = """
ALTER TABLE imports_importchunkphase
DROP COLUMN IF EXISTS heartbeat_at;
DROP INDEX IF EXISTS idx_imp_wf_exec_profile;
DROP INDEX IF EXISTS idx_imp_wf_status_queue;
DROP TABLE IF EXISTS imports_importworkflowstate;
"""


class Migration(migrations.Migration):

    dependencies = [
        ("imports", "0005_importjob_queued_importchunkphase_cancelled"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(
                    sql=_CREATE_IMPORT_WORKFLOW_STATE_TABLE,
                    reverse_sql=migrations.RunSQL.noop,
                ),
                migrations.RunSQL(
                    sql=_CREATE_INDEXES_AND_HEARTBEAT,
                    reverse_sql=_DROP_INDEXES_AND_TABLE,
                ),
            ],
            state_operations=[
                migrations.CreateModel(
                    name="ImportWorkflowState",
                    fields=[
                        (
                            "id",
                            models.BigAutoField(
                                auto_created=True,
                                primary_key=True,
                                serialize=False,
                                verbose_name="ID",
                            ),
                        ),
                        ("run_id", models.CharField(blank=True, default="", max_length=64)),
                        ("status", models.CharField(blank=True, default="", max_length=20)),
                        ("fingerprint", models.CharField(blank=True, default="", max_length=128)),
                        ("cancel_requested", models.BooleanField(default=False)),
                        ("prepare_completed", models.BooleanField(default=False)),
                        ("finalize_queued", models.BooleanField(default=False)),
                        ("finalized", models.BooleanField(default=False)),
                        ("queue_position", models.IntegerField(default=0)),
                        ("queued_at", models.DateTimeField(blank=True, null=True)),
                        (
                            "execution_profile",
                            models.CharField(blank=True, default="", max_length=20),
                        ),
                        ("admission_mode", models.CharField(blank=True, default="", max_length=20)),
                        (
                            "pressure_reason",
                            models.CharField(blank=True, default="", max_length=64),
                        ),
                        ("bundle_mode", models.CharField(blank=True, default="", max_length=32)),
                        ("topology_side", models.CharField(blank=True, default="", max_length=32)),
                        ("params", models.JSONField(default=dict)),
                        ("prepare_counts", models.JSONField(default=dict)),
                        ("load_counts", models.JSONField(default=dict)),
                        ("metadata", models.JSONField(default=dict)),
                        ("root_plan_index_ready", models.BooleanField(default=False)),
                        ("root_plan_index_manifest_id", models.BigIntegerField(default=0)),
                        (
                            "root_plan_index_checksum",
                            models.CharField(blank=True, default="", max_length=64),
                        ),
                        ("root_plan_index_key_count", models.IntegerField(default=0)),
                        ("root_load_anchor_map_ready", models.BooleanField(default=False)),
                        ("root_load_anchor_map_manifest_id", models.BigIntegerField(default=0)),
                        (
                            "root_load_anchor_map_checksum",
                            models.CharField(blank=True, default="", max_length=64),
                        ),
                        ("root_load_anchor_map_key_count", models.IntegerField(default=0)),
                        ("started_at", models.DateTimeField(blank=True, null=True)),
                        ("finished_at", models.DateTimeField(blank=True, null=True)),
                        ("created_at", models.DateTimeField(auto_now_add=True)),
                        ("updated_at", models.DateTimeField(auto_now=True)),
                        (
                            "job",
                            models.OneToOneField(
                                on_delete=django.db.models.deletion.CASCADE,
                                related_name="workflow_state",
                                to="imports.importjob",
                            ),
                        ),
                    ],
                    options={"ordering": ["job_id"]},
                ),
                migrations.AddField(
                    model_name="importchunkphase",
                    name="heartbeat_at",
                    field=models.DateTimeField(blank=True, null=True),
                ),
                migrations.AddIndex(
                    model_name="importworkflowstate",
                    index=models.Index(
                        fields=["status", "queued_at"],
                        name="idx_imp_wf_status_queue",
                    ),
                ),
                migrations.AddIndex(
                    model_name="importworkflowstate",
                    index=models.Index(
                        fields=["execution_profile"],
                        name="idx_imp_wf_exec_profile",
                    ),
                ),
            ],
        ),
    ]
