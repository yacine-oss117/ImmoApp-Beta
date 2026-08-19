"""pg_trgm + numeric hardening

Revision ID: 20260204_0002
Revises: 20260204_0001
Create Date: 2026-02-04
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "20260204_0002"
down_revision = "20260204_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute("CREATE EXTENSION IF NOT EXISTS unaccent")
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute("""
        CREATE OR REPLACE FUNCTION immoapp_norm_text(input_text TEXT)
        RETURNS TEXT
        LANGUAGE sql
        IMMUTABLE
        AS $$
            SELECT lower(unaccent(coalesce(input_text, '')))
        $$;
        """)
    op.execute("DROP FUNCTION IF EXISTS immoapp_hash_trigrams(TEXT)")
    op.execute("""
        CREATE OR REPLACE FUNCTION immoapp_hash_trigrams(input_text TEXT)
        RETURNS TEXT[]
        LANGUAGE plpgsql
        STABLE
        AS $$
        DECLARE
            norm TEXT;
            secret TEXT;
        BEGIN
            norm := immoapp_norm_text(input_text);
            IF norm = '' THEN
                RETURN ARRAY[]::TEXT[];
            END IF;

            secret := current_setting('app.ale_search_secret', true);
            IF secret IS NULL OR secret = '' THEN
                RAISE EXCEPTION 'app.ale_search_secret is required for immoapp_hash_trigrams()';
            END IF;

            RETURN COALESCE(
                (
                    SELECT array_agg(DISTINCT substring(encode(hmac(tri, secret, 'sha256'), 'hex') FROM 1 FOR 32))
                    FROM unnest(show_trgm(norm)) AS tri
                ),
                ARRAY[]::TEXT[]
            );
        END
        $$;
        """)

    op.execute("""
        DO $$
        BEGIN
            BEGIN
                ALTER TABLE offers ALTER COLUMN surface TYPE NUMERIC USING surface::NUMERIC;
            EXCEPTION WHEN undefined_column OR undefined_table THEN NULL;
            END;
            BEGIN
                ALTER TABLE offers ALTER COLUMN budget TYPE NUMERIC USING budget::NUMERIC;
            EXCEPTION WHEN undefined_column OR undefined_table THEN NULL;
            END;
            BEGIN
                ALTER TABLE demandes ALTER COLUMN surface_min TYPE NUMERIC USING surface_min::NUMERIC;
            EXCEPTION WHEN undefined_column OR undefined_table THEN NULL;
            END;
            BEGIN
                ALTER TABLE demandes ALTER COLUMN surface_max TYPE NUMERIC USING surface_max::NUMERIC;
            EXCEPTION WHEN undefined_column OR undefined_table THEN NULL;
            END;
            BEGIN
                ALTER TABLE demandes ALTER COLUMN budget_min TYPE NUMERIC USING budget_min::NUMERIC;
            EXCEPTION WHEN undefined_column OR undefined_table THEN NULL;
            END;
            BEGIN
                ALTER TABLE demandes ALTER COLUMN budget_max TYPE NUMERIC USING budget_max::NUMERIC;
            EXCEPTION WHEN undefined_column OR undefined_table THEN NULL;
            END;
        END $$;
        """)

    op.execute("""
        DO $$
        BEGIN
            IF to_regclass('offers') IS NOT NULL THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS idx_offers_location_trgm '
                     || 'ON offers USING GIN (location gin_trgm_ops) '
                     || 'WHERE deleted_at IS NULL';
            END IF;
            IF to_regclass('demandes') IS NOT NULL THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS idx_demandes_locations_trgm '
                     || 'ON demandes USING GIN (locations gin_trgm_ops) '
                     || 'WHERE deleted_at IS NULL';
            END IF;
            IF to_regclass('custom_locations') IS NOT NULL THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS idx_custom_locations_name_trgm '
                     || 'ON custom_locations USING GIN (name gin_trgm_ops) '
                     || 'WHERE deleted_at IS NULL';
            END IF;
        END $$;
        """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_custom_locations_name_trgm")
    op.execute("DROP INDEX IF EXISTS idx_demandes_locations_trgm")
    op.execute("DROP INDEX IF EXISTS idx_offers_location_trgm")
    op.execute("DROP FUNCTION IF EXISTS immoapp_hash_trigrams(TEXT)")
    op.execute("DROP FUNCTION IF EXISTS immoapp_norm_text(TEXT)")
    # Keep column type changes and extensions in place on downgrade for data safety.
