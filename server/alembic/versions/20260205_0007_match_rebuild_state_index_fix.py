"""Fix match_rebuild_state agency_id index name.

Revision ID: 20260205_0007
Revises: 20260205_0006
Create Date: 2026-02-05
"""

from __future__ import annotations

from alembic import op

revision = "20260205_0007"
down_revision = "20260205_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_match_rebuild_state_agency")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_match_rebuild_state_agency_id "
        "ON match_rebuild_state(agency_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_match_rebuild_state_agency_id")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_match_rebuild_state_agency "
        "ON match_rebuild_state(agency_id)"
    )
