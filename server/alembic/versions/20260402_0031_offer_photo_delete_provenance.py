"""Add explicit offer-photo delete provenance.

Revision ID: 20260402_0031
Revises: 20260330_0030
Create Date: 2026-04-02
"""

from __future__ import annotations

from alembic import op

revision = "20260402_0031"
down_revision = "20260330_0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE offer_photos ADD COLUMN IF NOT EXISTS delete_origin TEXT")
    op.execute("ALTER TABLE offer_photos ADD COLUMN IF NOT EXISTS delete_parent_scope TEXT")
    op.execute("ALTER TABLE offer_photos ADD COLUMN IF NOT EXISTS delete_parent_id BIGINT")
    op.execute("""
        UPDATE offer_photos
        SET delete_origin = 'manual'
        WHERE deleted_at IS NOT NULL
          AND delete_origin IS NULL
          AND delete_parent_scope IS NULL
          AND delete_parent_id IS NULL
        """)
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'chk_offer_photos_delete_origin'
            ) THEN
                ALTER TABLE offer_photos
                ADD CONSTRAINT chk_offer_photos_delete_origin
                CHECK (
                    delete_origin IS NULL
                    OR delete_origin IN (
                        'manual',
                        'offer_deleted',
                        'listing_deleted',
                        'offer_purged',
                        'listing_purged'
                    )
                );
            END IF;
        END $$;
        """)
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'chk_offer_photos_delete_parent_scope'
            ) THEN
                ALTER TABLE offer_photos
                ADD CONSTRAINT chk_offer_photos_delete_parent_scope
                CHECK (
                    delete_parent_scope IS NULL
                    OR delete_parent_scope IN ('offer', 'listing')
                );
            END IF;
        END $$;
        """)
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'chk_offer_photos_delete_provenance'
            ) THEN
                ALTER TABLE offer_photos
                ADD CONSTRAINT chk_offer_photos_delete_provenance
                CHECK (
                    (
                        delete_origin IS NULL
                        AND delete_parent_scope IS NULL
                        AND delete_parent_id IS NULL
                    )
                    OR (
                        delete_origin = 'manual'
                        AND delete_parent_scope IS NULL
                        AND delete_parent_id IS NULL
                    )
                    OR (
                        delete_origin IN ('offer_deleted', 'offer_purged')
                        AND delete_parent_scope = 'offer'
                        AND delete_parent_id IS NOT NULL
                    )
                    OR (
                        delete_origin IN ('listing_deleted', 'listing_purged')
                        AND delete_parent_scope = 'listing'
                        AND delete_parent_id IS NOT NULL
                    )
                );
            END IF;
        END $$;
        """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_offer_photos_restore_parent
        ON offer_photos(offer_id, delete_origin, delete_parent_scope, delete_parent_id)
        WHERE deleted_at IS NOT NULL
        """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_offer_photos_restore_parent")
    op.execute("""
        ALTER TABLE offer_photos
        DROP CONSTRAINT IF EXISTS chk_offer_photos_delete_provenance
        """)
    op.execute("""
        ALTER TABLE offer_photos
        DROP CONSTRAINT IF EXISTS chk_offer_photos_delete_parent_scope
        """)
    op.execute("""
        ALTER TABLE offer_photos
        DROP CONSTRAINT IF EXISTS chk_offer_photos_delete_origin
        """)
    op.execute("ALTER TABLE offer_photos DROP COLUMN IF EXISTS delete_parent_id")
    op.execute("ALTER TABLE offer_photos DROP COLUMN IF EXISTS delete_parent_scope")
    op.execute("ALTER TABLE offer_photos DROP COLUMN IF EXISTS delete_origin")
