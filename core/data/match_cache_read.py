"""
Read helpers for the match count cache.
"""

from __future__ import annotations

import logging
from typing import Literal, TypedDict

from core.matcher.ports.db import DbSession
from core.models_cast import as_int, row_at
from core.utils.memory_guard import adaptive_chunk_size
from core.utils.row_casts import row_int, row_optional_int

logger = logging.getLogger(__name__)
_CACHE_PAGE_DEFAULT_LIMIT = 100
_CACHE_PAGE_MAX_LIMIT = 5000


class HotLeadRow(TypedDict):
    """Typed shape for hot lead results."""

    client_id: int
    count: int
    computed_at: str | None
    count_status: str


CountStatus = Literal["fresh", "stale", "missing"]


class CachedCount(TypedDict):
    count: int
    computed_at: str | None
    status: CountStatus


class CachedCountMeta(TypedDict):
    status: CountStatus
    computed_at: str | None


def _iso_or_none(value: object) -> str | None:
    if value is None:
        return None
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        return str(isoformat())
    return None


def is_cache_clean(session: DbSession) -> bool:
    """
    Check if ALL cache entries are clean (not dirty).
    Optimized for 100k+ records: avoids slow JOINs.
    """
    # 1. Explicitly dirty records? (O(1) with index)
    dirty = session.execute(
        "SELECT 1 FROM match_counts_cache WHERE is_dirty = 1 LIMIT 1"
    ).fetchone()
    if dirty:
        return False

    # 2. Does cache count match client count?
    client_count_sql = "SELECT COUNT(*) FROM clients WHERE status = 'active' AND deleted_at IS NULL"
    total_clients_row = session.execute(client_count_sql).fetchone()
    total_clients = as_int(row_at(total_clients_row, 0)) if total_clients_row else 0

    cache_count_sql = "SELECT COUNT(*) FROM match_counts_cache WHERE is_dirty = 0"
    cache_count_row = session.execute(cache_count_sql).fetchone()
    cache_count = as_int(row_at(cache_count_row, 0)) if cache_count_row else 0

    return total_clients == cache_count


def get_dirty_count(session: DbSession) -> int:
    """Get count of dirty entries (need recomputation)."""
    sql = "SELECT COUNT(*) FROM match_counts_cache WHERE is_dirty = 1"
    row = session.execute(sql).fetchone()
    return as_int(row_at(row, 0)) if row else 0


def get_cached_count(session: DbSession, client_id: int) -> int | None:
    """
    Get cached count for a client.
    Returns None only when no row exists.
    """
    row = session.execute(
        "SELECT m.count FROM match_counts_cache m WHERE m.client_id = %s",
        [client_id],
    ).fetchone()
    return row_optional_int(row, "count") if row else None


def get_cached_count_with_status(session: DbSession, client_id: int) -> CachedCount:
    """Get cached count and freshness status for a single client."""
    row = session.execute(
        """
        SELECT m.count, m.computed_at, m.is_dirty
        FROM match_counts_cache m
        WHERE m.client_id = %s
        """,
        [client_id],
    ).fetchone()
    if not row:
        return {"count": 0, "computed_at": None, "status": "missing"}
    is_dirty = row_int(row, "is_dirty") == 1
    computed_at = _iso_or_none(row.get("computed_at"))
    return {
        "count": row_int(row, "count"),
        "computed_at": computed_at,
        "status": "stale" if is_dirty else "fresh",
    }


def get_cached_counts_batch(session: DbSession, client_ids: list[int]) -> dict[int, int]:
    """Get cached counts for a specific list of clients."""
    return get_cached_count_for_ids(session, client_ids)


def get_cached_count_for_ids(session: DbSession, client_ids: list[int]) -> dict[int, int]:
    """Get cached counts (fresh or stale) for a potentially large list of clients."""
    counts, _meta = get_cached_counts_with_meta_for_ids(session, client_ids)
    return counts


