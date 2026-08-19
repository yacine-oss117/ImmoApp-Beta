"""
Write helpers for the match count cache.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

from core.config.match_cache import (
    CACHE_BATCH_THRESHOLD,
    CACHE_CHUNK_SIZE,
    CACHE_DIRTY_MARK_CHUNK_SIZE,
    CACHE_LOCK_TIMEOUT_MS,
    CACHE_STATEMENT_TIMEOUT_MS,
)
from core.data import lookup_tables
from core.data.match_cache_utils import chunk_ids
from core.matcher.ports.db import DbSession
from core.utils.row_casts import row_int, row_optional_int, row_str
from core.utils.time import utc_now_iso

logger = logging.getLogger(__name__)

_UPSERT_SQL_COMPOSITE = """
    INSERT INTO match_counts_cache
    (client_id, agency_id, count, visibility, owner_user_id, computed_at, is_dirty)
    VALUES (%s, %s, %s, %s, %s, %s, 0)
    ON CONFLICT (agency_id, client_id) DO UPDATE
    SET count = EXCLUDED.count,
        visibility = EXCLUDED.visibility,
        owner_user_id = EXCLUDED.owner_user_id,
        computed_at = EXCLUDED.computed_at,
        is_dirty = EXCLUDED.is_dirty
"""

_UPSERT_SQL_LEGACY = """
    INSERT INTO match_counts_cache
    (client_id, agency_id, count, visibility, owner_user_id, computed_at, is_dirty)
    VALUES (%s, %s, %s, %s, %s, %s, 0)
    ON CONFLICT (client_id) DO UPDATE
    SET agency_id = EXCLUDED.agency_id,
        count = EXCLUDED.count,
        visibility = EXCLUDED.visibility,
        owner_user_id = EXCLUDED.owner_user_id,
        computed_at = EXCLUDED.computed_at,
        is_dirty = EXCLUDED.is_dirty
