"""Add import workflow state table and chunk-phase heartbeat column.

Revision ID: 20260312_0025
Revises: 20260312_0024
Create Date: 2026-03-12
"""

from __future__ import annotations

from alembic import op

revision = "20260312_0025"
down_revision = "20260312_0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = current_schema()
                  AND table_name = 'imports_importjob'
            ) THEN
                CREATE TABLE IF NOT EXISTS imports_importworkflowstate (
                    id BIGSERIAL PRIMARY KEY,
                    job_id UUID NOT NULL UNIQUE
                        REFERENCES imports_importjob(id) ON DELETE CASCADE,
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
            END IF;
        END
        $$;
        """)
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = current_schema()
                  AND table_name = 'imports_importworkflowstate'
            ) THEN
                CREATE INDEX IF NOT EXISTS idx_imp_wf_status_queue
                ON imports_importworkflowstate(status, queued_at);
            END IF;
        END
        $$;
        """)
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = current_schema()
                  AND table_name = 'imports_importworkflowstate'
            ) THEN
                CREATE INDEX IF NOT EXISTS idx_imp_wf_exec_profile
                ON imports_importworkflowstate(execution_profile);
            END IF;
        END
        $$;
        """)
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = current_schema()
                  AND table_name = 'imports_importchunkphase'
            ) THEN
                ALTER TABLE imports_importchunkphase
                ADD COLUMN IF NOT EXISTS heartbeat_at TIMESTAMPTZ NULL;
            END IF;
        END
        $$;
        """)


def downgrade() -> None:
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = current_schema()
                  AND table_name = 'imports_importchunkphase'
            ) THEN
                ALTER TABLE imports_importchunkphase
                DROP COLUMN IF EXISTS heartbeat_at;
            END IF;
        END
        $$;
        """)
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = current_schema()
                  AND table_name = 'imports_importworkflowstate'
            ) THEN
                DROP INDEX IF EXISTS idx_imp_wf_exec_profile;
                DROP INDEX IF EXISTS idx_imp_wf_status_queue;
                DROP TABLE IF EXISTS imports_importworkflowstate;
            END IF;
        END
        $$;
        """)
