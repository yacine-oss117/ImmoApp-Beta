"""Prepare and repair tenant-qualified foreign-key hardening.

Revision ID: 20260309_0021
Revises: 20260308_0020
Create Date: 2026-03-09
"""

from __future__ import annotations

from alembic import op

from server.pg.tenant_fk_hardening import assert_report_ok, repair_tenant_integrity

revision = "20260309_0021"
down_revision = "20260308_0020"
branch_labels = None
depends_on = None


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
    report = repair_tenant_integrity(op.get_bind())
    assert_report_ok(report)


def downgrade() -> None:
    pass
