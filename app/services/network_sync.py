"""Background connectivity sync and status helpers for resilient client behavior."""

from __future__ import annotations

import logging
from typing import Any

from app.services.agency_media import flush_pending_media_uploads
from app.services.api_client import api_get, flush_pending_api_mutations, get_api_circuit_snapshot
from app.services.api_write_queue import failed_api_mutation_count, pending_api_mutation_count
from app.services.offline_account_scope import get_active_account_scope
from app.services.offline_conflicts import needs_review_count
from app.services.offline_op_log import list_operations
from app.services.offline_state import get_offline_mode
from app.services.upload_queue import pending_media_upload_count

_API_SYNC_BATCH_LIMIT = 10
logger = logging.getLogger(__name__)


def _safe_active_scope() -> Any:
    try:
        return get_active_account_scope()
    except Exception:
        logger.debug("Account scope lookup failed during network status refresh", exc_info=True)
        return None


def get_network_status_snapshot(*, sync_in_flight: bool = False) -> dict[str, Any]:
    """Return a small status snapshot for UI and reconnect logic."""
    offline = get_offline_mode()
    scope = _safe_active_scope()
    store_error = False
    operations = []
    pending_api = 0
    pending_media = 0
    failed_api = 0
    review_count = 0
    if scope is not None:
        try:
            operations = list_operations(scope=scope)
            pending_api = pending_api_mutation_count(scope=scope)
            pending_media = pending_media_upload_count(scope=scope)
            failed_api = failed_api_mutation_count(scope=scope)
            review_count = needs_review_count(scope=scope)
        except OSError:
            store_error = True
            logger.debug(
                "Offline sync store temporarily unavailable during status refresh", exc_info=True
            )
    pending_ops = len(operations)
    pending_creates = sum(1 for op in operations if op.op_type == "create")
    blocked_ops = sum(1 for op in operations if op.status == "blocked")
    circuit = get_api_circuit_snapshot()
    state = "online"
    if offline:
        state = "offline"
    elif store_error:
        state = "error"
    elif failed_api > 0 or review_count > 0:
        state = "error"
    elif sync_in_flight:
        state = "syncing"
    elif pending_ops > 0 or pending_media > 0:
        state = "pending"
    elif str(circuit.get("state") or "") != "closed":
        state = "degraded"
    return {
        "state": state,
        "offline": offline,
        "pending_api": pending_api,
        "pending_media": pending_media,
        "pending_ops": pending_ops,
        "pending_creates": pending_creates,
        "failed_api": failed_api,
        "needs_review": review_count,
        "blocked_ops": blocked_ops,
        "pending_total": pending_ops + pending_media,
        "circuit": circuit,
        "sync_in_flight": sync_in_flight,
        "store_error": store_error,
    }


def flush_pending_network_work() -> dict[str, Any]:
    """Replay queued data/media work when connectivity is available."""
    summary = get_network_status_snapshot(sync_in_flight=False)
    scope = _safe_active_scope()
    if bool(summary.get("offline")):
        summary.update({"flushed_api": 0, "flushed_media": 0})
        return summary

    circuit_state = str(summary.get("circuit", {}).get("state") or "")
    if scope is not None and (
        circuit_state != "closed" or int(summary.get("pending_media") or 0) > 0
    ):
        api_get("/health")

    api_result = flush_pending_api_mutations(limit=_API_SYNC_BATCH_LIMIT, scope=scope)
    media_result = flush_pending_media_uploads(scope=scope)
    refreshed = get_network_status_snapshot(sync_in_flight=False)
    refreshed.update(
        {
            "flushed_api": int(api_result.get("flushed") or 0),
            "discarded_api": int(api_result.get("discarded") or 0),
            "flushed_media": int(media_result),
        }
    )
    return refreshed


__all__ = ["flush_pending_network_work", "get_network_status_snapshot"]
