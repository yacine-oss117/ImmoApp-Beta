"""Service wrapper for core.data.match_cache using Unit of Work."""

from __future__ import annotations

from app.models_cast import as_int
from app.services.api_client import api_get, api_post, as_dict
from app.services.task_status import get_task_status
from app.utils.task_push import wait_for_task_notification

__all__ = [
    "get_cached_count",
    "get_cached_counts_batch",
    "get_dirty_client_ids",
    "is_cache_clean",
    "mark_all_dirty",
    "mark_client_dirty",
    "mark_clients_in_wilaya_dirty",
    "store_count",
    "store_counts_batch",
    "init_cache_table",
    "clear_all",
    "get_missing_client_ids",
]


def _wait_for_task_counts(task_id: str, *, max_wait_sec: float = 300.0) -> dict[int, int]:
    payload = wait_for_task_notification(task_id, timeout_sec=min(30.0, max_wait_sec))
    if isinstance(payload, dict):
        status = payload.get("status")
        if status == "SUCCESS":
            result_payload = payload.get("result")
            if result_payload is not None:
                return _parse_counts(result_payload)
            return _parse_counts(get_task_status(task_id).get("result"))
        if status in {"FAILURE", "REVOKED"}:
            return {}

    import time

    started = time.monotonic()
    while True:
        payload = get_task_status(task_id)
        status = payload.get("status")
        if status == "SUCCESS":
            return _parse_counts(payload.get("result"))
        if status in {"FAILURE", "REVOKED"}:
            return {}
        if time.monotonic() - started >= max_wait_sec:
            return {}
        time.sleep(0.5)


def _parse_counts(payload: object) -> dict[int, int]:
    data = as_dict(payload)
    raw = data.get("counts") if "counts" in data else data
    if not isinstance(raw, dict):
        return {}
    result: dict[int, int] = {}
    for key, value in raw.items():
        try:
            key_int = int(key)
        except (TypeError, ValueError):
            continue
        result[key_int] = as_int(value, default=0)
    return result


def get_cached_count(client_id: int) -> int | None:
    """Get the cached match count for a single client, or None if not cached."""
    payload = as_dict(api_post("/cache/match/get", {"ids": [client_id]}))
    raw = payload.get("counts")
    if not isinstance(raw, dict):
        return None
    key = str(client_id)
    if key not in raw:
        return None
    return as_int(raw.get(key), default=0)


def get_cached_counts_batch(client_ids: list[int]) -> dict[int, int]:
    """Get cached match counts for a batch of clients as {client_id: count}."""
    if not client_ids:
        return {}
    payload = as_dict(api_post("/cache/match/get", {"ids": client_ids}))
    raw = payload.get("counts")
    if not isinstance(raw, dict):
        return {}
    result: dict[int, int] = {}
    for key, value in raw.items():
        try:
            key_int = int(key)
        except (TypeError, ValueError):
            continue
        result[key_int] = as_int(value, default=0)
    return result


def get_dirty_client_ids() -> list[int]:
    """Get list of client IDs whose cached counts need recomputation."""
    payload = as_dict(api_get("/cache/match/dirty"))
    ids = payload.get("ids")
    if not isinstance(ids, list):
        return []
    result: list[int] = []
    for value in ids:
        try:
            result.append(int(value))
        except (TypeError, ValueError):
            continue
    return result


def get_missing_client_ids() -> list[int]:
    """Get list of client IDs that have no cached count at all."""
    payload = as_dict(api_get("/cache/match/missing"))
    ids = payload.get("ids")
    if not isinstance(ids, list):
        return []
    result: list[int] = []
    for value in ids:
        try:
            result.append(int(value))
        except (TypeError, ValueError):
            continue
    return result


def is_cache_clean() -> bool:
    """Check if all match counts in cache are up-to-date (not dirty)."""
    payload = as_dict(api_get("/cache/match/status"))
    return bool(payload.get("is_clean"))


def mark_all_dirty() -> None:
    """Mark all cached client counts as dirty, requiring recomputation."""
    api_post("/cache/match/mark-all")


def mark_client_dirty(client_id: int) -> None:
    """Mark a single client's cached count as dirty."""
    api_post("/cache/match/mark-client", {"client_id": client_id})


def mark_clients_in_wilaya_dirty(wilaya: str | None = None, wilaya_id: int | None = None) -> None:
    """Mark all clients in a given wilaya as dirty."""
    from app.services.lookup_service import get_wilaya_id

    resolved_id = wilaya_id
    if resolved_id is None and wilaya:
        resolved_id = get_wilaya_id(wilaya)
    payload: dict[str, object] = {"wilaya_id": resolved_id}
    if wilaya is not None:
        payload["wilaya"] = wilaya
    api_post("/cache/match/mark-wilaya", payload)


def store_count(client_id: int, count: int) -> None:
    """Store a single client's match count in the cache."""
    api_post("/cache/match/count", {"client_id": client_id, "count": count})


def store_counts_batch(counts: dict[int, int]) -> None:
    """Store multiple client match counts in the cache at once."""
    api_post("/cache/match/counts", {"counts": counts})


def init_cache_table() -> None:
    """No-op for API backend (table managed server-side)."""
    return None


def clear_all() -> None:
    """Clear all cached match counts from the server."""
    api_post("/cache/match/clear")
