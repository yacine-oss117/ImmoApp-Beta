"""
Integrity janitor tasks for match data safety.
"""

from __future__ import annotations

import os

from core.data import match_cache_read, match_rebuild_state
from core.data import match_pairs as match_pairs_data
from core.utils.row_casts import row_int

from .adaptive_batch import adaptive_batch_process
from .tasks_core import iter_active_agency_batches, logger, task_decorator

_JANITOR_STALE_SEC = int(os.environ.get("MATCH_REBUILD_JANITOR_STALE_SEC", "3600"))
_JANITOR_PENDING_LIMIT = int(os.environ.get("MATCH_REBUILD_JANITOR_PENDING_LIMIT", "200"))
_JANITOR_MISSING_LIMIT = int(os.environ.get("MATCH_REBUILD_JANITOR_MISSING_LIMIT", "200"))
_JANITOR_DEMANDE_ENQUEUE_BATCH_SIZE = int(
    os.environ.get("MATCH_REBUILD_JANITOR_ENQUEUE_BATCH_SIZE", "200")
)


def _schedule_rebuild(
    *,
    scope: str,
    scope_id: int,
    agency_id: int,
    schema: str | None,
    correlation_id: str | None,
) -> bool:
    from server.pg.uow import get_uow

    with get_uow().transaction() as session:
        should_enqueue = match_rebuild_state.request_rebuild(
            session, scope=scope, scope_id=scope_id
        )
    if not should_enqueue:
        return False

    kwargs = {
        "schema": schema,
        "agency_id": agency_id,
        "correlation_id": correlation_id,
    }
    if scope == "demande":
        from .tasks_match_pairs import rebuild_match_pairs_for_demande

        rebuild_match_pairs_for_demande.delay(int(scope_id), **kwargs)
    elif scope == "client":
        from .tasks_match_pairs import rebuild_match_pairs_for_client

        rebuild_match_pairs_for_client.delay(int(scope_id), **kwargs)
    elif scope == "offer":
        from .tasks_match_pairs import rebuild_match_pairs_for_offer

        rebuild_match_pairs_for_offer.delay(int(scope_id), **kwargs)
    elif scope == "wilaya":
        from .tasks_match_pairs import rebuild_match_pairs_for_wilaya

        rebuild_match_pairs_for_wilaya.delay(int(scope_id), **kwargs)
    else:
        logger.warning("Janitor skipped unknown rebuild scope: %s", scope)
        return False

    return True


def _schedule_demande_rebuilds_batch(
    *,
    demande_ids: list[int],
    agency_id: int,
    schema: str | None,
    correlation_id: str | None,
) -> int:
    normalized_ids = sorted({int(v) for v in (demande_ids or []) if int(v) > 0})
    if not normalized_ids:
        return 0
    from server.services.match_jobs import enqueue_rebuild_demande_pairs_batch

    enqueue_rebuild_demande_pairs_batch(normalized_ids, agency_id=agency_id)
    return len(normalized_ids)


