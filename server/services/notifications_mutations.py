"""
Notification mutation helpers (insert/mark/clear/purge).
"""

from __future__ import annotations

import json
from collections.abc import Iterable

from django.db import connection
from psycopg.types.json import Jsonb

from core.data.surface_cache_generation import (
    NOTIFICATIONS_ACTOR_SURFACE,
    NOTIFICATIONS_AGENCY_SURFACE,
    NOTIFICATIONS_GLOBAL_SURFACE,
    NOTIFICATIONS_OWNER_SURFACE,
    NOTIFICATIONS_ROLE_SURFACE,
    actor_scope_key,
    agency_scope_key,
    bump_generation,
    global_scope_key,
    owner_scope_key,
    role_scope_key,
)
from server.pg.uow import (
    PgSession,
    get_current_actor_email,
    get_current_actor_id,
    get_current_actor_role,
    get_current_agency_id,
    get_uow,
    is_current_actor_owner,
    is_current_user_superuser,
)
from server.services.json_safe import json_safe_value
from server.services.notifications_queries import _visibility_filters
from server.services.surface_cache_generations import bump_generation_in_atomic


def _resolved_agency_id(*, agency_id: int | None) -> int | None:
    if isinstance(agency_id, int) and agency_id > 0:
        return int(agency_id)
    current_agency_id = get_current_agency_id()
    if isinstance(current_agency_id, int) and current_agency_id > 0:
        return int(current_agency_id)
    return None


def _normalized_notification_payload(data: dict[str, object] | None) -> dict[str, object]:
    safe_payload = json_safe_value(data if data is not None else {})
    return dict(safe_payload) if isinstance(safe_payload, dict) else {}


def _notification_scope_request(
    *,
    scope: object,
    agency_id: int | None,
    user_id: int | None,
    role: str | None,
) -> tuple[str, str, int | None] | None:
    normalized_scope = str(scope or "").strip().lower()
    if normalized_scope == "global":
        return NOTIFICATIONS_GLOBAL_SURFACE, global_scope_key(), None
    if not isinstance(agency_id, int) or agency_id <= 0:
        return None
    if normalized_scope == "agency":
        return NOTIFICATIONS_AGENCY_SURFACE, agency_scope_key(agency_id), agency_id
    if normalized_scope == "owner":
        return NOTIFICATIONS_OWNER_SURFACE, owner_scope_key(agency_id=agency_id), agency_id
    if normalized_scope == "role":
        normalized_role = str(role or "").strip().lower()
        if not normalized_role:
            return None
        return (
            NOTIFICATIONS_ROLE_SURFACE,
            role_scope_key(agency_id=agency_id, role=normalized_role),
            agency_id,
        )
    if normalized_scope == "user":
        if not isinstance(user_id, int) or user_id <= 0:
            return None
        return NOTIFICATIONS_ACTOR_SURFACE, actor_scope_key(user_id), agency_id
    return None


def _coerce_scope_int(value: object) -> int | None:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float, str, bytes, bytearray)):
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
    return None


def _bump_notification_scope(
    session: PgSession,
    *,
    scope: object,
    agency_id: int | None,
    user_id: int | None,
    role: str | None,
) -> None:
    request = _notification_scope_request(
        scope=scope,
        agency_id=agency_id,
        user_id=user_id,
        role=role,
    )
    if request is None:
        return
    surface, scope_key, scope_agency_id = request
    bump_generation(
        session,
        surface=surface,
        scope_key=scope_key,
        agency_id=scope_agency_id,
    )


def _bump_notification_scope_in_atomic(
    *,
    scope: object,
    agency_id: int | None,
    user_id: int | None,
    role: str | None,
) -> None:
    request = _notification_scope_request(
        scope=scope,
        agency_id=agency_id,
        user_id=user_id,
        role=role,
    )
    if request is None:
        return
    surface, scope_key, scope_agency_id = request
    bump_generation_in_atomic(
        surface=surface,
        scope_key=scope_key,
        agency_id=scope_agency_id,
    )


