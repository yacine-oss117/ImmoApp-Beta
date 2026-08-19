"""Metadata helpers for schema and settings versions."""

from __future__ import annotations

from core.data.db_schema_constants import SETTINGS_SCHEMA_META_KEY, SETTINGS_SCHEMA_VERSION
from core.matcher.ports.db import DbSession


def ensure_meta_table(session: DbSession) -> None:
    """Assert metadata table exists (migration-owned schema)."""
    row = session.execute("SELECT to_regclass('public.meta') AS rel").fetchone()
    if not row or not row.get("rel"):
        raise RuntimeError(
            "Required table 'meta' is missing. Run database migrations before invoking meta helpers."
        )


def set_meta(session: DbSession, key: str, value: str) -> None:
    """Set a metadata value."""
    session.execute(
        "INSERT INTO meta (key, value) VALUES (%s, %s) "
        "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
        (key, value),
    )


def get_meta(session: DbSession, key: str) -> str | None:
    """Get a metadata value."""
    row = session.execute("SELECT value FROM meta WHERE key = %s", (key,)).fetchone()
    if row and "value" in row.keys():
        return str(row["value"])
    return None


def ensure_settings_schema_version(session: DbSession) -> None:
    """Record the current settings schema version in meta."""
    ensure_meta_table(session)
    raw = get_meta(session, SETTINGS_SCHEMA_META_KEY)
    try:
        current = int(raw) if raw is not None else 0
    except ValueError:
        current = 0
    if current < SETTINGS_SCHEMA_VERSION:
        set_meta(session, SETTINGS_SCHEMA_META_KEY, str(SETTINGS_SCHEMA_VERSION))
