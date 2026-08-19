"""Add matcher selectivity indexes (junction + strict)."""

from __future__ import annotations

from alembic import op

revision = "20260206_0010"
down_revision = "20260206_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_demandes_active_agency_action_type "
        "ON demandes(agency_id, action_id, type_id) "
        "WHERE deleted_at IS NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_offers_active_agency_action_type "
        "ON offers(agency_id, action_id, type_id) "
        "WHERE status = 'available' AND deleted_at IS NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_demande_loc_agency "
        "ON demande_locations(agency_id, location_id, demande_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_offer_loc_agency "
        "ON offer_locations(agency_id, location_id, offer_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_offer_loc_agency")
    op.execute("DROP INDEX IF EXISTS idx_demande_loc_agency")
    op.execute("DROP INDEX IF EXISTS idx_offers_active_agency_action_type")
    op.execute("DROP INDEX IF EXISTS idx_demandes_active_agency_action_type")
