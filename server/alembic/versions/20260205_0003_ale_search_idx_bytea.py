"""ALE search index bytea + function hardening

Revision ID: 20260205_0003
Revises: 20260204_0002
Create Date: 2026-02-05
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "20260205_0003"
down_revision = "20260204_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE OR REPLACE FUNCTION immoapp_hex_text_array_to_bytea(p_values TEXT[])
        RETURNS BYTEA[]
        LANGUAGE sql
        IMMUTABLE
        AS $$
            SELECT CASE
                WHEN p_values IS NULL THEN NULL
                ELSE ARRAY(
                    SELECT decode(v, 'hex')
                    FROM unnest(p_values) AS v
                )
            END
        $$;
        """)
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = current_schema()
                  AND table_name = 'clients'
                  AND column_name = 'family_name_search_idx'
                  AND udt_name = '_text'
            ) THEN
                ALTER TABLE clients
                ALTER COLUMN family_name_search_idx TYPE BYTEA[]
                USING immoapp_hex_text_array_to_bytea(family_name_search_idx);
            END IF;
        END $$;
        """)
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = current_schema()
                  AND table_name = 'clients'
                  AND column_name = 'phone_search_idx'
                  AND udt_name = '_text'
            ) THEN
                ALTER TABLE clients
                ALTER COLUMN phone_search_idx TYPE BYTEA[]
                USING immoapp_hex_text_array_to_bytea(phone_search_idx);
            END IF;
        END $$;
        """)
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = current_schema()
                  AND table_name = 'listings'
                  AND column_name = 'family_name_search_idx'
                  AND udt_name = '_text'
            ) THEN
                ALTER TABLE listings
                ALTER COLUMN family_name_search_idx TYPE BYTEA[]
                USING immoapp_hex_text_array_to_bytea(family_name_search_idx);
            END IF;
        END $$;
        """)
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = current_schema()
                  AND table_name = 'listings'
                  AND column_name = 'phone_search_idx'
                  AND udt_name = '_text'
            ) THEN
                ALTER TABLE listings
                ALTER COLUMN phone_search_idx TYPE BYTEA[]
                USING immoapp_hex_text_array_to_bytea(phone_search_idx);
            END IF;
        END $$;
        """)
    op.execute("""
        DROP FUNCTION IF EXISTS immoapp_hash_trigrams(TEXT);
        """)
    op.execute("""
        CREATE OR REPLACE FUNCTION immoapp_hash_trigrams(input_text TEXT)
        RETURNS BYTEA[]
        LANGUAGE plpgsql
        STABLE
        AS $$
        DECLARE
            norm TEXT;
            secret TEXT;
            trigram_limit INTEGER;
        BEGIN
            norm := immoapp_norm_text(input_text);
            IF norm = '' THEN
                RETURN ARRAY[]::BYTEA[];
            END IF;

            secret := current_setting('app.ale_search_secret', true);
            IF secret IS NULL OR secret = '' THEN
                RAISE EXCEPTION 'app.ale_search_secret is required for immoapp_hash_trigrams()';
            END IF;
            trigram_limit := COALESCE(
                NULLIF(current_setting('app.ale_trigram_limit', true), '')::INTEGER,
                128
            );
            IF trigram_limit < 16 THEN
                trigram_limit := 16;
            END IF;

            RETURN COALESCE(
                (
                    SELECT array_agg(DISTINCT substring(hmac(tri, secret, 'sha256') FROM 1 FOR 12))
                    FROM (
                        SELECT tri
                        FROM unnest(show_trgm(norm)) AS tri
                        LIMIT trigram_limit
                    ) limited
                ),
                ARRAY[]::BYTEA[]
            );
        END
        $$;
        """)


def downgrade() -> None:
    op.execute("""
        CREATE OR REPLACE FUNCTION immoapp_bytea_array_to_hex_text(p_values BYTEA[])
        RETURNS TEXT[]
        LANGUAGE sql
        IMMUTABLE
        AS $$
            SELECT CASE
                WHEN p_values IS NULL THEN NULL
                ELSE ARRAY(
                    SELECT encode(v, 'hex')
                    FROM unnest(p_values) AS v
                )
            END
        $$;
        """)
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = current_schema()
                  AND table_name = 'clients'
                  AND column_name = 'family_name_search_idx'
                  AND udt_name = '_bytea'
            ) THEN
                ALTER TABLE clients
                ALTER COLUMN family_name_search_idx TYPE TEXT[]
                USING immoapp_bytea_array_to_hex_text(family_name_search_idx);
            END IF;
        END $$;
        """)
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = current_schema()
                  AND table_name = 'clients'
                  AND column_name = 'phone_search_idx'
                  AND udt_name = '_bytea'
            ) THEN
                ALTER TABLE clients
                ALTER COLUMN phone_search_idx TYPE TEXT[]
                USING immoapp_bytea_array_to_hex_text(phone_search_idx);
            END IF;
        END $$;
        """)
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = current_schema()
                  AND table_name = 'listings'
                  AND column_name = 'family_name_search_idx'
                  AND udt_name = '_bytea'
            ) THEN
                ALTER TABLE listings
                ALTER COLUMN family_name_search_idx TYPE TEXT[]
                USING immoapp_bytea_array_to_hex_text(family_name_search_idx);
            END IF;
        END $$;
        """)
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = current_schema()
                  AND table_name = 'listings'
                  AND column_name = 'phone_search_idx'
                  AND udt_name = '_bytea'
            ) THEN
                ALTER TABLE listings
                ALTER COLUMN phone_search_idx TYPE TEXT[]
                USING immoapp_bytea_array_to_hex_text(phone_search_idx);
            END IF;
        END $$;
        """)
    op.execute("""
        DROP FUNCTION IF EXISTS immoapp_hash_trigrams(TEXT);
        """)
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
