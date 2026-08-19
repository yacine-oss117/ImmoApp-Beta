"""ALE search key versioning and dual-secret hash support.

Revision ID: 20260205_0005
Revises: 20260205_0004
Create Date: 2026-02-05
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "20260205_0005"
down_revision = "20260205_0004"
branch_labels = None
depends_on = None


def _create_dual_secret_hash_function() -> None:
    op.execute("DROP FUNCTION IF EXISTS immoapp_hash_trigrams(TEXT)")
    op.execute("""
        CREATE OR REPLACE FUNCTION immoapp_hash_trigrams(input_text TEXT)
        RETURNS BYTEA[]
        LANGUAGE plpgsql
        STABLE
        AS $$
        DECLARE
            norm TEXT;
            secret TEXT;
            secrets_text TEXT;
            secrets TEXT[];
            trigram_limit INTEGER;
        BEGIN
            norm := immoapp_norm_text(input_text);
            IF norm = '' THEN
                RETURN ARRAY[]::BYTEA[];
            END IF;

            secrets_text := current_setting('app.ale_search_secrets', true);
            IF secrets_text IS NOT NULL AND secrets_text <> '' THEN
                secrets := array_remove(string_to_array(secrets_text, ';'), '');
            END IF;
            IF secrets IS NULL OR array_length(secrets, 1) IS NULL THEN
                secret := current_setting('app.ale_search_secret', true);
                IF secret IS NULL OR secret = '' THEN
                    RAISE EXCEPTION 'app.ale_search_secret/app.ale_search_secrets is required for immoapp_hash_trigrams()';
                END IF;
                secrets := ARRAY[secret];
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
                    SELECT array_agg(
                        DISTINCT substring(hmac(tri, sec.secret, 'sha256') FROM 1 FOR 12)
                    )
                    FROM (
                        SELECT tri
                        FROM unnest(show_trgm(norm)) AS tri
                        LIMIT trigram_limit
                    ) limited
                    CROSS JOIN unnest(secrets) AS sec(secret)
                ),
                ARRAY[]::BYTEA[]
            );
        END
        $$;
        """)


def _bootstrap_rotation_meta() -> None:
    op.execute("""
        INSERT INTO meta (key, value)
        VALUES ('ale_search_key_version', 'v1')
        ON CONFLICT (key) DO NOTHING
        """)
    op.execute("""
        INSERT INTO meta (key, value)
        VALUES ('ale_search_key_prev_version', '')
        ON CONFLICT (key) DO NOTHING
        """)


def upgrade() -> None:
    _create_dual_secret_hash_function()
    _bootstrap_rotation_meta()


def downgrade() -> None:
    # Keep meta rows; revert function to single-secret behavior.
    op.execute("DROP FUNCTION IF EXISTS immoapp_hash_trigrams(TEXT)")
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
