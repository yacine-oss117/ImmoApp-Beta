"""Add tenant work lease table for fairness and queue isolation controls."""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "20260221_0018"
down_revision = "20260221_0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS tenant_work_lease (
            id BIGSERIAL PRIMARY KEY,
            task_name TEXT NOT NULL,
            agency_id BIGINT NOT NULL,
            stream_key TEXT NOT NULL,
            in_flight INTEGER NOT NULL DEFAULT 0,
            lease_owner TEXT,
            lease_until TIMESTAMPTZ,
            attempt INTEGER NOT NULL DEFAULT 0,
            last_id BIGINT NOT NULL DEFAULT 0,
            rows_processed BIGINT NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_tenant_work_lease_stream UNIQUE (task_name, agency_id, stream_key),
            CONSTRAINT chk_tenant_work_lease_in_flight CHECK (in_flight >= 0)
        )
        """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_tenant_work_lease_active
        ON tenant_work_lease (task_name, lease_until, agency_id)
        """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS tenant_work_lease")
