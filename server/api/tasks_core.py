"""
Shared helpers for Celery tasks.
"""

from __future__ import annotations

import hashlib
import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import psycopg
from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded

from core.data import match_cache as match_cache_data
from core.utils.row_casts import row_int
from server.logging_config import set_correlation_id
from server.pg.uow import get_uow, use_actor_context, use_schema, use_security_context

logger = logging.getLogger(__name__)

_REBUILD_LOCK_NAMESPACE = "match_cache_rebuild"
_MATCH_PAIRS_LOCK_NAMESPACE = "match_pairs_rebuild"
_IMPORT_LOCK_NAMESPACE = "import_execution"
_TASK_TIME_LIMIT_SEC = int(os.environ.get("CELERY_TASK_TIME_LIMIT", "300"))
_TASK_SOFT_TIME_LIMIT_SEC = int(os.environ.get("CELERY_TASK_SOFT_TIME_LIMIT", "240"))
_TASK_RETRYABLE_EXCEPTIONS = (
    TimeoutError,
    ConnectionError,
    OSError,
    SoftTimeLimitExceeded,
    psycopg.OperationalError,
    psycopg.InterfaceError,
)

_TASK_RETRY_KWARGS = {
    "autoretry_for": _TASK_RETRYABLE_EXCEPTIONS,
    "retry_backoff": True,
    "retry_jitter": True,
    "max_retries": 5,
    "time_limit": _TASK_TIME_LIMIT_SEC,
    "soft_time_limit": _TASK_SOFT_TIME_LIMIT_SEC,
}


def task_decorator(**kwargs: Any) -> Any:
    """Shared task decorator with retry + time limits."""
    merged = dict(_TASK_RETRY_KWARGS)
    merged.update(kwargs)
    return shared_task(bind=True, **merged)


def enqueue_named_task(
    task: Any,
    *,
    queue: str,
    routing_key: str | None = None,
    task_id: str | None = None,
    **kwargs: Any,
) -> Any:
    """Route Celery work explicitly when dispatching from importer control-plane code."""
    return task.apply_async(
        kwargs=kwargs,
        queue=str(queue),
        routing_key=str(routing_key or queue),
        task_id=str(task_id or "") or None,
    )


def enqueue_import_task(task: Any, **kwargs: Any) -> Any:
    """Dispatch importer tasks to the imports queue explicitly."""
    return enqueue_named_task(task, queue="imports", routing_key="imports", **kwargs)


def require_agency_id(agency_id: int | None, task_name: str) -> int:
    """Tenant-scoped Celery tasks must not run with agency_id=None (RLS-safe)."""
    if agency_id is None:
        raise ValueError(f"{task_name}: agency_id is required (tenant-scoped task)")
    return agency_id


def normalize_pairs_limit(limit: int | None) -> int | None:
    if limit is None:
        return None
    limit = int(limit)
    if limit <= 0:
        return None
    return limit


