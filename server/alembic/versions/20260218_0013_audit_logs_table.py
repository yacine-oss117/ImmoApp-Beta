"""Add audit logs table for tenant-scoped immutable trail.

Revision ID: 20260218_0013
Revises: 20260212_0012
Create Date: 2026-02-18
"""

from __future__ import annotations

from alembic import op

revision = "20260218_0013"
down_revision = "20260212_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS audit_logs (
            id BIGSERIAL PRIMARY KEY,
            ts TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            actor TEXT,
            action TEXT NOT NULL,
            table_name TEXT NOT NULL,
            record_id TEXT,
            details JSONB,
            agency_id BIGINT DEFAULT NULLIF(current_setting('app.current_agency_id', true), '')::bigint
        )
        """)
    op.execute("""
        DO $$
        BEGIN
            IF to_regclass('public.accounts_agency') IS NULL THEN
                RETURN;
            END IF;
            ALTER TABLE audit_logs
            DROP CONSTRAINT IF EXISTS fk_audit_logs_agency;
            ALTER TABLE audit_logs
            ADD CONSTRAINT fk_audit_logs_agency
            FOREIGN KEY (agency_id) REFERENCES accounts_agency(id) ON DELETE SET NULL;
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;
        """)
    op.execute("ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE audit_logs FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS policy_audit_logs_isolation ON audit_logs")
    op.execute("""
        CREATE POLICY policy_audit_logs_isolation ON audit_logs
        USING (
            (NULLIF(current_setting('app.is_superuser', true), '')::boolean = true)
            OR (
                agency_id = NULLIF(current_setting('app.current_agency_id', true), '')::bigint
            )
        )
        WITH CHECK (
            (NULLIF(current_setting('app.is_superuser', true), '')::boolean = true)
            OR (
                agency_id = NULLIF(current_setting('app.current_agency_id', true), '')::bigint
            )
        )
        """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_audit_logs_agency_id ON audit_logs(agency_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_audit_logs_ts_desc ON audit_logs(ts DESC)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS audit_logs")
