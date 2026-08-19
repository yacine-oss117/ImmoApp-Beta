"""
Notification query helpers (visibility + list/count).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from core.data.surface_cache_generation import (
    NOTIFICATIONS_ACTOR_SURFACE,
    NOTIFICATIONS_AGENCY_SURFACE,
    NOTIFICATIONS_GLOBAL_SURFACE,
    NOTIFICATIONS_OWNER_SURFACE,
    NOTIFICATIONS_ROLE_SURFACE,
    ScopeRequest,
    actor_scope_key,
    agency_scope_key,
    global_scope_key,
    owner_scope_key,
    read_generations,
    role_scope_key,
)
from server.pg.uow import get_uow, use_security_context


def _notification_list_include_data() -> bool:
    import os

    return os.environ.get("IMMOAPP_NOTIFICATION_LIST_INCLUDE_DATA", "1").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _notification_generation_requests(
    *,
    user_id: int | None,
    role: str | None,
    is_owner: bool,
    is_superuser: bool,
    agency_id: int | None,
) -> list[ScopeRequest]:
    requests: list[ScopeRequest] = []
    resolved_agency_id = int(agency_id) if isinstance(agency_id, int) and agency_id > 0 else None
    if resolved_agency_id is not None:
        requests.append(
            (
                NOTIFICATIONS_AGENCY_SURFACE,
                agency_scope_key(resolved_agency_id),
                resolved_agency_id,
            )
        )
        normalized_role = str(role or "").strip().lower()
        if normalized_role:
            requests.append(
                (
                    NOTIFICATIONS_ROLE_SURFACE,
                    role_scope_key(agency_id=resolved_agency_id, role=normalized_role),
                    resolved_agency_id,
                )
            )
        if is_owner:
            requests.append(
                (
                    NOTIFICATIONS_OWNER_SURFACE,
                    owner_scope_key(agency_id=resolved_agency_id),
                    resolved_agency_id,
                )
            )
        if isinstance(user_id, int) and user_id > 0:
            requests.append(
                (
                    NOTIFICATIONS_ACTOR_SURFACE,
                    actor_scope_key(user_id),
                    resolved_agency_id,
                )
            )
    if is_superuser:
        requests.append(
            (
                NOTIFICATIONS_GLOBAL_SURFACE,
                global_scope_key(),
                None,
            )
        )
    return requests


def get_notifications_scope_generations(
    *,
    user_id: int | None,
    role: str | None,
    is_owner: bool,
    is_superuser: bool,
    agency_id: int | None,
) -> tuple[tuple[str, str, int], ...]:
    requests = _notification_generation_requests(
        user_id=user_id,
        role=role,
        is_owner=is_owner,
        is_superuser=is_superuser,
        agency_id=agency_id,
    )
    if not requests:
        return ()
    with use_security_context(
        agency_id=int(agency_id) if isinstance(agency_id, int) and agency_id > 0 else None,
        is_superuser=is_superuser,
    ):
        with get_uow().session(is_superuser=is_superuser) as session:
            generations = read_generations(session, requests=requests)
    result: list[tuple[str, str, int]] = []
    for surface, scope_key, _scope_agency_id in requests:
        result.append((surface, scope_key, int(generations.get((surface, scope_key), 1))))
    return tuple(result)


def _visibility_filters(
    *,
    user_id: int | None,
    role: str | None,
    is_owner: bool,
    is_superuser: bool,
    prefix: str = "",
) -> tuple[list[str], list[object]]:
    filters: list[str] = []
    params: list[object] = []

    if user_id is not None:
        filters.append(f"({prefix}scope = 'user' AND {prefix}user_id = %s)")
        params.append(user_id)

    # Agency scope is now implicitly isolated by RLS, but we still check the 'scope' tag
    filters.append(f"({prefix}scope = 'agency')")

    if role:
        filters.append(f"({prefix}scope = 'role' AND {prefix}role = %s)")
        params.append(role)

    if is_owner:
        filters.append(f"({prefix}scope = 'owner')")

    if is_superuser:
        filters.append(f"({prefix}scope = 'global')")

    return filters, params


def _fetch_notification_page(
    session: Any,
    *,
    user_id: int | None,
    role: str | None,
    is_owner: bool,
    is_superuser: bool,
    limit: int,
    cursor: int | None,
) -> list[dict[str, object]]:
    filters, params = _visibility_filters(
        user_id=user_id,
        role=role,
        is_owner=is_owner,
        is_superuser=is_superuser,
        prefix="n.",
    )
    if not filters:
        return []

    where_sql = " OR ".join(filters)
    data_sql = "n.data" if _notification_list_include_data() else "'{}'::jsonb AS data"
    base_select = (
        "SELECT n.id, n.scope, n.role, n.user_id, n.agency_id, "
        f"n.type, n.title, n.body, {data_sql}, n.created_at "
    )

    cursor_filter_sql = ""
    cursor_params: list[object] = []
    if isinstance(cursor, int) and cursor > 0:
        cursor_filter_sql = " AND n.id < %s"
        cursor_params.append(int(cursor))

    if user_id is None:
        list_sql = (
            base_select
            + ", FALSE AS is_read, NULL AS read_at "
            + "FROM notifications n "
            + f"WHERE {where_sql} "
            + cursor_filter_sql
            + " ORDER BY n.id DESC LIMIT %s"
        )
        list_params = [*params, *cursor_params, limit]
    else:
        list_sql = (
            base_select
            + ", (nr.notification_id IS NOT NULL) AS is_read, nr.read_at AS read_at "
            + "FROM notifications n "
            + "LEFT JOIN notification_reads nr "
            + "ON nr.notification_id = n.id AND nr.user_id = %s "
            + f"WHERE {where_sql} "
            + cursor_filter_sql
            + " ORDER BY n.id DESC LIMIT %s"
        )
        list_params = [user_id, *params, *cursor_params, limit]
    return [dict(row) for row in session.execute(list_sql, list_params).fetchall()]


def _fetch_notification_rows(
    session: Any,
    *,
    user_id: int | None,
    role: str | None,
    is_owner: bool,
    is_superuser: bool,
    limit: int,
    offset: int,
    cursor: int | None,
) -> list[dict[str, object]]:
    if isinstance(cursor, int) and cursor > 0:
        return _fetch_notification_page(
            session,
            user_id=user_id,
            role=role,
            is_owner=is_owner,
            is_superuser=is_superuser,
            limit=limit,
            cursor=cursor,
        )
    if limit <= 0 or offset <= 0:
        return _fetch_notification_page(
            session,
            user_id=user_id,
            role=role,
            is_owner=is_owner,
            is_superuser=is_superuser,
            limit=limit,
            cursor=None,
        )

    current_offset = 0
    current_cursor: int | None = None
    while current_offset < offset:
        step = min(limit, offset - current_offset)
        page = _fetch_notification_page(
            session,
            user_id=user_id,
            role=role,
            is_owner=is_owner,
            is_superuser=is_superuser,
            limit=step,
            cursor=current_cursor,
        )
        current_offset += len(page)
        if len(page) < step:
            return []
        last_id = page[-1].get("id") if page else None
        current_cursor = int(last_id) if isinstance(last_id, int) and last_id > 0 else None
        if current_cursor is None:
            return []

    return _fetch_notification_page(
        session,
        user_id=user_id,
        role=role,
        is_owner=is_owner,
        is_superuser=is_superuser,
        limit=limit,
        cursor=current_cursor,
    )


def _infer_notification_total(
    *,
    limit: int,
    offset: int,
    cursor: int | None,
    item_count: int,
) -> int | None:
    if cursor is not None or limit <= 0:
        return None
    if item_count < limit:
        return max(0, int(offset)) + int(item_count)
    return None


def list_notifications(
    *,
    user_id: int | None,
    role: str | None,
    is_owner: bool,
    is_superuser: bool,
    limit: int = 200,
    offset: int = 0,
    cursor: int | None = None,
) -> list[dict[str, object]]:
    """Return notifications visible to the current user."""
    items, _total = list_notifications_with_total(
        user_id=user_id,
        role=role,
        is_owner=is_owner,
        is_superuser=is_superuser,
        limit=limit,
        offset=offset,
        cursor=cursor,
    )
    return items


def list_notifications_with_total(
    *,
    user_id: int | None,
    role: str | None,
    is_owner: bool,
    is_superuser: bool,
    limit: int = 200,
    offset: int = 0,
    cursor: int | None = None,
) -> tuple[list[dict[str, object]], int]:
    """Return visible notifications and total count."""
    filters, params = _visibility_filters(
        user_id=user_id,
        role=role,
        is_owner=is_owner,
        is_superuser=is_superuser,
        prefix="n.",
    )
    if not filters:
        return [], 0

    where_sql = " OR ".join(filters)
    count_sql = f"SELECT COUNT(*) AS total FROM notifications n WHERE {where_sql}"
    count_params = params

    with get_uow().session(is_superuser=is_superuser) as session:
        rows = _fetch_notification_rows(
            session,
            user_id=user_id,
            role=role,
            is_owner=is_owner,
            is_superuser=is_superuser,
            limit=limit,
            offset=offset,
            cursor=cursor,
        )
        inferred_total = _infer_notification_total(
            limit=limit,
            offset=offset,
            cursor=cursor,
            item_count=len(rows),
        )
        if inferred_total is not None:
            total = int(inferred_total)
        else:
            total_row = session.execute(count_sql, count_params).fetchone()
            total_raw = total_row.get("total", 0) if total_row else 0
            total = int(total_raw) if isinstance(total_raw, int) else 0
    return rows, total


def count_notifications(
    *,
    user_id: int | None,
    role: str | None,
    is_owner: bool,
    is_superuser: bool,
) -> int:
    """Return total notifications visible to the user."""
    filters, params = _visibility_filters(
        user_id=user_id,
        role=role,
        is_owner=is_owner,
        is_superuser=is_superuser,
        prefix="",
    )
    if not filters:
        return 0
    where_sql = " OR ".join(filters)
    sql = f"SELECT COUNT(*) AS total FROM notifications WHERE {where_sql}"
    with get_uow().session(is_superuser=is_superuser) as session:
        row = session.execute(sql, params).fetchone()
    if not row:
        return 0
    total = row.get("total", 0)
    return int(total) if isinstance(total, int) else 0


def count_unread_notifications(
    *,
    user_id: int | None,
    role: str | None,
    is_owner: bool,
    is_superuser: bool,
) -> int:
    """Return unread notification count for the user."""
    if user_id is None:
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
    sql = (
        "SELECT COUNT(*) AS total "
        "FROM notifications n "
        "LEFT JOIN notification_reads nr "
        "ON nr.notification_id = n.id AND nr.user_id = %s "
        f"WHERE {where_sql} AND nr.notification_id IS NULL"
    )
    params = [user_id, *params]
    with get_uow().session(is_superuser=is_superuser) as session:
        row = session.execute(sql, params).fetchone()
    if not row:
        return 0
    total = row.get("total", 0)
    return int(total) if isinstance(total, int) else 0


def _rows_to_items(rows: Iterable[dict[str, object]]) -> list[dict[str, object]]:
    return [dict(row) for row in rows]


def list_notification_items(**kwargs: Any) -> list[dict[str, object]]:
    """Wrapper that returns plain dicts."""
    return _rows_to_items(list_notifications(**kwargs))


def list_notification_items_with_total(**kwargs: Any) -> tuple[list[dict[str, object]], int]:
    """Wrapper that returns plain dicts plus total count."""
    rows, total = list_notifications_with_total(**kwargs)
    return _rows_to_items(rows), int(total)


__all__ = [
    "count_notifications",
    "count_unread_notifications",
    "get_notifications_scope_generations",
    "list_notification_items",
    "list_notification_items_with_total",
    "list_notifications",
    "list_notifications_with_total",
]
