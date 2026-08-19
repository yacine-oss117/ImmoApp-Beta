"""
Audit log repository functions.
"""

from __future__ import annotations

from core.matcher.ports.db import DbSession
from core.models import AuditLog
from core.models_cast import as_int, row_at


def fetch_audit_logs(
    session: DbSession,
    limit: int = 200,
    offset: int = 0,
    table_name: str | None = None,
    record_id: str | None = None,
    actor: str | None = None,
    action: str | None = None,
    start_ts: str | None = None,
    end_ts: str | None = None,
) -> list[AuditLog]:
    """Fetch audit logs with optional filters. RLS filters by agency_id."""
    sql = "SELECT * FROM audit_logs"
    conditions: list[str] = []
    params: list[object] = []

    if table_name:
        conditions.append("table_name = %s")
        params.append(table_name)
    if record_id:
        conditions.append("record_id = %s")
        params.append(record_id)
    if actor:
        conditions.append("actor = %s")
        params.append(actor)
    if action:
        conditions.append("action = %s")
        params.append(action)
    if start_ts:
        conditions.append("ts >= %s")
        params.append(start_ts)
    if end_ts:
        conditions.append("ts <= %s")
        params.append(end_ts)

    if conditions:
        sql += " WHERE " + " AND ".join(conditions)

    sql += " ORDER BY ts DESC, id DESC LIMIT %s OFFSET %s"
    params.extend([limit, offset])

    rows = session.execute(sql, params).fetchall()
    return [AuditLog.from_row(row) for row in rows]


def count_audit_logs(
    session: DbSession,
    table_name: str | None = None,
    record_id: str | None = None,
    actor: str | None = None,
    action: str | None = None,
    start_ts: str | None = None,
    end_ts: str | None = None,
) -> int:
    """Count audit logs with optional filters. RLS filters by agency_id."""
    sql = "SELECT COUNT(*) FROM audit_logs"
    conditions: list[str] = []
    params: list[object] = []

    if table_name:
        conditions.append("table_name = %s")
        params.append(table_name)
    if record_id:
        conditions.append("record_id = %s")
        params.append(record_id)
    if actor:
        conditions.append("actor = %s")
        params.append(actor)
    if action:
        conditions.append("action = %s")
        params.append(action)
    if start_ts:
        conditions.append("ts >= %s")
        params.append(start_ts)
    if end_ts:
        conditions.append("ts <= %s")
        params.append(end_ts)

    if conditions:
        sql += " WHERE " + " AND ".join(conditions)

    row = session.execute(sql, params).fetchone()
    return as_int(row_at(row, 0)) if row else 0


def purge_audit_logs(session: DbSession) -> int:
    """Delete all audit logs for current agency (RLS scoped) and return count."""
    session.execute("DELETE FROM audit_logs")
    return int(session.rowcount)


def purge_old_audit_logs(session: DbSession, retention_days: int = 90) -> int:
    """Delete audit logs older than retention_days. RLS scoped to current agency."""
    session.execute(
        "DELETE FROM audit_logs WHERE ts < NOW() - INTERVAL '%s days'",
        (retention_days,),
    )
    return int(session.rowcount)
