"""Add durable rebuild lease table for API coalescing/backpressure.

Revision ID: 20260303_0019
Revises: 20260221_0018
Create Date: 2026-03-03
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "20260303_0019"
down_revision = "20260221_0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS api_rebuild_job_leases (
            id BIGSERIAL PRIMARY KEY,
            agency_id BIGINT NOT NULL,
            job_type TEXT NOT NULL,
            scope_key TEXT NOT NULL DEFAULT '_',
            task_id TEXT NOT NULL,
            status TEXT NOT NULL,
            last_error TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            expires_at TIMESTAMPTZ NOT NULL,
            CONSTRAINT chk_api_rebuild_job_leases_status
                CHECK (status IN ('queued', 'running', 'done', 'failed')),
            CONSTRAINT chk_api_rebuild_job_leases_scope_key
                CHECK (scope_key <> '')
        )
        """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_api_rebuild_job_leases_agency_status_updated
        ON api_rebuild_job_leases (agency_id, status, updated_at DESC)
        """)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_api_rebuild_job_leases_task_id
        ON api_rebuild_job_leases (task_id)
        """)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_api_rebuild_job_leases_active
        ON api_rebuild_job_leases (agency_id, job_type, scope_key)
        WHERE status IN ('queued', 'running')
        """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS api_rebuild_job_leases")
