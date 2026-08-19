"""Service orchestrator for audit operations."""

from __future__ import annotations

from app.models import AuditLog
from app.models_cast import as_int
from app.services.api_client import api_delete, api_get, as_dict


def fetch_audit_logs(
    limit: int = 200,
    offset: int = 0,
    table_name: str | None = None,
    record_id: str | None = None,
    actor: str | None = None,
    action: str | None = None,
    start_ts: str | None = None,
    end_ts: str | None = None,
) -> list[AuditLog]:
    """Fetch audit logs using UoW."""
    response = api_get(
        "/audit/logs",
        params={
            "limit": limit,
            "offset": offset,
            "table_name": table_name,
            "record_id": record_id,
            "actor": actor,
            "action": action,
            "start_ts": start_ts,
            "end_ts": end_ts,
        },
    )
    payload = as_dict(response)
    items = payload.get("items")
    if isinstance(items, list):
        return [AuditLog.from_row(item) for item in items if isinstance(item, dict)]
    return []


def count_audit_logs(
    table_name: str | None = None,
    record_id: str | None = None,
    actor: str | None = None,
    action: str | None = None,
    start_ts: str | None = None,
    end_ts: str | None = None,
) -> int:
    """Count audit logs using UoW."""
    response = api_get(
        "/audit/count",
        params={
            "table_name": table_name,
            "record_id": record_id,
            "actor": actor,
            "action": action,
            "start_ts": start_ts,
            "end_ts": end_ts,
        },
    )
    payload = as_dict(response)
    return as_int(payload.get("total"), default=0)


def purge_audit_logs() -> int:
    """Purge all audit logs using UoW."""
    payload = as_dict(api_delete("/audit/purge", params={"confirm": "PURGE_AUDIT_LOGS"}))
    return as_int(payload.get("purged"), default=0)