def _lock_key(
    namespace: str, schema: str | None, agency_id: int | None, scope: str | None = None
) -> int:
    payload = f"{namespace}:{schema or 'public'}:{agency_id or 'all'}:{scope or ''}"
    digest = hashlib.sha256(payload.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") & 0x7FFF_FFFF_FFFF_FFFF


@contextmanager
def task_context(
    schema: str | None,
    agency_id: int | None,
    *,
    actor_id: int | None = None,
    actor_role: str | None = None,
    actor_is_owner: bool = False,
    correlation_id: str | None = None,
) -> Iterator[None]:
    """Apply schema + security context for Celery tasks."""
    set_correlation_id(correlation_id)
    try:
        with use_schema(schema):
            with (
                use_security_context(agency_id=agency_id, is_superuser=False),
                use_actor_context(
                    actor_id=actor_id,
                    actor_role=actor_role,
                    actor_is_owner=actor_is_owner,
                ),
            ):
                yield
    finally:
        set_correlation_id(None)


@contextmanager
def match_compute_context(
    schema: str | None,
    agency_id: int | None,
    *,
    actor_id: int | None = None,
    actor_role: str | None = None,
    correlation_id: str | None = None,
) -> Iterator[None]:
    """
    Apply context for background match computations.

    Matching precompute should run with agency-scoped manager visibility so
    restricted rows are not accidentally excluded from pair/candidate builds.
    """
    effective_role = actor_role or "manager"
    with task_context(
        schema,
        agency_id,
        actor_id=actor_id,
        actor_role=effective_role,
        actor_is_owner=False,
        correlation_id=correlation_id,
    ):
        yield


@contextmanager
def match_cache_rebuild_lock(schema: str | None, agency_id: int | None) -> Iterator[bool]:
    with get_uow().session() as session:
        lock_key = _lock_key(_REBUILD_LOCK_NAMESPACE, schema, agency_id)
        row = session.execute(
            "SELECT pg_try_advisory_lock(%s) AS locked",
            (lock_key,),
        ).fetchone()
        locked = bool(row and row.get("locked"))
        session.commit()
        if not locked:
            yield False
            return
        try:
            yield True
        finally:
            session.execute("SELECT pg_advisory_unlock(%s)", (lock_key,))
            session.commit()


@contextmanager
def match_pairs_rebuild_lock(
    schema: str | None, agency_id: int | None, scope: str | None
) -> Iterator[bool]:
    with get_uow().session() as session:
        lock_key = _lock_key(_MATCH_PAIRS_LOCK_NAMESPACE, schema, agency_id, scope)
        row = session.execute(
            "SELECT pg_try_advisory_lock(%s) AS locked",
            (lock_key,),
        ).fetchone()
        locked = bool(row and row.get("locked"))
        session.commit()
        if not locked:
            yield False
            return
        try:
            yield True
        finally:
            session.execute("SELECT pg_advisory_unlock(%s)", (lock_key,))
            session.commit()


@contextmanager
def import_execution_lock(schema: str | None, agency_id: int | None) -> Iterator[bool]:
    with get_uow().session() as session:
        lock_key = _lock_key(_IMPORT_LOCK_NAMESPACE, schema, agency_id)
        row = session.execute(
            "SELECT pg_try_advisory_lock(%s) AS locked",
            (lock_key,),
        ).fetchone()
        locked = bool(row and row.get("locked"))
        session.commit()
        if not locked:
            yield False
            return
        try:
            yield True
        finally:
            session.execute("SELECT pg_advisory_unlock(%s)", (lock_key,))
            session.commit()


def store_counts(session: Any, counts: dict[int, int], *, label: str) -> int:
    if not counts:
        logger.info("Match cache rebuild skipped: no %s to store", label)
        return 0
    match_cache_data.store_counts_batch(session, counts)
    return len(counts)


def iter_chunks(ids: list[int], chunk_size: int) -> list[list[int]]:
    return [ids[i : i + chunk_size] for i in range(0, len(ids), chunk_size)]


def count_active_clients(session: Any) -> int:
    sql = "SELECT COUNT(*) AS count FROM clients WHERE status = 'active' AND deleted_at IS NULL"
    row = session.execute(sql).fetchone()
    return row_int(row, "count") if row else 0


def count_active_demandes(session: Any) -> int:
    sql = "SELECT COUNT(*) AS count FROM demandes WHERE deleted_at IS NULL"
    row = session.execute(sql).fetchone()
    return row_int(row, "count") if row else 0


def count_active_listings(session: Any) -> int:
    sql = "SELECT COUNT(*) AS count FROM listings WHERE status = 'available' AND deleted_at IS NULL"
    row = session.execute(sql).fetchone()
    return row_int(row, "count") if row else 0


def count_active_offers(session: Any) -> int:
    sql = "SELECT COUNT(*) AS count FROM offers WHERE deleted_at IS NULL"
    row = session.execute(sql).fetchone()
    return row_int(row, "count") if row else 0


def iter_active_client_batches(
    session: Any,
    *,
    batch_size: int,
    start_after_id: int = 0,
) -> Iterator[list[int]]:
    last_id = max(0, int(start_after_id))
    while True:
        sql = "SELECT id FROM clients WHERE status = 'active' AND deleted_at IS NULL " "AND id > %s"
        params: list[object] = [last_id]
        sql += " ORDER BY id LIMIT %s"
        params.append(batch_size)
        rows = session.execute(sql, params).fetchall()
        if not rows:
            break
        ids = [row_int(row, "id") for row in rows]
        if not ids:
            break
        last_id = ids[-1]
        yield ids


def iter_active_demande_batches(
    session: Any,
    *,
    batch_size: int,
    start_after_id: int = 0,
) -> Iterator[list[int]]:
    last_id = max(0, int(start_after_id))
    while True:
        sql = "SELECT id FROM demandes WHERE deleted_at IS NULL AND id > %s ORDER BY id LIMIT %s"
        rows = session.execute(sql, [last_id, batch_size]).fetchall()
        if not rows:
            break
        ids = [row_int(row, "id") for row in rows]
        if not ids:
            break
        last_id = ids[-1]
        yield ids


def iter_active_listing_batches(
    session: Any,
    *,
    batch_size: int,
    start_after_id: int = 0,
) -> Iterator[list[int]]:
    last_id = max(0, int(start_after_id))
    while True:
        sql = (
            "SELECT id FROM listings "
            "WHERE status = 'available' AND deleted_at IS NULL AND id > %s "
            "ORDER BY id LIMIT %s"
        )
        rows = session.execute(sql, [last_id, batch_size]).fetchall()
        if not rows:
            break
        ids = [row_int(row, "id") for row in rows]
        if not ids:
            break
        last_id = ids[-1]
        yield ids


def iter_active_offer_batches(
    session: Any,
    *,
    batch_size: int,
    start_after_id: int = 0,
) -> Iterator[list[int]]:
    last_id = max(0, int(start_after_id))
    while True:
        sql = "SELECT id FROM offers WHERE deleted_at IS NULL AND id > %s ORDER BY id LIMIT %s"
        rows = session.execute(sql, [last_id, batch_size]).fetchall()
        if not rows:
            break
        ids = [row_int(row, "id") for row in rows]
        if not ids:
            break
        last_id = ids[-1]
        yield ids


def iter_active_agency_batches(
    session: Any,
    *,
    batch_size: int,
    start_after_id: int = 0,
) -> Iterator[list[int]]:
    last_id = max(0, int(start_after_id))
    while True:
        sql = (
            "SELECT id FROM accounts_agency "
            "WHERE is_active = true AND id > %s "
            "ORDER BY id LIMIT %s"
        )
        rows = session.execute(sql, [last_id, batch_size]).fetchall()
        if not rows:
            break
        ids = [row_int(row, "id") for row in rows]
        if not ids:
            break
        last_id = ids[-1]
        yield ids


__all__ = [
    "task_decorator",
    "require_agency_id",
    "normalize_pairs_limit",
    "task_context",
    "match_compute_context",
    "match_cache_rebuild_lock",
    "match_pairs_rebuild_lock",
    "import_execution_lock",
    "store_counts",
    "iter_chunks",
    "count_active_clients",
    "count_active_demandes",
    "count_active_listings",
    "count_active_offers",
    "iter_active_client_batches",
    "iter_active_demande_batches",
    "iter_active_listing_batches",
    "iter_active_offer_batches",
    "iter_active_agency_batches",
    "logger",
]
