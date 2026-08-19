"""Enforce strict type/wilaya for demandes.

Revision ID: 20260206_0011
Revises: 20260206_0010
Create Date: 2026-02-06
"""

from __future__ import annotations

from alembic import op

revision = "20260206_0011"
down_revision = "20260206_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        DELETE FROM demandes
        WHERE type_id IS NULL
           OR wilaya_id IS NULL
           OR type_id <= 0
           OR wilaya_id <= 0
        """)
    op.execute("ALTER TABLE demandes ALTER COLUMN type_id SET NOT NULL")
    op.execute("ALTER TABLE demandes ALTER COLUMN wilaya_id SET NOT NULL")

    op.execute("""
        DO $$
        BEGIN
            ALTER TABLE demandes
            ADD CONSTRAINT chk_demandes_type_id_no_zero
            CHECK (type_id > 0);
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;
        """)
    op.execute("""
        DO $$
        BEGIN
            ALTER TABLE demandes
            ADD CONSTRAINT chk_demandes_wilaya_id_no_zero
            CHECK (wilaya_id > 0);
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;
        """)


def downgrade() -> None:
    op.execute("ALTER TABLE demandes ALTER COLUMN wilaya_id DROP NOT NULL")
    op.execute("ALTER TABLE demandes ALTER COLUMN type_id DROP NOT NULL")
    op.execute("ALTER TABLE demandes DROP CONSTRAINT IF EXISTS chk_demandes_type_id_no_zero")
    op.execute("ALTER TABLE demandes DROP CONSTRAINT IF EXISTS chk_demandes_wilaya_id_no_zero")
