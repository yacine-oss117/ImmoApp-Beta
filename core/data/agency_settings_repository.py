"""
Agency Settings Repository - Store agency branding and configuration.
"""

from __future__ import annotations

from datetime import datetime

from core.matcher.ports.db import DbSession
from core.utils.row_casts import row_int, row_str
from core.utils.time import utc_now_iso

# Default settings
DEFAULT_SETTINGS = {
    "agency_name": "Real Estate Agency",
    "agency_logo_path": "",  # Empty = no logo
    "agency_signature_path": "",
    "default_security_deposit_months": "1",
    "contract_serial_prefix": "C21",
    "pdf_password": "",  # Empty = no password protection
    "audit_actor": "Yacine",
}


def get_agency_setting(session: DbSession, key: str, default: str = "") -> str:
    """Get a single agency setting value."""
    sql = "SELECT value FROM agency_settings WHERE key = %s AND deleted_at IS NULL"
    params: list[object] = [key]
    row = session.execute(sql, params).fetchone()
    return row_str(row, "value", default=default) if row else default


def set_agency_setting(session: DbSession, key: str, value: str) -> None:
    """Set a single agency setting value."""
    now = utc_now_iso()
    session.execute(
        """
        INSERT INTO agency_settings (key, value, updated_at)
        VALUES (%s, %s, %s)
        ON CONFLICT (agency_id, key) DO UPDATE
        SET value = EXCLUDED.value,
            updated_at = EXCLUDED.updated_at,
            deleted_at = NULL,
            row_version = agency_settings.row_version + 1
        """,
        (key, value, now),
    )


def get_all_agency_settings(session: DbSession) -> dict[str, str]:
    """Get all agency settings as a dictionary."""
    sql = "SELECT key, value FROM agency_settings WHERE deleted_at IS NULL"
    params: list[object] = []
    rows = session.execute(sql, params).fetchall()
    return {row_str(row, "key"): row_str(row, "value") for row in rows}


def generate_contract_serial(session: DbSession, prefix: str) -> str:
    """Generate a unique contract serial number."""
    year = datetime.now().year
    counter_key = f"contract_counter_{year}"

    # Get current counter
    row = session.execute(
        "SELECT value FROM agency_settings WHERE key = %s AND deleted_at IS NULL",
        (counter_key,),
    ).fetchone()

    current = row_int(row, "value") if row else 0
    next_num = current + 1

    # Update counter
    now = utc_now_iso()
    session.execute(
        """
        INSERT INTO agency_settings (key, value, updated_at)
        VALUES (%s, %s, %s)
        ON CONFLICT (agency_id, key) DO UPDATE
        SET value = EXCLUDED.value,
            updated_at = EXCLUDED.updated_at,
            deleted_at = NULL,
            row_version = agency_settings.row_version + 1
        """,
        (counter_key, str(next_num), now),
    )

    serial = f"{prefix}-{year}-{next_num:04d}"
    return serial
