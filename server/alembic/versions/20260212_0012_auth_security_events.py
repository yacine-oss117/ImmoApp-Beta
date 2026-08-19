"""Add auth security event audit table.

Revision ID: 20260212_0012
Revises: 20260206_0011
Create Date: 2026-02-12
"""

from __future__ import annotations

from alembic import op

revision = "20260212_0012"
down_revision = "20260206_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS auth_security_events (
            id BIGSERIAL PRIMARY KEY,
            agency_id BIGINT DEFAULT NULLIF(current_setting('app.current_agency_id', true), '')::bigint,
            user_id BIGINT,
            event_type TEXT NOT NULL,
            outcome TEXT NOT NULL DEFAULT 'unknown',
            identifier TEXT,
            reason_code TEXT,
            source_ip TEXT,
            user_agent TEXT,
            request_id TEXT,
            details JSONB,
            created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
        )
        """)
    op.execute("""
        DO $$
        BEGIN
            IF to_regclass('public.accounts_user') IS NULL THEN
                RETURN;
            END IF;
            ALTER TABLE auth_security_events
            ADD CONSTRAINT fk_auth_security_events_user
            FOREIGN KEY (user_id) REFERENCES accounts_user(id) ON DELETE SET NULL;
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;
        """)
    op.execute("""
        DO $$
        BEGIN
            IF to_regclass('public.accounts_agency') IS NULL THEN
                RETURN;
            END IF;
            ALTER TABLE auth_security_events
            DROP CONSTRAINT IF EXISTS fk_auth_security_events_agency;
            ALTER TABLE auth_security_events
            ADD CONSTRAINT fk_auth_security_events_agency
            FOREIGN KEY (agency_id) REFERENCES accounts_agency(id) ON DELETE SET NULL;
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;
        """)
    op.execute("""
        DO $$
        BEGIN
            ALTER TABLE auth_security_events
            ADD CONSTRAINT chk_auth_security_events_outcome
            CHECK (outcome IN ('attempt', 'success', 'failure', 'unknown'));
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;
        """)
    op.execute("""
        CREATE OR REPLACE FUNCTION auth_security_events_block_mod()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RETURN NULL;
        END;
        $$;
        """)
    op.execute("DROP TRIGGER IF EXISTS auth_security_events_no_mod ON auth_security_events")
    op.execute("""
        CREATE TRIGGER auth_security_events_no_mod
        BEFORE UPDATE OR DELETE ON auth_security_events
        FOR EACH ROW EXECUTE FUNCTION auth_security_events_block_mod()
        """)
    op.execute("ALTER TABLE auth_security_events ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE auth_security_events FORCE ROW LEVEL SECURITY")
    op.execute(
        "DROP POLICY IF EXISTS policy_auth_security_events_isolation ON auth_security_events"
    )
    op.execute("""
        CREATE POLICY policy_auth_security_events_isolation ON auth_security_events
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
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_auth_security_events_agency_id "
        "ON auth_security_events(agency_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_auth_security_events_created_at "
        "ON auth_security_events(created_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_auth_security_events_event_outcome "
        "ON auth_security_events(event_type, outcome, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_auth_security_events_user "
        "ON auth_security_events(user_id, created_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS auth_security_events_no_mod ON auth_security_events")
    op.execute("DROP FUNCTION IF EXISTS auth_security_events_block_mod()")
    op.execute("DROP TABLE IF EXISTS auth_security_events")
