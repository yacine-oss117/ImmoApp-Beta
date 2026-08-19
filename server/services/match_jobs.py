"""
Service-layer helpers for enqueueing background match jobs.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from django.core.cache import caches

from core.data import match_rebuild_state
from server.async_task_identity import build_context_async_task_identity
from server.pg.uow import (
    use_security_context,
)

logger = logging.getLogger(__name__)


def _demande_enqueue_batch_size() -> int:
    raw = os.environ.get("IMMOAPP_MATCH_PAIRS_ENQUEUE_BATCH_SIZE", "200").strip()
    try:
        value = int(raw)
    except ValueError:
        value = 200
    return max(1, min(value, 1000))


def _demande_task_chunk_size() -> int:
    raw = os.environ.get("IMMOAPP_MATCH_PAIRS_TASK_CHUNK_SIZE", "1000").strip()
    try:
        value = int(raw)
    except ValueError:
        value = 1000
    return max(50, min(value, 5000))


def _demande_enqueue_debounce_seconds() -> int:
    raw = os.environ.get("IMMOAPP_MATCH_PAIRS_ENQUEUE_DEBOUNCE_SECONDS", "1").strip()
    try:
        value = int(raw)
    except ValueError:
        value = 1
    return max(0, min(value, 30))


def _demande_enqueue_queue_ttl_seconds() -> int:
    raw = os.environ.get("IMMOAPP_MATCH_PAIRS_ENQUEUE_QUEUE_TTL_SECONDS", "300").strip()
    try:
        value = int(raw)
    except ValueError:
        value = 300
    return max(30, min(value, 3600))


def _default_cache_client() -> Any | None:
    try:
        cache = caches["default"]
        client = getattr(cache, "client", None)
        if client is None or not hasattr(client, "get_client"):
            return None
        return client.get_client(write=True)
    except Exception:
        return None


def _demande_queue_key(*, agency_id: int) -> str:
    return f"match_pairs:demande_queue:{int(agency_id)}"


def _demande_flush_lock_key(*, agency_id: int) -> str:
    return f"match_pairs:demande_queue_flush:{int(agency_id)}"


def _demande_flush_requested_key(*, agency_id: int) -> str:
    return f"match_pairs:demande_queue_flush_requested:{int(agency_id)}"


def _enqueue_direct_demande_task(demande_id: int, *, kwargs: dict[str, object]) -> None:
    from server.api.tasks import rebuild_match_pairs_for_demande

    rebuild_match_pairs_for_demande.delay(int(demande_id), **kwargs)


def schedule_demande_rebuild_flush(*, kwargs: dict[str, object]) -> bool:
    agency_id = int(kwargs.get("agency_id") or 0)
    if agency_id <= 0:
        return False
    delay_seconds = _demande_enqueue_debounce_seconds()
    cache = caches["default"]
    lock_key = _demande_flush_lock_key(agency_id=agency_id)
    lock_timeout = max(_demande_enqueue_queue_ttl_seconds(), delay_seconds + 30)
    acquired = bool(cache.add(lock_key, "1", timeout=lock_timeout))
    if not acquired:
        cache.set(
            _demande_flush_requested_key(agency_id=agency_id),
            "1",
            timeout=lock_timeout,
        )
        return False
    try:
        from server.api.tasks import flush_rebuild_demande_pairs_queue

        flush_rebuild_demande_pairs_queue.apply_async(
            kwargs=kwargs,
            countdown=delay_seconds,
        )
        return True
    except Exception:
        cache.delete(lock_key)
        raise


def pop_demande_rebuild_flush_requested(*, agency_id: int) -> bool:
    cache = caches["default"]
    key = _demande_flush_requested_key(agency_id=int(agency_id))
    try:
        requested = cache.get(key) is not None
        cache.delete(key)
        return requested
    except Exception:
        logger.warning("Failed to pop demande rebuild follow-up marker", exc_info=True)
        return False


def clear_demande_rebuild_flush(*, agency_id: int) -> None:
    try:
        caches["default"].delete(_demande_flush_lock_key(agency_id=int(agency_id)))
    except Exception:
        logger.warning("Failed to clear demande rebuild flush lock", exc_info=True)


def count_pending_demande_rebuilds(*, agency_id: int) -> int:
    from server.pg.uow import get_uow

    try:
        with use_security_context(agency_id=int(agency_id), is_superuser=False):
            with get_uow().session() as session:
                return max(0, int(match_rebuild_state.count_dispatchable(session, scope="demande")))
    except Exception:
        logger.warning("Failed to count pending demande rebuilds", exc_info=True)
        return 0


def dequeue_demande_rebuild_batch(*, agency_id: int, batch_size: int) -> list[int]:
    from server.pg.uow import get_uow

    try:
        with use_security_context(agency_id=int(agency_id), is_superuser=False):
            with get_uow().transaction() as session:
                return match_rebuild_state.claim_dispatchable_scope_ids(
                    session,
                    scope="demande",
                    limit=max(1, int(batch_size)),
                )
    except Exception:
        logger.warning("Failed to claim demande rebuild queue", exc_info=True)
        return []


def _queue_demande_rebuild_request(demande_id: int, *, kwargs: dict[str, object]) -> bool:
    return _queue_demande_rebuild_requests([int(demande_id)], kwargs=kwargs)


def _queue_demande_rebuild_requests(demande_ids: list[int], *, kwargs: dict[str, object]) -> bool:
    agency_id = int(kwargs.get("agency_id") or 0)
    if agency_id <= 0:
        return False
    normalized_ids = sorted({int(v) for v in (demande_ids or []) if int(v) > 0})
    if not normalized_ids:
        return True
    try:
        schedule_demande_rebuild_flush(kwargs=kwargs)
        return True
    except Exception:
        logger.warning(
            "Failed to queue demande rebuild for batched flush",
            exc_info=True,
        )
        return False


def _task_kwargs(*, agency_id: int | None = None) -> dict[str, object] | None:
    payload = build_context_async_task_identity(agency_id=agency_id)
    if payload is None:
        logger.warning("Skipping match task enqueue: missing agency_id context")
        return None
    return payload


def _record_rebuild_request(scope: str, scope_id: int, *, agency_id: int) -> bool:
    from server.pg.uow import get_uow

    with use_security_context(agency_id=int(agency_id), is_superuser=False):
        with get_uow().transaction() as session:
            return match_rebuild_state.request_rebuild(session, scope=scope, scope_id=scope_id)


def enqueue_rebuild_demande_pairs(demande_id: int, *, agency_id: int | None = None) -> None:
    kwargs = _task_kwargs(agency_id=agency_id)
    if kwargs is None:
        return
    try:
        from server.pg.uow import get_uow

        with use_security_context(agency_id=int(kwargs["agency_id"]), is_superuser=False):
            with get_uow().transaction() as session:
                should_enqueue = match_rebuild_state.request_rebuild(
                    session,
                    scope="demande",
                    scope_id=int(demande_id),
                    debounce_seconds=_demande_enqueue_debounce_seconds(),
                )
        if should_enqueue:
            _queue_demande_rebuild_request(int(demande_id), kwargs=kwargs)
    except Exception:
        logger.warning(
            "Failed to enqueue match pair rebuild for demande %s",
            demande_id,
            exc_info=True,
        )


def enqueue_rebuild_demande_pairs_batch(
    demande_ids: list[int], *, agency_id: int | None = None
) -> None:
    kwargs = _task_kwargs(agency_id=agency_id)
    if kwargs is None:
        return
    normalized_ids = sorted({int(v) for v in (demande_ids or []) if int(v) > 0})
    if not normalized_ids:
        return
    try:
        from server.pg.uow import get_uow

        with use_security_context(agency_id=int(kwargs["agency_id"]), is_superuser=False):
            with get_uow().transaction() as session:
                to_enqueue = match_rebuild_state.request_rebuild_batch(
                    session,
                    scope="demande",
                    scope_ids=normalized_ids,
                    debounce_seconds=_demande_enqueue_debounce_seconds(),
                )
        if not to_enqueue:
            return
        _queue_demande_rebuild_requests(to_enqueue, kwargs=kwargs)
    except Exception:
        logger.warning(
            "Failed to enqueue match pair rebuild batch for %s demandes",
            len(normalized_ids),
            exc_info=True,
        )


def enqueue_rebuild_client_pairs(client_id: int, *, include_deleted: bool = False) -> None:
    kwargs = _task_kwargs()
    if kwargs is None:
        return
    try:
        from server.api.tasks import rebuild_match_pairs_for_client

        should_enqueue = _record_rebuild_request(
            "client",
            int(client_id),
            agency_id=int(kwargs["agency_id"]),
        )
        if should_enqueue:
            rebuild_match_pairs_for_client.delay(
                int(client_id),
                include_deleted=include_deleted,
                **kwargs,
            )
    except Exception:
        logger.warning(
            "Failed to enqueue match pair rebuild for client %s",
            client_id,
            exc_info=True,
        )


def enqueue_rebuild_offer_pairs(
    offer_id: int, *, demande_ids_hint: list[int] | None = None
) -> None:
    kwargs = _task_kwargs()
    if kwargs is None:
        return
    try:
        from server.api.tasks import rebuild_match_pairs_for_offer

        should_enqueue = _record_rebuild_request(
            "offer",
            int(offer_id),
            agency_id=int(kwargs["agency_id"]),
        )
        if should_enqueue:
            rebuild_match_pairs_for_offer.delay(
                int(offer_id),
                demande_ids_hint=demande_ids_hint or [],
                **kwargs,
            )
    except Exception:
        logger.warning(
            "Failed to enqueue match pair rebuild for offer %s",
            offer_id,
            exc_info=True,
        )


def enqueue_rebuild_offer_pairs_batch(
    offer_ids: list[int], *, agency_id: int | None = None
) -> None:
    kwargs = _task_kwargs(agency_id=agency_id)
    if kwargs is None:
        return
    normalized_ids = sorted({int(v) for v in (offer_ids or []) if int(v) > 0})
    if not normalized_ids:
        return
    try:
        from server.api.tasks import rebuild_match_pairs_for_offers_batch
        from server.pg.uow import get_uow

        with use_security_context(agency_id=int(kwargs["agency_id"]), is_superuser=False):
            with get_uow().transaction() as session:
                to_enqueue = match_rebuild_state.request_rebuild_batch(
                    session,
                    scope="offer",
                    scope_ids=normalized_ids,
                )
        if not to_enqueue:
            return
        batch_size = _demande_task_chunk_size()
        for index in range(0, len(to_enqueue), batch_size):
            rebuild_match_pairs_for_offers_batch.delay(
                to_enqueue[index : index + batch_size],
                **kwargs,
            )
    except Exception:
        logger.warning(
            "Failed to enqueue match pair rebuild batch for %s offers",
            len(normalized_ids),
            exc_info=True,
        )


def enqueue_rebuild_wilaya_pairs(wilaya_id: int) -> None:
    if not isinstance(wilaya_id, int) or wilaya_id <= 0:
        return
    kwargs = _task_kwargs()
    if kwargs is None:
        return
    try:
        from server.api.tasks import rebuild_match_pairs_for_wilaya

        should_enqueue = _record_rebuild_request(
            "wilaya",
            int(wilaya_id),
            agency_id=int(kwargs["agency_id"]),
        )
        if should_enqueue:
            rebuild_match_pairs_for_wilaya.delay(int(wilaya_id), **kwargs)
    except Exception:
        logger.warning(
            "Failed to enqueue match pair rebuild for wilaya %s",
            wilaya_id,
            exc_info=True,
        )


__all__ = [
    "clear_demande_rebuild_flush",
    "count_pending_demande_rebuilds",
    "dequeue_demande_rebuild_batch",
    "enqueue_rebuild_demande_pairs",
    "enqueue_rebuild_demande_pairs_batch",
    "enqueue_rebuild_client_pairs",
    "enqueue_rebuild_offer_pairs",
    "enqueue_rebuild_offer_pairs_batch",
    "enqueue_rebuild_wilaya_pairs",
    "pop_demande_rebuild_flush_requested",
    "schedule_demande_rebuild_flush",
]
