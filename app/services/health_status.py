"""
Service helpers for system health snapshots.

Provides a single read-only snapshot so UI code does not manage DB connections.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.models_cast import as_int
from app.services.api_client import api_get, as_dict
from app.utils.row_casts import as_optional_str


@dataclass(frozen=True)
class HealthSnapshot:
    """Immutable snapshot of DB health metadata."""

    db_path: str
    active_connections: int
    audit_actor: str
    schema_version: str | None
    settings_schema_version: str | None
    last_repair: str | None
    last_backup_ts: str | None
    last_backup_reason: str | None
    last_backup_path: str | None


def fetch_health_snapshot() -> HealthSnapshot:
    """Fetch current health metrics from the active database."""
    payload = as_dict(api_get("/health/snapshot"))
    return HealthSnapshot(
        db_path=str(payload.get("db_path", "")),
        active_connections=as_int(payload.get("active_connections"), default=0),
        audit_actor=str(payload.get("audit_actor", "")),
        schema_version=as_optional_str(payload.get("schema_version")),
        settings_schema_version=as_optional_str(payload.get("settings_schema_version")),
        last_repair=as_optional_str(payload.get("last_repair")),
        last_backup_ts=as_optional_str(payload.get("last_backup_ts")),
        last_backup_reason=as_optional_str(payload.get("last_backup_reason")),
        last_backup_path=as_optional_str(payload.get("last_backup_path")),
    )
