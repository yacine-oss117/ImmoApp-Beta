"""
Postgres-backed match cache helpers (wrapper around core.data.match_cache).

Note: agency_id is optional to allow superuser access across agencies when needed.
"""

from __future__ import annotations

from core.config.match_cache import CACHE_RETRY_BASE_DELAY_SEC, CACHE_WRITE_MAX_ATTEMPTS
from core.data import match_cache as data
from core.data.match_cache_read import CachedCountMeta
from core.utils.db_retry import run_with_retry
from server.immoapp_server.business_metrics_match import record_match_cache_lookup
from server.pg.uow import get_uow

__all__ = [
    "get_cached_count",
    "get_cached_counts_batch",
    "get_cached_counts_batch_with_meta",
    "get_cached_count_with_status",
    "get_dirty_client_count",
    "get_dirty_client_ids_page",
    "get_missing_client_count",
    "get_missing_client_ids_page",
    "is_cache_clean",
    "mark_all_dirty",
    "mark_client_dirty",
    "mark_clients_in_wilaya_dirty",
    "store_count",
    "store_counts_batch",
    "clear_all",
]


def get_cached_count(client_id: int) -> int | None:
    """Retrieve a single cached match count for a client."""
    with get_uow().session() as session:
        cached = data.get_cached_count(session, client_id)
    record_match_cache_lookup(
        cache_name="match_counts_cache",
        outcome="hit" if cached is not None else "miss",
    )
    return cached


def get_cached_counts_batch(client_ids: list[int]) -> dict[int, int]:
    """Retrieve multiple cached match counts at once."""
    with get_uow().session() as session:
        counts = data.get_cached_counts_batch(session, client_ids)
    hits = len(counts)
    misses = max(0, len(client_ids) - hits)
    if hits:
        record_match_cache_lookup(cache_name="match_counts_cache", outcome="hit", count=hits)
    if misses:
        record_match_cache_lookup(cache_name="match_counts_cache", outcome="miss", count=misses)
    return counts


def get_cached_counts_batch_with_meta(
    client_ids: list[int],
) -> tuple[dict[int, int], dict[int, CachedCountMeta]]:
    """Retrieve multiple cached counts plus freshness metadata."""
    with get_uow().session() as session:
        counts, meta = data.get_cached_counts_with_meta_for_ids(session, client_ids)
    hits = len(counts)
    misses = max(0, len(client_ids) - hits)
    if hits:
        record_match_cache_lookup(cache_name="match_counts_cache", outcome="hit", count=hits)
    if misses:
        record_match_cache_lookup(cache_name="match_counts_cache", outcome="miss", count=misses)
    return counts, meta


def get_cached_count_with_status(client_id: int) -> dict[str, object]:
    """Retrieve a cached count with status metadata for a single client."""
    with get_uow().session() as session:
        cached = data.get_cached_count_with_status(session, client_id)
    record_match_cache_lookup(
        cache_name="match_counts_cache",
        outcome="hit" if cached.get("status") != "missing" else "miss",
    )
    return dict(cached)


def get_dirty_client_count() -> int:
    """Count clients needing recomputation (dirty + missing)."""
    with get_uow().session() as session:
        return int(data.get_dirty_client_count(session))


def get_missing_client_count() -> int:
    """Count clients with no match-cache entry."""
    with get_uow().session() as session:
        return int(data.get_missing_client_count(session))


def get_dirty_client_ids_page(
    *,
    limit: int,
    after_id: int = 0,
) -> tuple[list[int], int | None, bool]:
    """List a bounded page of client IDs needing recomputation."""
    with get_uow().session() as session:
        return data.get_dirty_client_ids_page(session, limit=limit, after_id=after_id)


def get_missing_client_ids_page(
    *,
    limit: int,
    after_id: int = 0,
) -> tuple[list[int], int | None, bool]:
    """List a bounded page of missing cache client IDs."""
    with get_uow().session() as session:
        return data.get_missing_client_ids_page(session, limit=limit, after_id=after_id)


def is_cache_clean() -> bool:
    """Check if there are no dirty or missing entries in the match cache."""
    with get_uow().session() as session:
        return data.is_cache_clean(session)


def mark_all_dirty() -> None:
    """Mark all client match counts as dirty for an agency."""

    def _do() -> None:
        with get_uow().transaction() as session:
            data.mark_all_dirty(session)

    run_with_retry(
        _do,
        max_attempts=CACHE_WRITE_MAX_ATTEMPTS,
        base_delay_seconds=CACHE_RETRY_BASE_DELAY_SEC,
    )


def mark_client_dirty(client_id: int) -> None:
    """Mark a specific client's match count as dirty."""

    def _do() -> None:
        with get_uow().transaction() as session:
            data.mark_client_dirty(session, client_id)

    run_with_retry(
        _do,
        max_attempts=CACHE_WRITE_MAX_ATTEMPTS,
        base_delay_seconds=CACHE_RETRY_BASE_DELAY_SEC,
    )


def mark_clients_in_wilaya_dirty(
    wilaya_id: int | None = None,
    *,
    wilaya: str | None = None,
) -> None:
    """Mark all clients in a wilaya as dirty."""

    def _do() -> None:
        with get_uow().transaction() as session:
            data.mark_clients_in_wilaya_dirty(session, wilaya_id, wilaya=wilaya)

    run_with_retry(
        _do,
        max_attempts=CACHE_WRITE_MAX_ATTEMPTS,
        base_delay_seconds=CACHE_RETRY_BASE_DELAY_SEC,
    )


def store_count(client_id: int, count: int) -> None:
    """Persist a computed match count for a client and clear its dirty flag."""

    def _do() -> None:
        with get_uow().transaction() as session:
            data.store_count(session, client_id, count)

    run_with_retry(
        _do,
        max_attempts=CACHE_WRITE_MAX_ATTEMPTS,
        base_delay_seconds=CACHE_RETRY_BASE_DELAY_SEC,
    )


def store_counts_batch(counts: dict[int, int]) -> None:
    """Batch persist multiple computed match counts."""

    def _do() -> None:
        with get_uow().transaction() as session:
            data.store_counts_batch(session, counts)

    run_with_retry(
        _do,
        max_attempts=CACHE_WRITE_MAX_ATTEMPTS,
        base_delay_seconds=CACHE_RETRY_BASE_DELAY_SEC,
    )


def clear_all(agency_id: int | None = None) -> None:
    """Permanently clear all entries in the match cache for an agency."""
    # Use security context so tenant RLS rules scope the delete correctly.
    from server.pg.uow import use_security_context

    with use_security_context(agency_id=agency_id):
        with get_uow().transaction() as session:
            data.clear_all(session)
