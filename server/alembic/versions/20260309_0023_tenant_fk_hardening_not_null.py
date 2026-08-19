"""Enforce non-null agency_id on tenant-owned tables.

Revision ID: 20260309_0023
Revises: 20260309_0022
Create Date: 2026-03-09
"""

from __future__ import annotations

from alembic import op

revision = "20260309_0023"
down_revision = "20260309_0022"
branch_labels = None
depends_on = None

_TABLES = (
    "clients",
    "listings",
    "demandes",
    "offers",
    "visits",
    "contracts",
    "contract_articles",
    "demande_locations",
    "offer_locations",
    "offer_photos",
    "match_candidates",
    "match_pairs",
)


def _accounts_agency_exists() -> bool:
    row = (
        op.get_bind()
        .exec_driver_sql("SELECT to_regclass('public.accounts_agency') AS table_name")
        .fetchone()
    )
    return bool(getattr(row, "_mapping", {}).get("table_name") if row is not None else None)


def upgrade() -> None:
    if not _accounts_agency_exists():
        return
    for table in _TABLES:
        op.execute(f"ALTER TABLE {table} ALTER COLUMN agency_id SET NOT NULL")


def downgrade() -> None:
    if not _accounts_agency_exists():
        return
    for table in reversed(_TABLES):
        op.execute(f"ALTER TABLE {table} ALTER COLUMN agency_id DROP NOT NULL")
