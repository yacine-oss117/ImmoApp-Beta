"""
Match cache/count tasks.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from datetime import datetime

from core.config.match_cache import (
    MATCH_CACHE_CHECKPOINT_LEASE_SEC,
    MATCH_CACHE_DB_BATCH_SIZE,
    MATCH_CACHE_HARD_TIME_LIMIT_SEC,
    MATCH_CACHE_MAX_ROWS_PER_RUN,
    MATCH_CACHE_SOFT_TIME_LIMIT_SEC,
)
from core.data import (
    lookup_tables,
    task_scan_checkpoint,
    tenant_work_lease,
)
from core.data import (
    match_cache as match_cache_data,
)
from core.matcher import match_counter
from core.utils.row_casts import row_int
from server.pg.uow import PgSession, PgUnitOfWork
from server.services import rebuild_leases

from .adaptive_batch import adaptive_batch_process
from .tasks_core import (
    count_active_clients,
    count_active_demandes,
    count_active_listings,
    count_active_offers,
    iter_active_client_batches,
    iter_active_demande_batches,
    iter_active_listing_batches,
    iter_active_offer_batches,
    logger,
    match_cache_rebuild_lock,
    match_compute_context,
    require_agency_id,
    store_counts,
    task_decorator,
)

TaskPayload = dict[str, object]


def _full_cte_fast_path_threshold() -> int:
    raw = os.environ.get("IMMOAPP_MATCH_CACHE_ALL_FULL_CTE_THRESHOLD", "1000").strip()
    try:
        value = int(raw)
    except ValueError:
        value = 1000
    return max(100, min(value, 100000))


def _should_use_full_cte_fast_path(*, total: int, last_id: int) -> bool:
    return int(last_id) <= 0 and int(total) <= _full_cte_fast_path_threshold()


def _maybe_run_full_count_fast_path(
    *,
    get_uow: Callable[[], PgUnitOfWork],
    checkpoint_enabled: bool,
    task_name: str,
    agency_id: int,
    stream_key: str,
    lease_owner: str,
    total: int,
    last_id: int,
    compute_counts: Callable[[PgSession], dict[int, int]],
) -> TaskPayload | None:
    if not _should_use_full_cte_fast_path(total=total, last_id=last_id):
        return None
    with get_uow().session() as session:
        counts = compute_counts(session)
    if checkpoint_enabled:
        with get_uow().transaction() as session:
            task_scan_checkpoint.reset_progress(
                session,
                task_name=task_name,
                agency_id=agency_id,
                stream_key=stream_key,
                lease_owner=lease_owner,
            )
    return {"counts": counts, "has_more": False, "last_id": 0}


def _resolve_rebuild_task_id(task: object, lease_task_id: str | None) -> str | None:
    if lease_task_id:
        return str(lease_task_id)
    request = getattr(task, "request", None)
    request_id = getattr(request, "id", None)
    if isinstance(request_id, str) and request_id.strip():
        return request_id.strip()
    return None


def _mark_rebuild_task_running(task_id: str | None, *, agency_id: int | None) -> None:
    if not task_id or agency_id is None:
        return
    from server.pg.uow import get_uow, use_security_context

    with use_security_context(agency_id=int(agency_id), is_superuser=True):
        with get_uow().transaction() as session:
            rebuild_leases.mark_rebuild_running(session, task_id=task_id)


def _mark_rebuild_task_done(task_id: str | None, *, agency_id: int | None) -> None:
    if not task_id or agency_id is None:
        return
    from server.pg.uow import get_uow, use_security_context

    with use_security_context(agency_id=int(agency_id), is_superuser=True):
        with get_uow().transaction() as session:
            rebuild_leases.mark_rebuild_done(session, task_id=task_id)


def _mark_rebuild_task_failed(
    task_id: str | None, exc: Exception, *, agency_id: int | None
) -> None:
    if not task_id or agency_id is None:
        return
    from server.pg.uow import get_uow, use_security_context

    with use_security_context(agency_id=int(agency_id), is_superuser=True):
        with get_uow().transaction() as session:
            rebuild_leases.mark_rebuild_failed(
                session,
                task_id=task_id,
                error_message=f"{type(exc).__name__}: {exc}",
            )


@task_decorator(
    soft_time_limit=MATCH_CACHE_SOFT_TIME_LIMIT_SEC,
    time_limit=MATCH_CACHE_HARD_TIME_LIMIT_SEC,
)
def rebuild_match_cache_all(
    _task: object,
    schema: str | None = None,
    agency_id: int | None = None,
    actor_id: int | None = None,
    actor_role: str | None = None,
    correlation_id: str | None = None,
    lease_task_id: str | None = None,
) -> dict[str, object]:
    """Rebuild the entire match cache for active clients."""
    task_id = _resolve_rebuild_task_id(_task, lease_task_id)
    try:
        agency_id = require_agency_id(agency_id, "rebuild_match_cache_all")
        _mark_rebuild_task_running(task_id, agency_id=agency_id)
        with match_compute_context(
            schema,
            agency_id,
            actor_id=actor_id,
            actor_role=actor_role,
            correlation_id=correlation_id,
        ):
            with match_cache_rebuild_lock(schema, agency_id) as locked:
                if not locked:
                    logger.info("Match cache rebuild skipped: lock already held")
                    _mark_rebuild_task_done(task_id, agency_id=agency_id)
                    return {"clients": 0, "total": 0, "skipped": True}

                from server.pg.uow import get_uow

                with get_uow().session() as session:
                    total = count_active_clients(session)

                stored_total = 0

                def _process_batch(batch: list[int]) -> None:
                    nonlocal stored_total
                    with get_uow().transaction() as session:
                        counts = match_counter.batch_count_clients_paginated(session, batch)
                        stored_total += store_counts(session, counts, label="clients")

                with get_uow().session() as session:
                    for client_page in iter_active_client_batches(
                        session,
                        batch_size=MATCH_CACHE_DB_BATCH_SIZE,
                    ):
                        if not client_page:
                            continue
                        page_batches = [
                            client_page[i : i + 100] for i in range(0, len(client_page), 100)
                        ]
                        adaptive_batch_process(
                            page_batches,
                            _process_batch,
                            batch_size=1,
                            label="cache_rebuild_all",
                        )

                logger.info("Match cache rebuild complete: %s/%s clients", stored_total, total)
                try:
                    from server.api.notifications import notify_only

                    notify_only(
                        scope="agency",
                        event_type="cache.rebuild_completed",
                        title="Matches refreshed",
                        body="All matches have been refreshed.",
                    )
                except Exception:
                    logger.warning("Failed to emit match rebuild notification", exc_info=True)
                _mark_rebuild_task_done(task_id, agency_id=agency_id)
                return {"clients": stored_total, "total": total}
    except Exception as exc:
        _mark_rebuild_task_failed(task_id, exc, agency_id=agency_id)
        raise


@task_decorator(
    soft_time_limit=MATCH_CACHE_SOFT_TIME_LIMIT_SEC,
    time_limit=MATCH_CACHE_HARD_TIME_LIMIT_SEC,
)
def rebuild_match_cache_dirty(
    _task: object,
    schema: str | None = None,
    agency_id: int | None = None,
    actor_id: int | None = None,
    actor_role: str | None = None,
    correlation_id: str | None = None,
    lease_task_id: str | None = None,
) -> dict[str, object]:
    """Rebuild match cache entries marked dirty."""
    task_id = _resolve_rebuild_task_id(_task, lease_task_id)
    try:
        agency_id = require_agency_id(agency_id, "rebuild_match_cache_dirty")
        _mark_rebuild_task_running(task_id, agency_id=agency_id)
        with match_compute_context(
            schema,
            agency_id,
            actor_id=actor_id,
            actor_role=actor_role,
            correlation_id=correlation_id,
        ):
            with match_cache_rebuild_lock(schema, agency_id) as locked:
                if not locked:
                    logger.info("Dirty cache rebuild skipped: lock already held")
                    _mark_rebuild_task_done(task_id, agency_id=agency_id)
                    return {"clients": 0, "dirty": 0, "skipped": True}

                from server.pg.uow import get_uow

                stored = 0
                dirty_total = 0

                def _process_dirty(batch: list[int]) -> None:
                    nonlocal stored
                    with get_uow().transaction() as session:
                        counts = match_counter.batch_count_clients_paginated(session, batch)
                        stored += store_counts(session, counts, label="dirty clients")

                def _process_missing(batch: list[int]) -> None:
                    nonlocal stored
                    with get_uow().transaction() as session:
                        counts = match_counter.batch_count_clients_paginated(session, batch)
                        stored += store_counts(session, counts, label="missing clients")

                with get_uow().session() as session:
                    last_dirty_id = 0
                    while True:
                        dirty_rows = session.execute(
                            """
                            SELECT client_id
                            FROM match_counts_cache
                            WHERE is_dirty = 1
                              AND client_id > %s
                            ORDER BY client_id
                            LIMIT %s
                            """,
                            (last_dirty_id, MATCH_CACHE_DB_BATCH_SIZE),
                        ).fetchall()
                        if not dirty_rows:
                            break
                        page_ids = [row_int(row, "client_id") for row in dirty_rows]
                        dirty_total += len(page_ids)
                        last_dirty_id = page_ids[-1]
                        dirty_batches = [
                            page_ids[i : i + 100] for i in range(0, len(page_ids), 100)
                        ]
                        adaptive_batch_process(
                            dirty_batches,
                            _process_dirty,
                            batch_size=1,
                            label="cache_dirty",
                        )

                    last_missing_id = 0
                    while True:
                        missing_rows = session.execute(
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
                            (last_missing_id, MATCH_CACHE_DB_BATCH_SIZE),
                        ).fetchall()
                        if not missing_rows:
                            break
                        page_ids = [row_int(row, "id") for row in missing_rows]
                        dirty_total += len(page_ids)
                        last_missing_id = page_ids[-1]
                        missing_batches = [
                            page_ids[i : i + 100] for i in range(0, len(page_ids), 100)
                        ]
                        adaptive_batch_process(
                            missing_batches,
                            _process_missing,
                            batch_size=1,
                            label="cache_missing",
                        )

                logger.info(
                    "Match cache dirty rebuild complete: %s/%s clients", stored, dirty_total
                )
                _mark_rebuild_task_done(task_id, agency_id=agency_id)
                return {"clients": stored, "dirty": dirty_total}
    except Exception as exc:
        _mark_rebuild_task_failed(task_id, exc, agency_id=agency_id)
        raise


@task_decorator(
    soft_time_limit=MATCH_CACHE_SOFT_TIME_LIMIT_SEC,
    time_limit=MATCH_CACHE_HARD_TIME_LIMIT_SEC,
)
def rebuild_match_cache_client(
    _task: object,
    client_id: int,
    schema: str | None = None,
    agency_id: int | None = None,
    actor_id: int | None = None,
    actor_role: str | None = None,
    correlation_id: str | None = None,
    lease_task_id: str | None = None,
) -> dict[str, object]:
    """Rebuild match cache for a single client."""
    task_id = _resolve_rebuild_task_id(_task, lease_task_id)
    try:
        agency_id = require_agency_id(agency_id, "rebuild_match_cache_client")
        _mark_rebuild_task_running(task_id, agency_id=agency_id)
        with match_compute_context(
            schema,
            agency_id,
            actor_id=actor_id,
            actor_role=actor_role,
            correlation_id=correlation_id,
        ):
            with match_cache_rebuild_lock(schema, agency_id) as locked:
                if not locked:
                    logger.info("Client cache rebuild skipped: lock already held")
                    _mark_rebuild_task_done(task_id, agency_id=agency_id)
                    return {"client_id": client_id, "count": 0, "skipped": True}

                from server.pg.uow import get_uow

                with get_uow().transaction() as session:
                    count = match_counter.count_single_client_cte(session, client_id)
                    match_cache_data.store_count(session, client_id, count)
                logger.info("Match cache rebuilt for client %s", client_id)
                _mark_rebuild_task_done(task_id, agency_id=agency_id)
                return {"client_id": client_id, "count": count}
    except Exception as exc:
        _mark_rebuild_task_failed(task_id, exc, agency_id=agency_id)
        raise


@task_decorator(
    soft_time_limit=MATCH_CACHE_SOFT_TIME_LIMIT_SEC,
    time_limit=MATCH_CACHE_HARD_TIME_LIMIT_SEC,
)
def rebuild_match_cache_wilaya(
    _task: object,
    wilaya_id: int | str | None = None,
    *,
    wilaya: str | None = None,
    schema: str | None = None,
    agency_id: int | None = None,
    actor_id: int | None = None,
    actor_role: str | None = None,
    correlation_id: str | None = None,
    lease_task_id: str | None = None,
) -> dict[str, object]:
    """Rebuild match cache for all clients in a wilaya."""
    task_id = _resolve_rebuild_task_id(_task, lease_task_id)
    try:
        agency_id = require_agency_id(agency_id, "rebuild_match_cache_wilaya")
        _mark_rebuild_task_running(task_id, agency_id=agency_id)
        with match_compute_context(
            schema,
            agency_id,
            actor_id=actor_id,
            actor_role=actor_role,
            correlation_id=correlation_id,
        ):
            with match_cache_rebuild_lock(schema, agency_id) as locked:
                if not locked:
                    logger.info("Wilaya cache rebuild skipped: lock already held")
                    _mark_rebuild_task_done(task_id, agency_id=agency_id)
                    return {"wilaya_id": wilaya_id, "clients": 0, "skipped": True}

                from server.pg.uow import get_uow

                with get_uow().transaction() as session:
                    resolved_id = _resolve_wilaya_id(session, wilaya_id, wilaya)
                    if not resolved_id:
                        _mark_rebuild_task_done(task_id, agency_id=agency_id)
                        return {"wilaya_id": wilaya_id, "clients": 0, "skipped": True}
                    counts = match_counter.count_clients_in_wilaya_cte(session, resolved_id)
                    stored = store_counts(session, counts, label=f"wilaya {resolved_id}")
                logger.info("Match cache rebuilt for wilaya %s (%s clients)", resolved_id, stored)
                _mark_rebuild_task_done(task_id, agency_id=agency_id)
                return {"wilaya_id": resolved_id, "clients": stored}
    except Exception as exc:
        _mark_rebuild_task_failed(task_id, exc, agency_id=agency_id)
        raise


def _resolve_wilaya_id(
    session: PgSession,
    wilaya_id: int | str | None,
    wilaya: str | None,
) -> int | None:
    if isinstance(wilaya_id, int):
        return None if wilaya_id == 0 else wilaya_id
    if isinstance(wilaya_id, str):
        text = wilaya_id.strip()
        if text.isdigit():
            value = int(text)
            return None if value == 0 else value
        return lookup_tables.get_wilaya_id(session, text)
    if wilaya:
        return lookup_tables.get_wilaya_id(session, wilaya)
    return None


def _task_lease_owner(task: object) -> str:
    request = getattr(task, "request", None)
    request_id = getattr(request, "id", None)
    if isinstance(request_id, str) and request_id:
        return request_id
    return f"task-{id(task)}"


def _deadline() -> float:
    return time.monotonic() + MATCH_CACHE_SOFT_TIME_LIMIT_SEC


def _budget_exhausted(*, rows_processed: int, deadline: float) -> bool:
    if rows_processed >= MATCH_CACHE_MAX_ROWS_PER_RUN:
        return True
    return time.monotonic() >= deadline


def _acquire_checkpoint(
    *,
    get_uow: Callable[[], PgUnitOfWork],
    task_name: str,
    agency_id: int,
    stream_key: str,
    lease_owner: str,
) -> tuple[task_scan_checkpoint.ScanCheckpoint | None, bool]:
    """Acquire checkpoint lease when table is available.

    Returns ``(checkpoint, checkpoint_enabled)``.
    """
    try:
        with get_uow().transaction() as session:
            checkpoint = task_scan_checkpoint.acquire_lease(
                session,
                task_name=task_name,
                agency_id=agency_id,
                stream_key=stream_key,
                lease_owner=lease_owner,
                lease_seconds=MATCH_CACHE_CHECKPOINT_LEASE_SEC,
            )
    except Exception as exc:
        if getattr(exc, "sqlstate", None) == "42P01":
            logger.warning(
                "task_scan_checkpoints table missing; running %s without resume support",
                task_name,
            )
            return (
                task_scan_checkpoint.ScanCheckpoint(last_id=0, rows_processed=0, attempt=0),
                False,
            )
        raise
    return checkpoint, True


@task_decorator(
    soft_time_limit=MATCH_CACHE_SOFT_TIME_LIMIT_SEC,
    time_limit=MATCH_CACHE_HARD_TIME_LIMIT_SEC,
)
def count_matches_all_clients_task(
    _task: object,
    schema: str | None = None,
    agency_id: int | None = None,
    actor_id: int | None = None,
    actor_role: str | None = None,
    correlation_id: str | None = None,
) -> dict[str, object]:
    """Compute match counts for all active clients in the background."""
    agency_id = require_agency_id(agency_id, "count_matches_all_clients_task")

    with match_compute_context(
        schema,
        agency_id,
        actor_id=actor_id,
        actor_role=actor_role,
        correlation_id=correlation_id,
    ):
        from server.pg.uow import get_uow

        lease_owner = _task_lease_owner(_task)
        task_name = "count_matches_all_clients_task"
        stream_key = "clients"
        try:
            checkpoint, checkpoint_enabled = _acquire_checkpoint(
                get_uow=get_uow,
                task_name=task_name,
                agency_id=agency_id,
                stream_key=stream_key,
                lease_owner=lease_owner,
            )
            if checkpoint_enabled and checkpoint is None:
                return {"counts": {}, "skipped": True}
            if checkpoint is None:
                checkpoint = task_scan_checkpoint.ScanCheckpoint(
                    last_id=0, rows_processed=0, attempt=0
                )

            deadline = _deadline()
            last_id = checkpoint.last_id
            rows_processed = checkpoint.rows_processed
            counts: dict[int, int] = {}
            has_more = False
            with get_uow().session() as session:
                total = count_active_clients(session)
            fast_path_result = _maybe_run_full_count_fast_path(
                get_uow=get_uow,
                checkpoint_enabled=checkpoint_enabled,
                task_name=task_name,
                agency_id=agency_id,
                stream_key=stream_key,
                lease_owner=lease_owner,
                total=total,
                last_id=last_id,
                compute_counts=match_counter.batch_count_all_clients_cte,
            )
            if fast_path_result is not None:
                return fast_path_result

            with get_uow().session() as session:
                for batch in iter_active_client_batches(
                    session,
                    batch_size=MATCH_CACHE_DB_BATCH_SIZE,
                    start_after_id=last_id,
                ):
                    if _budget_exhausted(rows_processed=rows_processed, deadline=deadline):
                        has_more = True
                        break
                    batch_counts = match_counter.batch_count_clients_paginated(session, batch)
                    counts.update(batch_counts)
                    rows_processed += len(batch)
                    last_id = batch[-1]
                    if checkpoint_enabled:
                        with get_uow().transaction() as tx:
                            task_scan_checkpoint.save_progress(
                                tx,
                                task_name=task_name,
                                agency_id=agency_id,
                                stream_key=stream_key,
                                lease_owner=lease_owner,
                                last_id=last_id,
                                rows_processed=rows_processed,
                            )
                            task_scan_checkpoint.heartbeat_lease(
                                tx,
                                task_name=task_name,
                                agency_id=agency_id,
                                stream_key=stream_key,
                                lease_owner=lease_owner,
                                lease_seconds=MATCH_CACHE_CHECKPOINT_LEASE_SEC,
                            )

            if checkpoint_enabled:
                with get_uow().transaction() as session:
                    if has_more:
                        task_scan_checkpoint.release_lease(
                            session,
                            task_name=task_name,
                            agency_id=agency_id,
                            stream_key=stream_key,
                            lease_owner=lease_owner,
                        )
                    else:
                        task_scan_checkpoint.reset_progress(
                            session,
                            task_name=task_name,
                            agency_id=agency_id,
                            stream_key=stream_key,
                            lease_owner=lease_owner,
                        )
            return {"counts": counts, "has_more": has_more, "last_id": last_id}
        finally:
            try:
                with get_uow().transaction() as session:
                    tenant_work_lease.release_stream_slot(
                        session,
                        task_name="matches_all",
                        agency_id=agency_id,
                        stream_key="clients:all",
                        lease_owner=lease_owner,
                    )
            except Exception as exc:
                if getattr(exc, "sqlstate", None) != "42P01":
                    logger.warning("Failed to release clients stream lease: %s", exc)


@task_decorator(
    soft_time_limit=MATCH_CACHE_SOFT_TIME_LIMIT_SEC,
    time_limit=MATCH_CACHE_HARD_TIME_LIMIT_SEC,
)
def count_matches_all_demandes_task(
    _task: object,
    schema: str | None = None,
    agency_id: int | None = None,
    actor_id: int | None = None,
    actor_role: str | None = None,
    correlation_id: str | None = None,
) -> dict[str, object]:
    """Compute match counts for all active demandes in the background."""
    agency_id = require_agency_id(agency_id, "count_matches_all_demandes_task")

    with match_compute_context(
        schema,
        agency_id,
        actor_id=actor_id,
        actor_role=actor_role,
        correlation_id=correlation_id,
    ):
        from core.matcher.match_counter import count_demandes_by_ids
        from server.pg.uow import get_uow

        lease_owner = _task_lease_owner(_task)
        task_name = "count_matches_all_demandes_task"
        stream_key = "demandes"
        try:
            checkpoint, checkpoint_enabled = _acquire_checkpoint(
                get_uow=get_uow,
                task_name=task_name,
                agency_id=agency_id,
                stream_key=stream_key,
                lease_owner=lease_owner,
            )
            if checkpoint_enabled and checkpoint is None:
                return {"counts": {}, "skipped": True}
            if checkpoint is None:
                checkpoint = task_scan_checkpoint.ScanCheckpoint(
                    last_id=0, rows_processed=0, attempt=0
                )

            deadline = _deadline()
            last_id = checkpoint.last_id
            rows_processed = checkpoint.rows_processed
            counts: dict[int, int] = {}
            has_more = False
            with get_uow().session() as session:
                total = count_active_demandes(session)
            fast_path_result = _maybe_run_full_count_fast_path(
                get_uow=get_uow,
                checkpoint_enabled=checkpoint_enabled,
                task_name=task_name,
                agency_id=agency_id,
                stream_key=stream_key,
                lease_owner=lease_owner,
                total=total,
                last_id=last_id,
                compute_counts=match_counter.batch_count_all_demandes_cte,
            )
            if fast_path_result is not None:
                return fast_path_result

            with get_uow().session() as session:
                for batch in iter_active_demande_batches(
                    session,
                    batch_size=MATCH_CACHE_DB_BATCH_SIZE,
                    start_after_id=last_id,
                ):
                    if _budget_exhausted(rows_processed=rows_processed, deadline=deadline):
                        has_more = True
                        break
                    batch_counts = count_demandes_by_ids(session, batch)
                    counts.update(batch_counts)
                    rows_processed += len(batch)
                    last_id = batch[-1]
                    if checkpoint_enabled:
                        with get_uow().transaction() as tx:
                            task_scan_checkpoint.save_progress(
                                tx,
                                task_name=task_name,
                                agency_id=agency_id,
                                stream_key=stream_key,
                                lease_owner=lease_owner,
                                last_id=last_id,
                                rows_processed=rows_processed,
                            )
                            task_scan_checkpoint.heartbeat_lease(
                                tx,
                                task_name=task_name,
                                agency_id=agency_id,
                                stream_key=stream_key,
                                lease_owner=lease_owner,
                                lease_seconds=MATCH_CACHE_CHECKPOINT_LEASE_SEC,
                            )

            if checkpoint_enabled:
                with get_uow().transaction() as session:
                    if has_more:
                        task_scan_checkpoint.release_lease(
                            session,
                            task_name=task_name,
                            agency_id=agency_id,
                            stream_key=stream_key,
                            lease_owner=lease_owner,
                        )
                    else:
                        task_scan_checkpoint.reset_progress(
                            session,
                            task_name=task_name,
                            agency_id=agency_id,
                            stream_key=stream_key,
                            lease_owner=lease_owner,
                        )
            return {"counts": counts, "has_more": has_more, "last_id": last_id}
        finally:
            try:
                with get_uow().transaction() as session:
                    tenant_work_lease.release_stream_slot(
                        session,
                        task_name="matches_all",
                        agency_id=agency_id,
                        stream_key="demandes:all",
                        lease_owner=lease_owner,
                    )
            except Exception as exc:
                if getattr(exc, "sqlstate", None) != "42P01":
                    logger.warning("Failed to release demandes stream lease: %s", exc)


@task_decorator(
    soft_time_limit=MATCH_CACHE_SOFT_TIME_LIMIT_SEC,
    time_limit=MATCH_CACHE_HARD_TIME_LIMIT_SEC,
)
def count_matches_all_listings_task(
    _task: object,
    schema: str | None = None,
    agency_id: int | None = None,
    actor_id: int | None = None,
    actor_role: str | None = None,
    correlation_id: str | None = None,
) -> dict[str, object]:
    """Compute match counts for all active listings in the background."""
    agency_id = require_agency_id(agency_id, "count_matches_all_listings_task")

    with match_compute_context(
        schema,
        agency_id,
        actor_id=actor_id,
        actor_role=actor_role,
        correlation_id=correlation_id,
    ):
        from server.pg.uow import get_uow

        lease_owner = _task_lease_owner(_task)
        task_name = "count_matches_all_listings_task"
        stream_key = "listings"
        try:
            checkpoint, checkpoint_enabled = _acquire_checkpoint(
                get_uow=get_uow,
                task_name=task_name,
                agency_id=agency_id,
                stream_key=stream_key,
                lease_owner=lease_owner,
            )
            if checkpoint_enabled and checkpoint is None:
                return {"counts": {}, "skipped": True}
            if checkpoint is None:
                checkpoint = task_scan_checkpoint.ScanCheckpoint(
                    last_id=0, rows_processed=0, attempt=0
                )

            deadline = _deadline()
            last_id = checkpoint.last_id
            rows_processed = checkpoint.rows_processed
            counts: dict[int, int] = {}
            has_more = False
            with get_uow().session() as session:
                total = count_active_listings(session)
            fast_path_result = _maybe_run_full_count_fast_path(
                get_uow=get_uow,
                checkpoint_enabled=checkpoint_enabled,
                task_name=task_name,
                agency_id=agency_id,
                stream_key=stream_key,
                lease_owner=lease_owner,
                total=total,
                last_id=last_id,
                compute_counts=match_counter.batch_count_all_listings_cte,
            )
            if fast_path_result is not None:
                return fast_path_result

            with get_uow().session() as session:
                for batch in iter_active_listing_batches(
                    session,
                    batch_size=MATCH_CACHE_DB_BATCH_SIZE,
                    start_after_id=last_id,
                ):
                    if _budget_exhausted(rows_processed=rows_processed, deadline=deadline):
                        has_more = True
                        break
                    batch_counts = match_counter.batch_count_listings_paginated(session, batch)
                    counts.update(batch_counts)
                    rows_processed += len(batch)
                    last_id = batch[-1]
                    if checkpoint_enabled:
                        with get_uow().transaction() as tx:
                            task_scan_checkpoint.save_progress(
                                tx,
                                task_name=task_name,
                                agency_id=agency_id,
                                stream_key=stream_key,
                                lease_owner=lease_owner,
                                last_id=last_id,
                                rows_processed=rows_processed,
                            )
                            task_scan_checkpoint.heartbeat_lease(
                                tx,
                                task_name=task_name,
                                agency_id=agency_id,
                                stream_key=stream_key,
                                lease_owner=lease_owner,
                                lease_seconds=MATCH_CACHE_CHECKPOINT_LEASE_SEC,
                            )

            if checkpoint_enabled:
                with get_uow().transaction() as session:
                    if has_more:
                        task_scan_checkpoint.release_lease(
                            session,
                            task_name=task_name,
                            agency_id=agency_id,
                            stream_key=stream_key,
                            lease_owner=lease_owner,
                        )
                    else:
                        task_scan_checkpoint.reset_progress(
                            session,
                            task_name=task_name,
                            agency_id=agency_id,
                            stream_key=stream_key,
                            lease_owner=lease_owner,
                        )
            return {"counts": counts, "has_more": has_more, "last_id": last_id}
        finally:
            try:
                with get_uow().transaction() as session:
                    tenant_work_lease.release_stream_slot(
                        session,
                        task_name="matches_all",
                        agency_id=agency_id,
                        stream_key="listings:all",
                        lease_owner=lease_owner,
                    )
            except Exception as exc:
                if getattr(exc, "sqlstate", None) != "42P01":
                    logger.warning("Failed to release listings stream lease: %s", exc)


@task_decorator(
    soft_time_limit=MATCH_CACHE_SOFT_TIME_LIMIT_SEC,
    time_limit=MATCH_CACHE_HARD_TIME_LIMIT_SEC,
)
def count_matches_all_offers_task(
    _task: object,
    schema: str | None = None,
    agency_id: int | None = None,
    actor_id: int | None = None,
    actor_role: str | None = None,
    correlation_id: str | None = None,
) -> dict[str, object]:
    """Compute match counts for all active offers in the background."""
    agency_id = require_agency_id(agency_id, "count_matches_all_offers_task")

    with match_compute_context(
        schema,
        agency_id,
        actor_id=actor_id,
        actor_role=actor_role,
        correlation_id=correlation_id,
    ):
        from core.matcher.match_counter import count_offers_by_ids
        from server.pg.uow import get_uow

        lease_owner = _task_lease_owner(_task)
        task_name = "count_matches_all_offers_task"
        stream_key = "offers"
        try:
            checkpoint, checkpoint_enabled = _acquire_checkpoint(
                get_uow=get_uow,
                task_name=task_name,
                agency_id=agency_id,
                stream_key=stream_key,
                lease_owner=lease_owner,
            )
            if checkpoint_enabled and checkpoint is None:
                return {"counts": {}, "skipped": True}
            if checkpoint is None:
                checkpoint = task_scan_checkpoint.ScanCheckpoint(
                    last_id=0, rows_processed=0, attempt=0
                )

            deadline = _deadline()
            last_id = checkpoint.last_id
            rows_processed = checkpoint.rows_processed
            counts: dict[int, int] = {}
            has_more = False
            with get_uow().session() as session:
                total = count_active_offers(session)
            fast_path_result = _maybe_run_full_count_fast_path(
                get_uow=get_uow,
                checkpoint_enabled=checkpoint_enabled,
                task_name=task_name,
                agency_id=agency_id,
                stream_key=stream_key,
                lease_owner=lease_owner,
                total=total,
                last_id=last_id,
                compute_counts=match_counter.batch_count_all_offers_cte,
            )
            if fast_path_result is not None:
                return fast_path_result

            with get_uow().session() as session:
                for batch in iter_active_offer_batches(
                    session,
                    batch_size=MATCH_CACHE_DB_BATCH_SIZE,
                    start_after_id=last_id,
                ):
                    if _budget_exhausted(rows_processed=rows_processed, deadline=deadline):
                        has_more = True
                        break
                    batch_counts = count_offers_by_ids(session, batch)
                    counts.update(batch_counts)
                    rows_processed += len(batch)
                    last_id = batch[-1]
                    if checkpoint_enabled:
                        with get_uow().transaction() as tx:
                            task_scan_checkpoint.save_progress(
                                tx,
                                task_name=task_name,
                                agency_id=agency_id,
                                stream_key=stream_key,
                                lease_owner=lease_owner,
                                last_id=last_id,
                                rows_processed=rows_processed,
                            )
                            task_scan_checkpoint.heartbeat_lease(
                                tx,
                                task_name=task_name,
                                agency_id=agency_id,
                                stream_key=stream_key,
                                lease_owner=lease_owner,
                                lease_seconds=MATCH_CACHE_CHECKPOINT_LEASE_SEC,
                            )

            if checkpoint_enabled:
                with get_uow().transaction() as session:
                    if has_more:
                        task_scan_checkpoint.release_lease(
                            session,
                            task_name=task_name,
                            agency_id=agency_id,
                            stream_key=stream_key,
                            lease_owner=lease_owner,
                        )
                    else:
                        task_scan_checkpoint.reset_progress(
                            session,
                            task_name=task_name,
                            agency_id=agency_id,
                            stream_key=stream_key,
                            lease_owner=lease_owner,
                        )
            return {"counts": counts, "has_more": has_more, "last_id": last_id}
        finally:
            try:
                with get_uow().transaction() as session:
                    tenant_work_lease.release_stream_slot(
                        session,
                        task_name="matches_all",
                        agency_id=agency_id,
                        stream_key="offers:all",
                        lease_owner=lease_owner,
                    )
            except Exception as exc:
                if getattr(exc, "sqlstate", None) != "42P01":
                    logger.warning("Failed to release offers stream lease: %s", exc)


@task_decorator(
    soft_time_limit=MATCH_CACHE_SOFT_TIME_LIMIT_SEC,
    time_limit=MATCH_CACHE_HARD_TIME_LIMIT_SEC,
)
def fetch_match_cache_all_task(
    _task: object,
    schema: str | None = None,
    agency_id: int | None = None,
    actor_id: int | None = None,
    actor_role: str | None = None,
    correlation_id: str | None = None,
) -> dict[str, object]:
    """Fetch cached match counts in bounded keyset pages (deprecated endpoint)."""
    agency_id = require_agency_id(agency_id, "fetch_match_cache_all_task")
    with match_compute_context(
        schema,
        agency_id,
        actor_id=actor_id,
        actor_role=actor_role,
        correlation_id=correlation_id,
    ):
        from server.pg.uow import get_uow

        lease_owner = _task_lease_owner(_task)
        task_name = "fetch_match_cache_all_task"
        stream_key = "cache_all"
        checkpoint, checkpoint_enabled = _acquire_checkpoint(
            get_uow=get_uow,
            task_name=task_name,
            agency_id=agency_id,
            stream_key=stream_key,
            lease_owner=lease_owner,
        )
        if checkpoint_enabled and checkpoint is None:
            return {"counts": {}, "count_meta": {}, "skipped": True}
        if checkpoint is None:
            checkpoint = task_scan_checkpoint.ScanCheckpoint(last_id=0, rows_processed=0, attempt=0)

        deadline = _deadline()
        last_id = checkpoint.last_id
        rows_processed = checkpoint.rows_processed
        counts: dict[int, int] = {}
        count_meta: dict[int, dict[str, object]] = {}
        has_more = False

        with get_uow().session() as session:
            while True:
                if _budget_exhausted(rows_processed=rows_processed, deadline=deadline):
                    has_more = True
                    break
                rows = session.execute(
                    """
                    SELECT client_id, count, computed_at, is_dirty
                    FROM match_counts_cache
                    WHERE client_id > %s
                    ORDER BY client_id
                    LIMIT %s
                    """,
                    (last_id, MATCH_CACHE_DB_BATCH_SIZE),
                ).fetchall()
                if not rows:
                    break
                for row in rows:
                    client_id = row_int(row, "client_id")
                    counts[client_id] = row_int(row, "count")
                    computed_at = row.get("computed_at")
                    computed_at_text = (
                        computed_at.isoformat() if isinstance(computed_at, datetime) else None
                    )
                    count_meta[client_id] = {
                        "status": "stale" if row_int(row, "is_dirty") == 1 else "fresh",
                        "computed_at": computed_at_text,
                    }
                rows_processed += len(rows)
                last_id = row_int(rows[-1], "client_id")
                if checkpoint_enabled:
                    with get_uow().transaction() as tx:
                        task_scan_checkpoint.save_progress(
                            tx,
                            task_name=task_name,
                            agency_id=agency_id,
                            stream_key=stream_key,
                            lease_owner=lease_owner,
                            last_id=last_id,
                            rows_processed=rows_processed,
                        )
                        task_scan_checkpoint.heartbeat_lease(
                            tx,
                            task_name=task_name,
                            agency_id=agency_id,
                            stream_key=stream_key,
                            lease_owner=lease_owner,
                            lease_seconds=MATCH_CACHE_CHECKPOINT_LEASE_SEC,
                        )

        if checkpoint_enabled:
            with get_uow().transaction() as session:
                if has_more:
                    task_scan_checkpoint.release_lease(
                        session,
                        task_name=task_name,
                        agency_id=agency_id,
                        stream_key=stream_key,
                        lease_owner=lease_owner,
                    )
                else:
                    task_scan_checkpoint.reset_progress(
                        session,
                        task_name=task_name,
                        agency_id=agency_id,
                        stream_key=stream_key,
                        lease_owner=lease_owner,
                    )
        return {
            "counts": counts,
            "count_meta": count_meta,
            "has_more": has_more,
            "last_id": last_id,
        }


__all__ = [
    "rebuild_match_cache_all",
    "rebuild_match_cache_dirty",
    "rebuild_match_cache_client",
    "rebuild_match_cache_wilaya",
    "count_matches_all_clients_task",
    "count_matches_all_demandes_task",
    "count_matches_all_listings_task",
    "count_matches_all_offers_task",
    "fetch_match_cache_all_task",
]