def _bump_notification_scopes_from_rows(
    session: PgSession,
    rows: Iterable[dict[str, object]],
    *,
    fallback_agency_id: int | None = None,
) -> None:
    seen: set[tuple[str, str]] = set()
    for row in rows:
        row_agency_id = _coerce_scope_int(row.get("agency_id"))
        row_user_id = _coerce_scope_int(row.get("user_id"))
        request = _notification_scope_request(
            scope=row.get("scope"),
            agency_id=row_agency_id if row_agency_id is not None else fallback_agency_id,
            user_id=row_user_id,
            role=str(row.get("role") or "") or None,
        )
        if request is None:
            continue
        surface, scope_key, scope_agency_id = request
        if (surface, scope_key) in seen:
            continue
        seen.add((surface, scope_key))
        bump_generation(
            session,
            surface=surface,
            scope_key=scope_key,
            agency_id=scope_agency_id,
        )


def _apply_atomic_notification_context(
    *,
    resolved_agency_id: int | None,
    actor: str | None,
    is_superuser: bool,
) -> None:
    effective_is_superuser = bool(is_superuser or is_current_user_superuser())
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                set_config('app.current_agency_id', %s, true),
                set_config('app.is_superuser', %s, true),
                set_config('app.audit_actor', %s, true),
                set_config('app.actor_id', %s, true),
                set_config('app.actor_email', %s, true),
                set_config('app.actor_role', %s, true),
                set_config('app.actor_is_owner', %s, true)
            """,
            (
                str(resolved_agency_id or ""),
                "true" if effective_is_superuser else "false",
                str(actor or ""),
                str(get_current_actor_id() or ""),
                str(get_current_actor_email() or ""),
                str(get_current_actor_role() or ""),
                "true" if is_current_actor_owner() else "false",
            ),
        )


def insert_notification(
    *,
    agency_id: int | None = None,
    scope: str,
    event_type: str,
    title: str,
    body: str,
    user_id: int | None = None,
    role: str | None = None,
    data: dict[str, object] | None = None,
    actor: str | None = None,
    is_superuser: bool = False,
) -> int | None:
    """Persist a notification in the database and return its id."""
    payload = _normalized_notification_payload(data)
    resolved_agency_id = _resolved_agency_id(agency_id=agency_id)
    with get_uow().transaction(actor=actor, is_superuser=is_superuser) as session:
        row = session.execute(
            """
            INSERT INTO notifications (
                agency_id, scope, type, title, body, data, user_id, role, created_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
            RETURNING id
            """,
            (
                resolved_agency_id,
                scope,
                event_type,
                title,
                body,
                Jsonb(payload),
                user_id,
                role,
            ),
        ).fetchone()
        _bump_notification_scope(
            session,
            scope=scope,
            agency_id=resolved_agency_id,
            user_id=user_id,
            role=role,
        )
        if not row:
            return None
        notification_id = row.get("id")
        return int(notification_id) if isinstance(notification_id, int) else None


def insert_notification_in_atomic(
    *,
    agency_id: int | None,
    scope: str,
    event_type: str,
    title: str,
    body: str,
    user_id: int | None = None,
    role: str | None = None,
    data: dict[str, object] | None = None,
    actor: str | None = None,
    is_superuser: bool = False,
) -> int | None:
    """Persist a notification on the current Django DB transaction."""
    payload = _normalized_notification_payload(data)
    resolved_agency_id = _resolved_agency_id(agency_id=agency_id)
    _apply_atomic_notification_context(
        resolved_agency_id=resolved_agency_id,
        actor=actor,
        is_superuser=is_superuser,
    )
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO public.notifications (
                agency_id, scope, type, title, body, data, user_id, role, created_at
            )
            VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s, CURRENT_TIMESTAMP)
            RETURNING id
            """,
            (
                resolved_agency_id,
                scope,
                event_type,
                title,
                body,
                json.dumps(payload),
                user_id,
                role,
            ),
        )
        row = cursor.fetchone()
    _bump_notification_scope_in_atomic(
        scope=scope,
        agency_id=resolved_agency_id,
        user_id=user_id,
        role=role,
    )
    if not row:
        return None
    notification_id = row[0]
    return int(notification_id) if isinstance(notification_id, int) else None