@task_decorator()
def match_pairs_janitor_task(
    _task: object,
    *,
    stale_seconds: int | None = None,
    pending_limit: int | None = None,
    missing_limit: int | None = None,
) -> dict[str, object]:
    """
    Daily safety sweep to recover from missed match-pair rebuilds.

    - Re-enqueues stale pending rebuilds.
    - Rebuilds demandes that have candidates but no stored pairs.
    - Kicks dirty match-count cache rebuilds.
    """

    from server.pg.uow import admin_transaction, get_current_schema, get_uow, use_security_context

    stale_seconds = _JANITOR_STALE_SEC if stale_seconds is None else int(stale_seconds)
    pending_limit = _JANITOR_PENDING_LIMIT if pending_limit is None else int(pending_limit)
    missing_limit = _JANITOR_MISSING_LIMIT if missing_limit is None else int(missing_limit)

    pages_processed = 0

    total_pending = 0
    total_missing = 0
    total_cold = 0
    total_scheduled = 0
    cache_rebuilds = 0
    cache_pruned = 0
    claim_recoveries = 0

    def _process_agency(agency_id: int) -> None:
        nonlocal total_pending, total_missing, total_cold, total_scheduled
        nonlocal cache_rebuilds, cache_pruned, claim_recoveries
        with use_security_context(agency_id=agency_id, is_superuser=False):
            schema = get_current_schema()
            with get_uow().session() as session:
                claim_recoveries += match_rebuild_state.reclaim_expired_dispatch_claims(
                    session,
                    scope="demande",
                    limit=pending_limit,
                )
                pending = match_rebuild_state.fetch_stale_pending(
                    session,
                    limit=pending_limit,
                    stale_seconds=stale_seconds,
                )
                missing_pairs = match_pairs_data.find_demande_ids_missing_pairs(
                    session, limit=missing_limit
                )
                cold_rows = session.execute(
                    """
                    SELECT d.id
                    FROM demandes d
                    WHERE d.deleted_at IS NULL
                      AND NOT EXISTS (
                        SELECT 1 FROM match_candidates mc WHERE mc.demande_id = d.id
                      )
                      AND NOT EXISTS (
                        SELECT 1 FROM match_pairs mp WHERE mp.demande_id = d.id
                      )
                      AND NOT EXISTS (
                        SELECT 1 FROM match_rebuild_state rs
                        WHERE rs.scope = 'demande'
                          AND rs.scope_id = d.id
                          AND rs.pending = TRUE
                      )
                    LIMIT %s
                    """,
                    (missing_limit,),
                ).fetchall()
                cold_demande_ids = [row_int(row, "id") for row in cold_rows]
                dirty_cache = match_cache_read.get_dirty_count(session)
                pruned = session.execute("""
                    DELETE FROM match_counts_cache m
                    USING clients c
                    WHERE c.id = m.client_id
                      AND (c.deleted_at IS NOT NULL OR c.status <> 'active')
                    """).rowcount
                cache_pruned += int(pruned or 0)

            pending_demande_ids: list[int] = []
            for row in pending:
                scope = str(row.get("scope") or "")
                scope_id = row_int(row, "scope_id") if row.get("scope_id") is not None else 0
                if scope_id <= 0:
                    continue
                if scope == "demande":
                    pending_demande_ids.append(scope_id)
                    continue
                total_pending += 1
                if _schedule_rebuild(
                    scope=scope,
                    scope_id=scope_id,
                    agency_id=agency_id,
                    schema=schema,
                    correlation_id="janitor:pending",
                ):
                    total_scheduled += 1
            if pending_demande_ids:
                total_pending += len(pending_demande_ids)
                total_scheduled += _schedule_demande_rebuilds_batch(
                    demande_ids=pending_demande_ids,
                    agency_id=agency_id,
                    schema=schema,
                    correlation_id="janitor:pending",
                )

            missing_demande_ids = [
                int(demande_id) for demande_id in missing_pairs if demande_id > 0
            ]
            if missing_demande_ids:
                total_missing += len(missing_demande_ids)
                total_scheduled += _schedule_demande_rebuilds_batch(
                    demande_ids=missing_demande_ids,
                    agency_id=agency_id,
                    schema=schema,
                    correlation_id="janitor:missing",
                )

            if cold_demande_ids:
                total_cold += len(cold_demande_ids)
                total_scheduled += _schedule_demande_rebuilds_batch(
                    demande_ids=cold_demande_ids,
                    agency_id=agency_id,
                    schema=schema,
                    correlation_id="janitor:cold",
                )

            if dirty_cache > 0:
                from .tasks_match_cache import rebuild_match_cache_dirty

                rebuild_match_cache_dirty.delay(
                    schema=schema,
                    agency_id=agency_id,
                    correlation_id="janitor:cache",
                )
                cache_rebuilds += 1

    with admin_transaction() as session:
        for agency_batch in iter_active_agency_batches(session, batch_size=500):
            pages_processed += 1
            adaptive_batch_process(
                agency_batch,
                _process_agency,
                label="maintenance.match_janitor",
            )

    logger.info(
        "Match janitor sweep complete: %s pending, %s missing, %s cold, %s scheduled, %s cache rebuilds, %s cache pruned (%s pages)",
        total_pending,
        total_missing,
        total_cold,
        total_scheduled,
        cache_rebuilds,
        cache_pruned,
        pages_processed,
    )
    return {
        "pending": total_pending,
        "missing": total_missing,
        "cold": total_cold,
        "scheduled": total_scheduled,
        "cache_rebuilds": cache_rebuilds,
        "cache_pruned": cache_pruned,
        "claim_recoveries": claim_recoveries,
        "pages": pages_processed,
    }


__all__ = ["match_pairs_janitor_task"]
