"""
Match pair computation tasks.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from typing import TYPE_CHECKING

from core.data import demande_repository as demande_data
from core.data import match_candidates as match_candidates_data
from core.data import match_pairs as match_pairs_data
from core.data import match_rebuild_state
from core.utils.row_casts import row_int
from server.async_task_identity import build_async_task_identity
from server.immoapp_server.observability import business_span
from server.services import match_jobs, match_runtime_profile, runtime_pressure_tripwire

from .adaptive_batch import adaptive_batch_process
from .match_pairs_compute import (
    DEFAULT_MATCH_PAIRS_LIMIT,
    compute_match_pairs_for_demande,
    compute_match_pairs_for_demandes,
    resolve_wilaya_id,
)
from .tasks_core import (
    logger,
    match_compute_context,
    match_pairs_rebuild_lock,
    normalize_pairs_limit,
    require_agency_id,
    task_decorator,
)

if TYPE_CHECKING:
    from server.pg.uow import PgUnitOfWork


def _demande_batch_size() -> int:
    # Base defaults still come from IMMOAPP_MATCH_PAIRS_DEMANDE_BATCH_SIZE via the runtime profile.
    return int(match_runtime_profile.resolve_effective_profile().demande_batch_size)


def _demande_stream_page_size() -> int:
    raw = os.environ.get("IMMOAPP_MATCH_PAIRS_DEMANDE_STREAM_PAGE_SIZE", "500").strip()
    try:
        value = int(raw)
    except ValueError:
        value = 500
    return max(50, min(value, 5000))


def _demande_enqueue_task_batch_size() -> int:
    raw = os.environ.get("IMMOAPP_MATCH_PAIRS_ENQUEUE_BATCH_SIZE", "200").strip()
    try:
        value = int(raw)
    except ValueError:
        value = 200
    return max(1, min(value, 1000))


def _demande_task_chunk_size() -> int:
    return int(match_runtime_profile.resolve_effective_profile().task_chunk_size)


def _demande_full_sql_threshold() -> int:
    return int(match_runtime_profile.resolve_effective_profile().full_sql_threshold)


def _demande_flush_max_batches() -> int:
    raw = os.environ.get("IMMOAPP_MATCH_PAIRS_FLUSH_MAX_BATCHES", "8").strip()
    try:
        value = int(raw)
    except ValueError:
        value = 8
    return max(1, min(value, 64))


def _publish_match_tripwire_from_exception(exc: Exception) -> None:
    sqlstate = str(getattr(exc, "sqlstate", "") or "").strip()
    text = str(exc).lower()
    if sqlstate == "57014" or "statement timeout" in text:
        runtime_pressure_tripwire.publish_override(profile="red", reason="red_statement_timeout")
    elif sqlstate in {"55P03", "40P01"} or "lock timeout" in text or "deadlock" in text:
        runtime_pressure_tripwire.publish_override(profile="red", reason="red_lock_timeout")


def _publish_match_tripwire_from_db_time(duration_seconds: float) -> None:
    try:
        yellow_seconds = float(
            os.environ.get("IMMOAPP_MATCH_TRIPWIRE_YELLOW_SECONDS", "1.5") or 1.5
        )
    except ValueError:
        yellow_seconds = 1.5
    try:
        red_seconds = float(os.environ.get("IMMOAPP_MATCH_TRIPWIRE_RED_SECONDS", "4.0") or 4.0)
    except ValueError:
        red_seconds = 4.0
    if duration_seconds >= max(yellow_seconds, red_seconds):
        runtime_pressure_tripwire.publish_override(profile="red", reason="red_sub_batch_db_time")
    elif duration_seconds >= max(0.25, yellow_seconds):
        runtime_pressure_tripwire.publish_override(
            profile="yellow",
            reason="yellow_sub_batch_db_time",
        )


def _cascade_count_cache_refresh(
    *,
    schema: str | None,
    agency_id: int,
    correlation_id: str | None,
    actor_id: int | None,
    actor_role: str | None,
    default_reason: str,
) -> None:
    try:
        from .tasks_match_cache import rebuild_match_cache_dirty

        rebuild_match_cache_dirty.delay(
            **build_async_task_identity(
                schema=schema,
                agency_id=agency_id,
                correlation_id=correlation_id or default_reason,
                actor_id=actor_id,
                actor_role=actor_role,
            )
        )
    except Exception:
        logger.warning("Post-rebuild count cache cascade failed", exc_info=True)


def _demande_batches(demande_ids: list[int], *, batch_size: int) -> list[list[int]]:
    if not demande_ids:
        return []
    return [demande_ids[i : i + batch_size] for i in range(0, len(demande_ids), batch_size)]


def _compute_demande_chunks(
    *,
    get_uow: Callable[[], PgUnitOfWork],
    demande_ids: list[int],
    limit: int | None,
    label: str,
) -> tuple[int, int]:
    normalized_ids = sorted({int(v) for v in (demande_ids or []) if int(v) > 0})
    if not normalized_ids:
        return 0, 0
    if len(normalized_ids) <= _demande_full_sql_threshold():
        started_at = time.monotonic()
        with get_uow().transaction() as session:
            result = compute_match_pairs_for_demandes(session, normalized_ids, limit=limit)
        _publish_match_tripwire_from_db_time(time.monotonic() - started_at)
        return result

    stored_total = 0
    candidate_total = 0
    demande_batches = _demande_batches(
        normalized_ids,
        batch_size=_demande_batch_size(),
    )

    def _process_demande_batch(batch_demande_ids: list[int]) -> None:
        nonlocal stored_total, candidate_total
        started_at = time.monotonic()
        with get_uow().transaction() as session:
            stored, candidates = compute_match_pairs_for_demandes(
                session,
                batch_demande_ids,
                limit=limit,
            )
        _publish_match_tripwire_from_db_time(time.monotonic() - started_at)
        stored_total += int(stored)
        candidate_total += int(candidates)

    adaptive_batch_process(
        demande_batches,
        _process_demande_batch,
        label=label,
    )
    return stored_total, candidate_total


@task_decorator()
def rebuild_match_pairs_for_demande(
    _task: object,
    demande_id: int,
    schema: str | None = None,
    agency_id: int | None = None,
    limit: int = 100,
    correlation_id: str | None = None,
    actor_id: int | None = None,
    actor_role: str | None = None,
) -> dict[str, object]:
    """Rebuild precomputed match pairs for a single demande."""
    with business_span(
        "matcher.task.rebuild_pairs_for_demande",
        attributes={
            "match.demande_id": demande_id,
            "task.limit": limit,
            "task.schema": schema,
            "task.agency_id": agency_id,
        },
    ) as span:
        agency_id = require_agency_id(agency_id, "rebuild_match_pairs_for_demande")
        normalized_limit = normalize_pairs_limit(limit)
        if normalized_limit is not None:
            normalized_limit = max(1, min(normalized_limit, DEFAULT_MATCH_PAIRS_LIMIT))
        with match_compute_context(
            schema,
            agency_id,
            actor_id=actor_id,
            actor_role=actor_role,
            correlation_id=correlation_id,
        ):
            needs_rerun = False
            result: dict[str, object] | None = None
            with match_pairs_rebuild_lock(schema, agency_id, str(demande_id)) as locked:
                if not locked:
                    logger.info("Match pair rebuild skipped: lock already held")
                    span.set_attribute("task.lock_acquired", False)
                    return {"demande_id": demande_id, "stored": 0, "skipped": True}
                span.set_attribute("task.lock_acquired", True)

                from server.pg.uow import get_uow

                with get_uow().session() as session:
                    start_gen = match_rebuild_state.get_generation(
                        session, scope="demande", scope_id=demande_id
                    )

                with get_uow().transaction() as session:
                    stored, total_count = compute_match_pairs_for_demande(
                        session,
                        demande_id,
                        limit=normalized_limit,
                    )
                with get_uow().transaction() as session:
                    needs_rerun = match_rebuild_state.complete_rebuild(
                        session,
                        scope="demande",
                        scope_id=demande_id,
                        start_generation=start_gen,
                    )
                logger.info(
                    "Match pairs rebuilt for demande %s (%s/%s stored)",
                    demande_id,
                    stored,
                    total_count,
                )
                span.set_attribute("match.pairs_stored", stored)
                span.set_attribute("match.candidates_total", total_count)
                span.set_attribute("task.needs_rerun", needs_rerun)
                result = {"demande_id": demande_id, "stored": stored, "total": total_count}

            if needs_rerun:
                rebuild_match_pairs_for_demande.apply_async(
                    args=(demande_id,),
                    kwargs={
                        **build_async_task_identity(
                            schema=schema,
                            agency_id=agency_id,
                            correlation_id=correlation_id,
                            actor_id=actor_id,
                            actor_role=actor_role,
                        ),
                        "limit": limit,
                    },
                    countdown=5,
                )
            _cascade_count_cache_refresh(
                schema=schema,
                agency_id=agency_id,
                correlation_id=correlation_id,
                actor_id=actor_id,
                actor_role=actor_role,
                default_reason="rebuild:cache",
            )
            return result or {"demande_id": demande_id, "stored": 0, "total": 0}


@task_decorator()
def rebuild_match_pairs_for_demandes_batch(
    _task: object,
    demande_ids: list[int],
    schema: str | None = None,
    agency_id: int | None = None,
    limit: int = 100,
    correlation_id: str | None = None,
    actor_id: int | None = None,
    actor_role: str | None = None,
) -> dict[str, object]:
    """Rebuild precomputed match pairs for multiple demandes in one task."""
    agency_id = require_agency_id(agency_id, "rebuild_match_pairs_for_demandes_batch")
    normalized_ids = sorted({int(v) for v in (demande_ids or []) if int(v) > 0})
    if not normalized_ids:
        return {"demande_ids": 0, "stored": 0, "total_candidates": 0}

    normalized_limit = normalize_pairs_limit(limit)
    if normalized_limit is not None:
        normalized_limit = max(1, min(normalized_limit, DEFAULT_MATCH_PAIRS_LIMIT))

    with business_span(
        "matcher.task.rebuild_pairs_for_demandes_batch",
        attributes={
            "task.demande_count": len(normalized_ids),
            "task.schema": schema,
            "task.agency_id": agency_id,
        },
    ) as span:
        with match_compute_context(
            schema,
            agency_id,
            actor_id=actor_id,
            actor_role=actor_role,
            correlation_id=correlation_id,
        ):
            scope_key = (
                f"demande_batch:{normalized_ids[0]}:{normalized_ids[-1]}:{len(normalized_ids)}"
            )
            with match_pairs_rebuild_lock(schema, agency_id, scope_key) as locked:
                if not locked:
                    logger.info("Demande batch rebuild skipped: lock already held")
                    span.set_attribute("task.lock_acquired", False)
                    return {
                        "demande_ids": len(normalized_ids),
                        "stored": 0,
                        "total_candidates": 0,
                        "skipped": True,
                    }
                span.set_attribute("task.lock_acquired", True)

                from server.pg.uow import get_uow

                with get_uow().session() as session:
                    generation_rows = session.execute(
                        """
                            SELECT scope_id, generation
                            FROM match_rebuild_state
                            WHERE scope = 'demande'
                              AND scope_id = ANY(%s)
                            """,
                        (normalized_ids,),
                    ).fetchall()
                start_generations = {
                    row_int(row, "scope_id"): row_int(row, "generation")
                    for row in generation_rows
                    if row.get("scope_id") is not None
                }
                stored_total, candidate_total = _compute_demande_chunks(
                    get_uow=get_uow,
                    demande_ids=normalized_ids,
                    limit=normalized_limit,
                    label=f"match_pairs_demande_batch_{len(normalized_ids)}",
                )

                with get_uow().transaction() as session:
                    rerun_ids = match_rebuild_state.complete_rebuild_batch(
                        session,
                        scope="demande",
                        start_generations={
                            demande_id: start_generations.get(demande_id, 0)
                            for demande_id in normalized_ids
                        },
                    )

            if rerun_ids:
                rebuild_match_pairs_for_demandes_batch.apply_async(
                    args=(sorted(set(rerun_ids)),),
                    kwargs={
                        **build_async_task_identity(
                            schema=schema,
                            agency_id=agency_id,
                            correlation_id=correlation_id,
                            actor_id=actor_id,
                            actor_role=actor_role,
                        ),
                        "limit": limit,
                    },
                    countdown=5,
                )

            # Cascade: mark affected clients' count cache as dirty so
            # match_counts_cache is updated immediately, not at next janitor.
            _cascade_count_cache_refresh(
                schema=schema,
                agency_id=agency_id,
                correlation_id=correlation_id,
                actor_id=actor_id,
                actor_role=actor_role,
                default_reason="batch_rebuild:cache",
            )

            span.set_attribute("match.pairs_stored", stored_total)
            span.set_attribute("match.candidates_total", candidate_total)
            span.set_attribute("task.needs_rerun_count", len(rerun_ids))
            return {
                "demande_ids": len(normalized_ids),
                "stored": stored_total,
                "total_candidates": candidate_total,
                "rerun_demande_ids": len(rerun_ids),
            }


@task_decorator()
def flush_rebuild_demande_pairs_queue(
    _task: object,
    *,
    schema: str | None = None,
    agency_id: int | None = None,
    correlation_id: str | None = None,
    actor_id: int | None = None,
    actor_role: str | None = None,
) -> dict[str, object]:
    """Drain queued demande rebuild requests into batched pair-compute tasks."""
    agency_id = require_agency_id(agency_id, "flush_rebuild_demande_pairs_queue")
    task_kwargs: dict[str, object] = build_async_task_identity(
        schema=schema,
        agency_id=agency_id,
        correlation_id=correlation_id,
        actor_id=actor_id,
        actor_role=actor_role,
    )
    with business_span(
        "matcher.task.flush_rebuild_pairs_queue",
        attributes={
            "task.schema": schema,
            "task.agency_id": agency_id,
        },
    ) as span:
        queued_demande_ids = 0
        batches_scheduled = 0
        try:
            with match_compute_context(
                schema,
                agency_id,
                actor_id=actor_id,
                actor_role=actor_role,
                correlation_id=correlation_id,
            ):
                with match_pairs_rebuild_lock(schema, agency_id, "demande_flush_queue") as locked:
                    if not locked:
                        span.set_attribute("task.lock_acquired", False)
                        return {
                            "agency_id": agency_id,
                            "demande_ids": 0,
                            "batches": 0,
                            "skipped": True,
                        }
                    span.set_attribute("task.lock_acquired", True)
                    queued_ids: list[int] = []
                    for _ in range(_demande_flush_max_batches()):
                        batch_demande_ids = match_jobs.dequeue_demande_rebuild_batch(
                            agency_id=agency_id,
                            batch_size=_demande_enqueue_task_batch_size(),
                        )
                        if not batch_demande_ids:
                            break
                        queued_ids.extend(batch_demande_ids)
                    normalized_queued_ids = sorted({int(v) for v in queued_ids if int(v) > 0})
                    queued_demande_ids = len(normalized_queued_ids)
                    for task_demande_ids in _demande_batches(
                        normalized_queued_ids,
                        batch_size=_demande_task_chunk_size(),
                    ):
                        rebuild_match_pairs_for_demandes_batch.apply_async(
                            args=(task_demande_ids,),
                            kwargs=task_kwargs,
                        )
                        batches_scheduled += 1
        finally:
            match_jobs.clear_demande_rebuild_flush(agency_id=agency_id)

        follow_up_requested = match_jobs.pop_demande_rebuild_flush_requested(agency_id=agency_id)
        remaining = match_jobs.count_pending_demande_rebuilds(agency_id=agency_id)
        if remaining > 0 or follow_up_requested:
            match_jobs.schedule_demande_rebuild_flush(kwargs=task_kwargs)

        span.set_attribute("task.demande_ids", queued_demande_ids)
        span.set_attribute("task.batches_scheduled", batches_scheduled)
        span.set_attribute("task.remaining_demande_ids", remaining)
        span.set_attribute("task.follow_up_requested", follow_up_requested)
        return {
            "agency_id": agency_id,
            "demande_ids": queued_demande_ids,
            "batches": batches_scheduled,
            "remaining": remaining,
            "follow_up_requested": follow_up_requested,
        }


@task_decorator()
def expand_match_pairs_for_demande(
    _task: object,
    demande_id: int,
    schema: str | None = None,
    agency_id: int | None = None,
    correlation_id: str | None = None,
    actor_id: int | None = None,
    actor_role: str | None = None,
) -> dict[str, object]:
    """Rebuild all match pairs for a demande (no limit) for pagination."""
    agency_id = require_agency_id(agency_id, "expand_match_pairs_for_demande")
    with match_compute_context(
        schema,
        agency_id,
        actor_id=actor_id,
        actor_role=actor_role,
        correlation_id=correlation_id,
    ):
        with match_pairs_rebuild_lock(schema, agency_id, f"expand:{demande_id}") as locked:
            if not locked:
                logger.info("Match pair expansion skipped: lock already held")
                return {"demande_id": demande_id, "stored": 0, "skipped": True}

            from server.pg.uow import get_uow

            with get_uow().transaction() as session:
                stored, total_count = compute_match_pairs_for_demande(
                    session, demande_id, limit=None
                )
            logger.info(
                "Match pairs expanded for demande %s (%s/%s stored)",
                demande_id,
                stored,
                total_count,
            )
            _cascade_count_cache_refresh(
                schema=schema,
                agency_id=agency_id,
                correlation_id=correlation_id,
                actor_id=actor_id,
                actor_role=actor_role,
                default_reason="expand:cache",
            )
            return {"demande_id": demande_id, "stored": stored, "total": total_count}


@task_decorator()
def rebuild_match_pairs_for_wilaya(
    _task: object,
    wilaya_id: int | str | None = None,
    *,
    wilaya: str | None = None,
    schema: str | None = None,
    agency_id: int | None = None,
    correlation_id: str | None = None,
    actor_id: int | None = None,
    actor_role: str | None = None,
) -> dict[str, object]:
    """Rebuild precomputed match pairs for demandes in a wilaya."""
    agency_id = require_agency_id(agency_id, "rebuild_match_pairs_for_wilaya")
    with match_compute_context(
        schema,
        agency_id,
        actor_id=actor_id,
        actor_role=actor_role,
        correlation_id=correlation_id,
    ):
        from server.pg.uow import get_uow

        with get_uow().session() as session:
            resolved_id = resolve_wilaya_id(session, wilaya_id, wilaya)
        if not resolved_id:
            return {"wilaya_id": wilaya_id, "demande_ids": 0, "stored": 0, "skipped": True}

        needs_rerun = False
        result: dict[str, object] | None = None
        with match_pairs_rebuild_lock(schema, agency_id, f"wilaya:{resolved_id}") as locked:
            if not locked:
                logger.info("Wilaya match pair rebuild skipped: lock already held")
                return {"wilaya_id": resolved_id, "demande_ids": 0, "stored": 0, "skipped": True}

            with get_uow().session() as session:
                start_gen = match_rebuild_state.get_generation(
                    session, scope="wilaya", scope_id=resolved_id
                )
            stored_total = 0
            total_demande = 0
            stream_page_size = _demande_stream_page_size()

            with get_uow().session() as session:
                for demande_page in demande_data.iter_demande_ids_for_wilaya(
                    session,
                    resolved_id,
                    page_size=stream_page_size,
                ):
                    if not demande_page:
                        continue
                    total_demande += len(demande_page)
                    stored, _candidate_total = _compute_demande_chunks(
                        get_uow=get_uow,
                        demande_ids=demande_page,
                        limit=DEFAULT_MATCH_PAIRS_LIMIT,
                        label=f"match_pairs_wilaya_{resolved_id}",
                    )
                    stored_total += stored
            logger.info(
                "Match pairs rebuilt for wilaya %s (%s demandes)",
                resolved_id,
                total_demande,
            )
            with get_uow().transaction() as session:
                needs_rerun = match_rebuild_state.complete_rebuild(
                    session,
                    scope="wilaya",
                    scope_id=resolved_id,
                    start_generation=start_gen,
                )
            result = {
                "wilaya_id": resolved_id,
                "demande_ids": total_demande,
                "stored": stored_total,
            }
        if needs_rerun:
            rebuild_match_pairs_for_wilaya.apply_async(
                args=(resolved_id,),
                kwargs=build_async_task_identity(
                    schema=schema,
                    agency_id=agency_id,
                    correlation_id=correlation_id,
                    actor_id=actor_id,
                    actor_role=actor_role,
                ),
                countdown=5,
            )
        _cascade_count_cache_refresh(
            schema=schema,
            agency_id=agency_id,
            correlation_id=correlation_id,
            actor_id=actor_id,
            actor_role=actor_role,
            default_reason="wilaya_rebuild:cache",
        )
        return result or {"wilaya_id": resolved_id, "demande_ids": 0, "stored": 0}


@task_decorator()
def rebuild_match_pairs_for_client(
    _task: object,
    client_id: int,
    *,
    include_deleted: bool = False,
    schema: str | None = None,
    agency_id: int | None = None,
    correlation_id: str | None = None,
    actor_id: int | None = None,
    actor_role: str | None = None,
) -> dict[str, object]:
    """Rebuild precomputed match pairs for all demandes owned by a client."""
    agency_id = require_agency_id(agency_id, "rebuild_match_pairs_for_client")
    with match_compute_context(
        schema,
        agency_id,
        actor_id=actor_id,
        actor_role=actor_role,
        correlation_id=correlation_id,
    ):
        from server.pg.uow import get_uow

        needs_rerun = False
        result: dict[str, object] | None = None
        with match_pairs_rebuild_lock(schema, agency_id, f"client:{client_id}") as locked:
            if not locked:
                logger.info("Client match pair rebuild skipped: lock already held")
                return {"client_id": client_id, "demande_ids": 0, "stored": 0, "skipped": True}

            with get_uow().session() as session:
                start_gen = match_rebuild_state.get_generation(
                    session, scope="client", scope_id=client_id
                )
            stored_total = 0
            total_demande = 0
            stream_page_size = _demande_stream_page_size()

            with get_uow().session() as session:
                for demande_page in demande_data.iter_demande_ids_for_client(
                    session,
                    client_id,
                    include_deleted=include_deleted,
                    page_size=stream_page_size,
                ):
                    if not demande_page:
                        continue
                    total_demande += len(demande_page)
                    stored, _candidate_total = _compute_demande_chunks(
                        get_uow=get_uow,
                        demande_ids=demande_page,
                        limit=DEFAULT_MATCH_PAIRS_LIMIT,
                        label=f"match_pairs_client_{client_id}",
                    )
                    stored_total += stored
            logger.info(
                "Match pairs rebuilt for client %s (%s demandes)",
                client_id,
                total_demande,
            )
            with get_uow().transaction() as session:
                needs_rerun = match_rebuild_state.complete_rebuild(
                    session,
                    scope="client",
                    scope_id=client_id,
                    start_generation=start_gen,
                )
            result = {"client_id": client_id, "demande_ids": total_demande, "stored": stored_total}

        if needs_rerun:
            rebuild_match_pairs_for_client.apply_async(
                args=(client_id,),
                kwargs={
                    **build_async_task_identity(
                        schema=schema,
                        agency_id=agency_id,
                        correlation_id=correlation_id,
                        actor_id=actor_id,
                        actor_role=actor_role,
                    ),
                    "include_deleted": include_deleted,
                },
                countdown=5,
            )
        _cascade_count_cache_refresh(
            schema=schema,
            agency_id=agency_id,
            correlation_id=correlation_id,
            actor_id=actor_id,
            actor_role=actor_role,
            default_reason="client_rebuild:cache",
        )
        return result or {"client_id": client_id, "demande_ids": 0, "stored": 0}


@task_decorator()
def rebuild_match_pairs_for_offer(
    _task: object,
    offer_id: int,
    *,
    demande_ids_hint: list[int] | None = None,
    schema: str | None = None,
    agency_id: int | None = None,
    correlation_id: str | None = None,
    actor_id: int | None = None,
    actor_role: str | None = None,
) -> dict[str, object]:
    """Rebuild precomputed match pairs for demandes affected by one offer."""
    agency_id = require_agency_id(agency_id, "rebuild_match_pairs_for_offer")
    with match_compute_context(
        schema,
        agency_id,
        actor_id=actor_id,
        actor_role=actor_role,
        correlation_id=correlation_id,
    ):
        from server.pg.uow import get_uow

        with get_uow().session() as session:
            demande_ids = demande_data.get_demande_ids_for_offer(session, offer_id)
            hinted_ids = [int(v) for v in (demande_ids_hint or []) if int(v) > 0]
            if hinted_ids:
                demande_ids = sorted(set(demande_ids).union(hinted_ids))

        needs_rerun = False
        result: dict[str, object] | None = None
        with match_pairs_rebuild_lock(schema, agency_id, f"offer:{offer_id}") as locked:
            if not locked:
                logger.info("Offer match pair rebuild skipped: lock already held")
                return {"offer_id": offer_id, "demande_ids": 0, "stored": 0, "skipped": True}

            with get_uow().session() as session:
                start_gen = match_rebuild_state.get_generation(
                    session, scope="offer", scope_id=offer_id
                )
            with get_uow().transaction() as session:
                match_candidates_data.clear_candidates_for_offer(session, offer_id)
                match_pairs_data.clear_pairs_for_offer(session, offer_id)
            stored_total = 0
            total_demande = len(demande_ids)
            stored_total, _candidate_total = _compute_demande_chunks(
                get_uow=get_uow,
                demande_ids=demande_ids,
                limit=DEFAULT_MATCH_PAIRS_LIMIT,
                label=f"match_pairs_offer_{offer_id}",
            )
            logger.info(
                "Match pairs rebuilt for offer %s (%s demandes)",
                offer_id,
                total_demande,
            )
            with get_uow().transaction() as session:
                needs_rerun = match_rebuild_state.complete_rebuild(
                    session,
                    scope="offer",
                    scope_id=offer_id,
                    start_generation=start_gen,
                )
            result = {"offer_id": offer_id, "demande_ids": total_demande, "stored": stored_total}

        if needs_rerun:
            rebuild_match_pairs_for_offer.apply_async(
                args=(offer_id,),
                kwargs={
                    **build_async_task_identity(
                        schema=schema,
                        agency_id=agency_id,
                        correlation_id=correlation_id,
                        actor_id=actor_id,
                        actor_role=actor_role,
                    ),
                    "demande_ids_hint": demande_ids,
                },
                countdown=5,
            )
        _cascade_count_cache_refresh(
            schema=schema,
            agency_id=agency_id,
            correlation_id=correlation_id,
            actor_id=actor_id,
            actor_role=actor_role,
            default_reason="offer_rebuild:cache",
        )
        return result or {"offer_id": offer_id, "demande_ids": 0, "stored": 0}


@task_decorator()
def rebuild_match_pairs_for_offers_batch(
    _task: object,
    offer_ids: list[int],
    *,
    schema: str | None = None,
    agency_id: int | None = None,
    correlation_id: str | None = None,
    actor_id: int | None = None,
    actor_role: str | None = None,
) -> dict[str, object]:
    agency_id = require_agency_id(agency_id, "rebuild_match_pairs_for_offers_batch")
    normalized_ids = sorted({int(v) for v in (offer_ids or []) if int(v) > 0})
    if not normalized_ids:
        return {"offer_ids": 0, "stored": 0, "demande_ids": 0}
    stored_total = 0
    demande_total = 0
    for offer_id in normalized_ids:
        result = rebuild_match_pairs_for_offer.run(
            offer_id,
            schema=schema,
            agency_id=agency_id,
            correlation_id=correlation_id,
            actor_id=actor_id,
            actor_role=actor_role,
        )
        stored_total += int(result.get("stored", 0) or 0)
        demande_total += int(result.get("demande_ids", 0) or 0)
    return {
        "offer_ids": len(normalized_ids),
        "stored": stored_total,
        "demande_ids": demande_total,
    }


__all__ = [
    "flush_rebuild_demande_pairs_queue",
    "rebuild_match_pairs_for_demande",
    "rebuild_match_pairs_for_demandes_batch",
    "expand_match_pairs_for_demande",
    "rebuild_match_pairs_for_wilaya",
    "rebuild_match_pairs_for_client",
    "rebuild_match_pairs_for_offer",
    "rebuild_match_pairs_for_offers_batch",
]
