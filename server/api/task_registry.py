"""Task ownership registry for WebSocket access control."""

from __future__ import annotations

from django.core.cache import cache

_TASK_TTL_SEC = 60 * 60 * 12  # 12 hours


def register_task(task_id: str, *, agency_id: int | None, user_id: int | None = None) -> None:
    if not task_id:
        return
    payload = {"agency_id": agency_id, "user_id": user_id}
    cache.set(_task_key(task_id), payload, timeout=_TASK_TTL_SEC)


def get_task_owner(task_id: str) -> dict[str, object] | None:
    if not task_id:
        return None
    payload = cache.get(_task_key(task_id))
    return payload if isinstance(payload, dict) else None


def _task_key(task_id: str) -> str:
    return f"task-owner:{task_id}"


__all__ = ["register_task", "get_task_owner"]