def clear_visible_notifications(
    *,
    agency_id: int | None,
    user_id: int | None,
    role: str | None,
    is_owner: bool,
    is_superuser: bool,
) -> int:
    """Delete notifications that the user is allowed to clear."""
    filters: list[str] = []
    params: list[object] = []

    if user_id is not None:
        filters.append("(scope = 'user' AND user_id = %s)")
        params.append(user_id)

    if role:
        filters.append("(scope = 'role' AND role = %s)")
        params.append(role)

    if is_owner:
        filters.append("(scope = 'owner')")
        filters.append("(scope = 'agency')")

    if is_superuser:
        filters.append("(scope = 'global')")

    if not filters:
        return 0

    where_sql = " OR ".join(filters)
    with get_uow().transaction(is_superuser=is_superuser) as session:
        deleted_rows = session.execute(
            f"""
            DELETE FROM notifications
            WHERE {where_sql}
            RETURNING scope, agency_id, role, user_id
            """,
            params,
        ).fetchall()
        _bump_notification_scopes_from_rows(
            session,
            deleted_rows,
            fallback_agency_id=agency_id,
        )
        return len(deleted_rows)


def mark_notifications_read(
    *,
    agency_id: int | None,
    user_id: int | None,
    role: str | None,
    is_owner: bool,
    is_superuser: bool,
    notification_ids: Iterable[int] | None = None,
    mark_all: bool = False,
) -> int:
    """Mark notifications as read for the current user."""
    if user_id is None:
        return 0
    ids = [int(item) for item in (notification_ids or []) if isinstance(item, (int, float, str))]
    if not mark_all and not ids:
        return 0

    filters, params = _visibility_filters(
        user_id=user_id,
        role=role,
        is_owner=is_owner,
        is_superuser=is_superuser,
        prefix="n.",
    )
    if not filters:
        return 0
    where_sql = " OR ".join(filters)
    extra = ""
    if not mark_all:
        extra = " AND n.id = ANY(%s)"
        params.append(ids)

    sql = (
        "INSERT INTO notification_reads (notification_id, user_id, read_at) "
        "SELECT n.id, %s, CURRENT_TIMESTAMP "
        "FROM notifications n "
        f"WHERE ({where_sql}){extra} "
        "ON CONFLICT (notification_id, user_id) DO NOTHING"
    )
    params = [user_id, *params]
    with get_uow().transaction(is_superuser=is_superuser) as session:
        session.execute(sql, params)
        _bump_notification_scope(
            session,
            scope="user",
            agency_id=agency_id,
            user_id=user_id,
            role=None,
        )
        return session.rowcount


def mark_notifications_unread(
    *,
    agency_id: int | None,
    user_id: int | None,
    role: str | None,
    is_owner: bool,
    is_superuser: bool,
    notification_ids: Iterable[int] | None = None,
    mark_all: bool = False,
) -> int:
    """Mark notifications as unread for the current user."""
    if user_id is None:
        return 0
    ids = [int(item) for item in (notification_ids or []) if isinstance(item, (int, float, str))]
    if not mark_all and not ids:
        return 0

    filters, params = _visibility_filters(
        user_id=user_id,
        role=role,
        is_owner=is_owner,
        is_superuser=is_superuser,
        prefix="n.",
    )
    if not filters:
        return 0
    where_sql = " OR ".join(filters)
    extra = ""
    if not mark_all:
        extra = " AND n.id = ANY(%s)"
        params.append(ids)

    sql = (
        "DELETE FROM notification_reads nr "
        "USING notifications n "
        "WHERE nr.notification_id = n.id "
        "AND nr.user_id = %s "
        f"AND ({where_sql}){extra}"
    )
    params = [user_id, *params]
    with get_uow().transaction(is_superuser=is_superuser) as session:
        session.execute(sql, params)
        _bump_notification_scope(
            session,
            scope="user",
            agency_id=agency_id,
            user_id=user_id,
            role=None,
        )
        return session.rowcount


def purge_notifications_older_than(
    *,
    days: int = 60,
    session: PgSession | None = None,
) -> int:
    """Delete notifications older than the given number of days."""
    if days <= 0:
        return 0
    sql = """
        DELETE FROM notifications
        WHERE created_at < (CURRENT_TIMESTAMP - (%s || ' days')::interval)
        RETURNING scope, agency_id, role, user_id
    """
    params = (days,)

    if session is not None:
        deleted_rows = session.execute(sql, params).fetchall()
        _bump_notification_scopes_from_rows(session, deleted_rows)
        return len(deleted_rows)

    with get_uow().transaction(is_superuser=True) as session2:
        deleted_rows = session2.execute(sql, params).fetchall()
        _bump_notification_scopes_from_rows(session2, deleted_rows)
        return len(deleted_rows)


__all__ = [
    "clear_visible_notifications",
    "insert_notification",
    "insert_notification_in_atomic",
    "mark_notifications_read",
    "mark_notifications_unread",
    "purge_notifications_older_than",
]
