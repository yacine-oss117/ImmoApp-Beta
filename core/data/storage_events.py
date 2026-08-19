"""
Storage event persistence (append-only audit trail).
"""

from __future__ import annotations

from typing import Any

from psycopg.types.json import Jsonb

from server.pg.uow import PgSession


def insert_storage_event(
    session: PgSession,
    *,
    storage_id: str,
    event_type: str,
    user_id: int | None,
    role: str | None,
    created_ip: str | None,
    details: dict[str, Any] | None = None,
) -> None:
    payload = details if details is not None else {}
    session.execute(
        """
        INSERT INTO storage_events (
            storage_id,
            event_type,
            user_id,
            role,
            created_ip,
            details,
            created_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
        """,
        (storage_id, event_type, user_id, role, created_ip, Jsonb(payload)),
    )


__all__ = ["insert_storage_event"]
