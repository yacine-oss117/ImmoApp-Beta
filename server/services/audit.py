"""
Postgres-backed audit log operations.
"""

from __future__ import annotations

import os

from core.data import audit_repository as data
from core.models import AuditLog
from server.pg.uow import get_uow


def _read_int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


MAX_AUDIT_LOG_LIMIT = max(1, _read_int_env("AUDIT_LOG_MAX_LIMIT", 1000))


def fetch_audit_logs(
    *,
    limit: int = 200,
    offset: int = 0,
    table_name: str | None = None,
    record_id: str | None = None,
    actor: str | None = None,
    action: str | None = None,
    start_ts: str | None = None,
    end_ts: str | None = None,
) -> list[AuditLog]:
    """Query audit logs with various filters."""
    bounded_limit = max(1, min(limit, MAX_AUDIT_LOG_LIMIT))
    bounded_offset = max(0, offset)
    with get_uow().session() as session:
        return data.fetch_audit_logs(
            session,
            limit=bounded_limit,
            offset=bounded_offset,
            table_name=table_name,
            record_id=record_id,
            actor=actor,
            action=action,
            start_ts=start_ts,
            end_ts=end_ts,
        )


def count_audit_logs(
    *,
    table_name: str | None = None,
    record_id: str | None = None,
    actor: str | None = None,
    action: str | None = None,
    start_ts: str | None = None,
    end_ts: str | None = None,
) -> int:
    """Return the number of audit logs matching the given filters."""
    with get_uow().session() as session:
        return data.count_audit_logs(
            session,
            table_name=table_name,
            record_id=record_id,
            actor=actor,
            action=action,
            start_ts=start_ts,
            end_ts=end_ts,
        )


def purge_audit_logs(*, actor: str | None = None) -> int:
    """Permanently delete all audit logs for an agency."""
    with get_uow().transaction(actor=actor) as session:
        return data.purge_audit_logs(session)
