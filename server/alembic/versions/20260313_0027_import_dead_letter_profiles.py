"""Add import agency profiles and dead-letter rows.

Revision ID: 20260313_0027
Revises: 20260313_0026
Create Date: 2026-03-13
"""

from __future__ import annotations

from alembic import op

revision = "20260313_0027"
down_revision = "20260313_0026"
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
                  AND table_name = 'accounts_agency'
            ) AND NOT EXISTS (
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = current_schema()
                  AND table_name = 'imports_importagencyprofile'
            ) THEN
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
                  AND table_name = 'accounts_agency'
            ) AND EXISTS (
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = current_schema()
                  AND table_name = 'imports_importjob'
            ) AND NOT EXISTS (
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = current_schema()
                  AND table_name = 'imports_importdeadletterrow'
            ) THEN
                DROP SEQUENCE IF EXISTS imports_importdeadletterrow_id_seq CASCADE;
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
                  AND table_name = 'imports_importdeadletterrow'
            ) THEN
                CREATE INDEX IF NOT EXISTS idx_imp_dead_ag_created
                ON imports_importdeadletterrow(agency_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_imp_dead_job_row
                ON imports_importdeadletterrow(job_id, row_ordinal);
                CREATE INDEX IF NOT EXISTS idx_imp_dead_ag_disp_ct
                ON imports_importdeadletterrow(agency_id, disposition, created_at);
            END IF;
        END
        $$;
        """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_imp_dead_ag_disp_ct")
    op.execute("DROP INDEX IF EXISTS idx_imp_dead_job_row")
    op.execute("DROP INDEX IF EXISTS idx_imp_dead_ag_created")
    op.execute("DROP TABLE IF EXISTS imports_importdeadletterrow")
    op.execute("DROP TABLE IF EXISTS imports_importagencyprofile")