def get_cached_counts_with_meta_for_ids(
    session: DbSession,
    client_ids: list[int],
) -> tuple[dict[int, int], dict[int, CachedCountMeta]]:
    """Get cached counts plus freshness metadata for each requested client id."""
    if not client_ids:
        return {}, {}

    normalized_ids = sorted({int(client_id) for client_id in client_ids if int(client_id) > 0})
    if not normalized_ids:
        return {}, {}

    chunk_size = adaptive_chunk_size(floor=100, ceiling=1000)
    result: dict[int, int] = {}
    meta: dict[int, CachedCountMeta] = {}
    for index in range(0, len(normalized_ids), chunk_size):
        batch = normalized_ids[index : index + chunk_size]
        placeholders = ",".join(["%s"] * len(batch))
        sql = f"""
            SELECT m.client_id, m.count, m.computed_at, m.is_dirty
            FROM match_counts_cache m
            WHERE m.client_id IN ({placeholders})
        """
        rows = session.execute(sql, batch).fetchall()
        for row in rows:
            client_id = row_int(row, "client_id")
            result[client_id] = row_int(row, "count")
            is_dirty = row_int(row, "is_dirty") == 1
            meta[client_id] = {
                "status": "stale" if is_dirty else "fresh",
                "computed_at": _iso_or_none(row.get("computed_at")),
            }
    for client_id in normalized_ids:
        meta.setdefault(client_id, {"status": "missing", "computed_at": None})
    return result, meta


def get_hot_leads(session: DbSession, min_matches: int = 5, limit: int = 5) -> list[HotLeadRow]:
    """
    Get top N clients with >= min_matches matches.
    """
    sql = """
        SELECT m.client_id, m.count, m.computed_at, m.is_dirty
        FROM match_counts_cache m
        WHERE m.count >= %s
    """
    params = [min_matches]
    sql += " ORDER BY m.count DESC LIMIT %s"
    params.append(limit)
    rows = session.execute(sql, params).fetchall()
    out: list[HotLeadRow] = []
    for row in rows:
        is_dirty = row_int(row, "is_dirty") == 1
        out.append(
            {
                "client_id": row_int(row, "client_id"),
                "count": row_int(row, "count"),
                "computed_at": _iso_or_none(row.get("computed_at")),
                "count_status": "stale" if is_dirty else "fresh",
            }
        )
    return out


def _bounded_page_limit(limit: int) -> int:
    normalized = int(limit) if int(limit) > 0 else _CACHE_PAGE_DEFAULT_LIMIT
    return min(_CACHE_PAGE_MAX_LIMIT, normalized)


def get_missing_client_count(session: DbSession) -> int:
    """Count active clients that have no cache row."""
    row = session.execute("""
        SELECT COUNT(*) AS count
        FROM clients c
        LEFT JOIN match_counts_cache m ON m.client_id = c.id
        WHERE c.status = 'active'
          AND c.deleted_at IS NULL
          AND m.client_id IS NULL
        """).fetchone()
    return row_int(row, "count") if row else 0


def get_dirty_client_count(session: DbSession) -> int:
    """Count clients that need recomputation (dirty rows + missing rows)."""
    return get_dirty_count(session) + get_missing_client_count(session)


def get_missing_client_ids_page(
    session: DbSession,
    *,
    limit: int,
    after_id: int = 0,
) -> tuple[list[int], int | None, bool]:
    """Return a bounded page of missing client IDs."""
    bounded_limit = _bounded_page_limit(limit)
    start_after = max(0, int(after_id))
    rows = session.execute(
        """
        SELECT c.id
        FROM clients c
        LEFT JOIN match_counts_cache m ON m.client_id = c.id
        WHERE c.status = 'active'
          AND c.deleted_at IS NULL
          AND m.client_id IS NULL
          AND c.id > %s
        ORDER BY c.id
        LIMIT %s
        """,
        [start_after, bounded_limit + 1],
    ).fetchall()
    ids = [row_int(row, "id") for row in rows]
    has_more = len(ids) > bounded_limit
    if has_more:
        ids = ids[:bounded_limit]
    next_cursor = ids[-1] if has_more and ids else None
    return ids, next_cursor, has_more


def get_dirty_client_ids_page(
    session: DbSession,
    *,
    limit: int,
    after_id: int = 0,
) -> tuple[list[int], int | None, bool]:
    """Return a bounded page of client IDs needing recomputation."""
    bounded_limit = _bounded_page_limit(limit)
    start_after = max(0, int(after_id))
    rows = session.execute(
        """
        SELECT q.id
        FROM (
            SELECT m.client_id AS id
            FROM match_counts_cache m
            WHERE m.is_dirty = 1
            UNION ALL
            SELECT c.id AS id
            FROM clients c
            LEFT JOIN match_counts_cache m ON m.client_id = c.id
            WHERE c.status = 'active'
              AND c.deleted_at IS NULL
              AND m.client_id IS NULL
        ) q
        WHERE q.id > %s
        ORDER BY q.id
        LIMIT %s
        """,
        [start_after, bounded_limit + 1],
    ).fetchall()
    ids = [row_int(row, "id") for row in rows]
    has_more = len(ids) > bounded_limit
    if has_more:
        ids = ids[:bounded_limit]
    next_cursor = ids[-1] if has_more and ids else None
    return ids, next_cursor, has_more