"""


def _set_lock_timeout(session: DbSession) -> None:
    session.execute(f"SET LOCAL lock_timeout = '{CACHE_LOCK_TIMEOUT_MS}ms'")
    session.execute(f"SET LOCAL statement_timeout = '{CACHE_STATEMENT_TIMEOUT_MS}ms'")


def _is_missing_conflict_target(exc: Exception) -> bool:
    sqlstate = getattr(exc, "sqlstate", None)
    if sqlstate == "42P10":
        return True
    return (
        "no unique or exclusion constraint matching the on conflict specification"
        in str(exc).lower()
    )


def _upsert_count_rows(session: DbSession, rows: list[tuple[object, ...]]) -> None:
    if not rows:
        return
    try:
        session.executemany(_UPSERT_SQL_COMPOSITE, rows)
    except Exception as exc:
        if not _is_missing_conflict_target(exc):
            raise
        session.executemany(_UPSERT_SQL_LEGACY, rows)


def _mark_rows_dirty(session: DbSession, client_ids: list[int]) -> None:
    if not client_ids:
        return
    placeholders = ",".join("%s" for _ in client_ids)
    session.execute(
        f"UPDATE match_counts_cache SET is_dirty = 1 WHERE client_id IN ({placeholders})",
        tuple(client_ids),
    )


def store_count(session: DbSession, client_id: int, count: int) -> None:
    """Store a single count (clean) with security shadow fields only."""
    _set_lock_timeout(session)
    client_row = session.execute(
        """
        SELECT agency_id, visibility, owner_user_id, status, deleted_at
        FROM clients
        WHERE id = %s
        FOR UPDATE
        """,
        [client_id],
    ).fetchone()
    if not client_row:
        delete_client_cache(session, client_id)
        return
    status = row_str(client_row, "status", default="active")
    if status != "active" or client_row.get("deleted_at") is not None:
        delete_client_cache(session, client_id)
        return
    agency_id_value = row_optional_int(client_row, "agency_id")
    if agency_id_value is None:
        delete_client_cache(session, client_id)
        return
    visibility = row_str(client_row, "visibility", default=None)
    owner_user_id = row_optional_int(client_row, "owner_user_id")
    now = utc_now_iso()
    _upsert_count_rows(
        session,
        [(client_id, agency_id_value, count, visibility, owner_user_id, now)],
    )


def store_counts_batch(session: DbSession, counts: dict[int, int]) -> None:
    """Store multiple counts with deterministic lock ordering."""
    if not counts:
        return
    normalized_ids = sorted({int(client_id) for client_id in counts if int(client_id) > 0})
    if not normalized_ids:
        return
    _set_lock_timeout(session)

    now = utc_now_iso()
    client_info: dict[int, tuple[int, str | None, int | None]] = {}

    for chunk in chunk_ids(normalized_ids):
        placeholders = ",".join("%s" for _ in chunk)
        rows = session.execute(
            f"""
            SELECT id, visibility, owner_user_id, agency_id
            FROM clients
            WHERE status = 'active'
              AND deleted_at IS NULL
              AND id IN ({placeholders})
            ORDER BY id
            FOR UPDATE
            """,
            list(chunk),
        ).fetchall()
        for row in rows:
            client_id_value = row_int(row, "id")
            agency_id_value = row_optional_int(row, "agency_id")
            if agency_id_value is None:
                continue
            client_info[client_id_value] = (
                agency_id_value,
                row_str(row, "visibility", default=None),
                row_optional_int(row, "owner_user_id"),
            )

    items: list[tuple[object, ...]] = []
    for client_id in normalized_ids:
        metadata = client_info.get(client_id)
        if not metadata:
            continue
        agency_id_value, visibility, owner_user_id = metadata
        items.append(
            (
                client_id,
                agency_id_value,
                int(counts.get(client_id, 0)),
                visibility,
                owner_user_id,
                now,
            )
        )
    if not items:
        return

    if len(items) < CACHE_BATCH_THRESHOLD:
        _upsert_count_rows(session, items)
        return

    for i in range(0, len(items), CACHE_CHUNK_SIZE):
        _upsert_count_rows(session, items[i : i + CACHE_CHUNK_SIZE])


def mark_client_dirty(session: DbSession, client_id: int) -> None:
    """Mark a single client as needing recomputation."""
    _set_lock_timeout(session)
    session.execute("UPDATE match_counts_cache SET is_dirty = 1 WHERE client_id = %s", (client_id,))


def mark_clients_for_demande_ids_dirty(session: DbSession, demande_ids: Iterable[int]) -> None:
    """Mark clients owning the given active demandes as needing recomputation."""
    normalized_ids = sorted({int(demande_id) for demande_id in demande_ids if int(demande_id) > 0})
    if not normalized_ids:
        return
    _set_lock_timeout(session)
    for chunk in chunk_ids(normalized_ids):
        placeholders = ",".join("%s" for _ in chunk)
        rows = session.execute(
            f"""
            SELECT DISTINCT d.client_id
            FROM demandes d
            JOIN clients c ON c.id = d.client_id
            WHERE d.id IN ({placeholders})
              AND d.deleted_at IS NULL
              AND c.deleted_at IS NULL
              AND c.status = 'active'
            ORDER BY d.client_id
            """,
            tuple(chunk),
        ).fetchall()
        _mark_rows_dirty(session, [row_int(row, "client_id") for row in rows])


def mark_clients_in_wilaya_dirty(
    session: DbSession,
    wilaya_id: int | None = None,
    *,
    wilaya: str | None = None,
) -> None:
    """Mark all clients with demandes in a wilaya as dirty."""
    _set_lock_timeout(session)
    resolved_id: int | None = None
    if isinstance(wilaya_id, int):
        resolved_id = wilaya_id
    elif isinstance(wilaya_id, str):
        resolved_id = lookup_tables.get_wilaya_id(session, wilaya_id)
    if resolved_id is None and wilaya:
        resolved_id = lookup_tables.get_wilaya_id(session, wilaya)
    if resolved_id is None:
        return

    conditions = [
        "d.deleted_at IS NULL",
        "c.deleted_at IS NULL",
        (
            "(d.wilaya_id = %s OR ("
            "d.wilaya_id IS NULL "
            "AND NOT EXISTS (SELECT 1 FROM demande_locations WHERE demande_id = d.id)"
            "))"
        ),
        "c.status = 'active'",
    ]
    params: list[object] = [resolved_id]

    where_clause = " AND ".join(conditions)
    last_client_id = 0
    while True:
        rows = session.execute(
            f"""
            SELECT DISTINCT d.client_id
            FROM demandes d
            JOIN clients c ON c.id = d.client_id
            WHERE {where_clause}
              AND d.client_id > %s
            ORDER BY d.client_id
            LIMIT %s
            """,
            tuple([*params, last_client_id, CACHE_DIRTY_MARK_CHUNK_SIZE]),
        ).fetchall()
        if not rows:
            break
        client_ids = [row_int(row, "client_id") for row in rows]
        _mark_rows_dirty(session, client_ids)
        last_client_id = client_ids[-1]


def mark_all_dirty(session: DbSession) -> None:
    """Mark entire cache as dirty (for rebuild)."""
    _set_lock_timeout(session)
    last_client_id = 0
    while True:
        rows = session.execute(
            """
            SELECT client_id
            FROM match_counts_cache
            WHERE is_dirty = 0
              AND client_id > %s
            ORDER BY client_id
            LIMIT %s
            """,
            (last_client_id, CACHE_DIRTY_MARK_CHUNK_SIZE),
        ).fetchall()
        if not rows:
            break
        client_ids = [row_int(row, "client_id") for row in rows]
        _mark_rows_dirty(session, client_ids)
        last_client_id = client_ids[-1]


def clear_all(session: DbSession) -> None:
    """Clear entire cache."""
    session.execute("DELETE FROM match_counts_cache")


def delete_client_cache(session: DbSession, client_id: int) -> None:
    """Delete cache entry for a client (when client is deleted)."""
    session.execute("DELETE FROM match_counts_cache WHERE client_id = %s", (client_id,))
