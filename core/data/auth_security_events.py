"""
Repository helpers for auth security events.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from core.matcher.ports.db import DbSession


def insert_auth_event(
    session: DbSession,
    *,
    event_type: str,
    outcome: str,
    agency_id: int | None = None,
    user_id: int | None = None,
    identifier: str | None = None,
    reason_code: str | None = None,
    source_ip: str | None = None,
    user_agent: str | None = None,
    request_id: str | None = None,
    details: Mapping[str, Any] | None = None,
) -> None:
    session.execute(
        """
        INSERT INTO auth_security_events (
            agency_id,
            user_id,
            event_type,
            outcome,
            identifier,
            reason_code,
            source_ip,
            user_agent,
            request_id,
            details
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
        """,
        (
            agency_id,
            user_id,
            event_type,
            outcome,
            identifier,
            reason_code,
            source_ip,
            user_agent,
            request_id,
            _json_text(details),
        ),
    )


def fetch_auth_events(
    session: DbSession,
    *,
    limit: int = 200,
    offset: int = 0,
    event_type: str | None = None,
    outcome: str | None = None,
    user_id: int | None = None,
    identifier: str | None = None,
    source_ip: str | None = None,
    start_ts: str | None = None,
    end_ts: str | None = None,
) -> list[dict[str, Any]]:
    sql = "SELECT * FROM auth_security_events"
    conditions: list[str] = []
    params: list[object] = []

    if event_type:
        conditions.append("event_type = %s")
        params.append(event_type)
    if outcome:
        conditions.append("outcome = %s")
        params.append(outcome)
    if user_id is not None:
        conditions.append("user_id = %s")
        params.append(user_id)
    if identifier:
        conditions.append("identifier = %s")
        params.append(identifier)
    if source_ip:
        conditions.append("source_ip = %s")
        params.append(source_ip)
    if start_ts:
        conditions.append("created_at >= %s")
        params.append(start_ts)
    if end_ts:
        conditions.append("created_at <= %s")
        params.append(end_ts)

    if conditions:
        sql += " WHERE " + " AND ".join(conditions)

    sql += " ORDER BY created_at DESC, id DESC LIMIT %s OFFSET %s"
    params.extend([limit, offset])
    rows = session.execute(sql, params).fetchall()
    return [dict(row) for row in rows]


def count_auth_events(
    session: DbSession,
    *,
    event_type: str | None = None,
    outcome: str | None = None,
    user_id: int | None = None,
    identifier: str | None = None,
    source_ip: str | None = None,
    start_ts: str | None = None,
    end_ts: str | None = None,
) -> int:
    sql = "SELECT COUNT(*) AS count FROM auth_security_events"
    conditions: list[str] = []
    params: list[object] = []

    if event_type:
        conditions.append("event_type = %s")
        params.append(event_type)
    if outcome:
        conditions.append("outcome = %s")
        params.append(outcome)
    if user_id is not None:
        conditions.append("user_id = %s")
        params.append(user_id)
    if identifier:
        conditions.append("identifier = %s")
        params.append(identifier)
    if source_ip:
        conditions.append("source_ip = %s")
        params.append(source_ip)
    if start_ts:
        conditions.append("created_at >= %s")
        params.append(start_ts)
    if end_ts:
        conditions.append("created_at <= %s")
        params.append(end_ts)

    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    row = session.execute(sql, params).fetchone()
    value = (row or {}).get("count")
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return 0
    return 0


def purge_old_auth_events(session: DbSession, retention_days: int = 90) -> int:
    session.execute(
        "DELETE FROM auth_security_events WHERE created_at < NOW() - (%s || ' days')::interval",
        (retention_days,),
    )
    return int(session.rowcount)


def _json_text(payload: Mapping[str, Any] | None) -> str:
    if not payload:
        return "{}"
    import json

    return json.dumps(payload, separators=(",", ":"), sort_keys=True)
