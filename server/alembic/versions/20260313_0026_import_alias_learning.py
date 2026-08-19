"""Add import agency alias memory and correction signals.

Revision ID: 20260313_0026
Revises: 20260312_0025
Create Date: 2026-03-13
"""

from __future__ import annotations

from alembic import op

revision = "20260313_0026"
down_revision = "20260312_0025"
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
            ) AND EXISTS (
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = current_schema()
                  AND table_name = 'imports_importjob'
            ) AND NOT EXISTS (
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = current_schema()
                  AND table_name = 'imports_importagencyalias'
            ) THEN
                DROP SEQUENCE IF EXISTS imports_importagencyalias_id_seq CASCADE;
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
                  AND table_name = 'imports_importcorrectionsignal'
            ) THEN
                DROP SEQUENCE IF EXISTS imports_importcorrectionsignal_id_seq CASCADE;
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
                  AND table_name = 'imports_importagencyalias'
            ) THEN
                CREATE INDEX IF NOT EXISTS idx_imp_alias_ag_dom_state
                ON imports_importagencyalias(agency_id, domain, state);
                CREATE INDEX IF NOT EXISTS idx_imp_alias_ag_source
                ON imports_importagencyalias(agency_id, source_value_normalized);
            END IF;
            IF EXISTS (
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = current_schema()
                  AND table_name = 'imports_importcorrectionsignal'
            ) THEN
                CREATE INDEX IF NOT EXISTS idx_imp_corrsig_ag_dom_src
                ON imports_importcorrectionsignal(agency_id, domain, source_value_normalized);
                CREATE INDEX IF NOT EXISTS idx_imp_corrsig_ag_field_ct
                ON imports_importcorrectionsignal(agency_id, field_name, created_at);
                CREATE INDEX IF NOT EXISTS idx_imp_corrsig_job_row
                ON imports_importcorrectionsignal(job_id, row_ordinal);
            END IF;
        END
        $$;
        """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_imp_corrsig_job_row")
    op.execute("DROP INDEX IF EXISTS idx_imp_corrsig_ag_field_ct")
    op.execute("DROP INDEX IF EXISTS idx_imp_corrsig_ag_dom_src")
    op.execute("DROP INDEX IF EXISTS idx_imp_alias_ag_source")
    op.execute("DROP INDEX IF EXISTS idx_imp_alias_ag_dom_state")
    op.execute("DROP TABLE IF EXISTS imports_importcorrectionsignal")
    op.execute("DROP TABLE IF EXISTS imports_importagencyalias")
