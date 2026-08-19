"""Add durable dispatch queue fields to match_rebuild_state.

Revision ID: 20260312_0024
Revises: 20260309_0023
Create Date: 2026-03-12
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "20260312_0024"
down_revision = "20260309_0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE match_rebuild_state "
        "ADD COLUMN IF NOT EXISTS dispatch_after TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP"
    )
    op.execute(
        "ALTER TABLE match_rebuild_state " "ADD COLUMN IF NOT EXISTS dispatch_claim_token TEXT"
    )
    op.execute(
        "ALTER TABLE match_rebuild_state "
        "ADD COLUMN IF NOT EXISTS dispatch_claim_expires_at TIMESTAMPTZ"
    )
    op.execute(
        "ALTER TABLE match_rebuild_state "
        "ADD COLUMN IF NOT EXISTS last_requested_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP"
    )
    op.execute(
        "UPDATE match_rebuild_state "
        "SET dispatch_after = COALESCE(dispatch_after, CURRENT_TIMESTAMP), "
        "    last_requested_at = COALESCE(last_requested_at, updated_at, CURRENT_TIMESTAMP)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_match_rebuild_dispatch_ready "
        "ON match_rebuild_state(scope, pending, dispatch_after)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_match_rebuild_dispatch_claim "
        "ON match_rebuild_state(scope, dispatch_claim_expires_at)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_match_rebuild_dispatch_claim")
    op.execute("DROP INDEX IF EXISTS idx_match_rebuild_dispatch_ready")
    op.execute("ALTER TABLE match_rebuild_state DROP COLUMN IF EXISTS last_requested_at")
    op.execute("ALTER TABLE match_rebuild_state DROP COLUMN IF EXISTS dispatch_claim_expires_at")
    op.execute("ALTER TABLE match_rebuild_state DROP COLUMN IF EXISTS dispatch_claim_token")
    op.execute("ALTER TABLE match_rebuild_state DROP COLUMN IF EXISTS dispatch_after")
