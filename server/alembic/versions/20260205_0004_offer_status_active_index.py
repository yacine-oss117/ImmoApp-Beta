"""offer status + active-offer index hardening

Revision ID: 20260205_0004
Revises: 20260205_0003
Create Date: 2026-02-05
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "20260205_0004"
down_revision = "20260205_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        DO $$
        BEGIN
            IF to_regclass('offers') IS NULL THEN
                RETURN;
            END IF;
            ALTER TABLE offers ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'available';
            UPDATE offers SET status = 'available' WHERE status IS NULL OR status = '';
            CREATE INDEX IF NOT EXISTS idx_offers_active_agency_action_wilaya_type_v2
                ON offers(agency_id, action_id, wilaya_id, type_id)
                WHERE status = 'available' AND deleted_at IS NULL;
        END $$;
        """)


def downgrade() -> None:
    # Keep status column for forward compatibility and data safety.
    op.execute("DROP INDEX IF EXISTS idx_offers_active_agency_action_wilaya_type_v2")
