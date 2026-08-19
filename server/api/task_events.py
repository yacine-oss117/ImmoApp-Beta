"""Broadcast task completion events over Channels."""

from __future__ import annotations

import logging
from typing import Any

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from server.api.task_registry import get_task_owner

logger = logging.getLogger(__name__)


def notify_task_status(task_id: str, status: str, result: object | None = None) -> None:
    """Send a task status update to WebSocket listeners."""
    if not task_id:
        return
    if not get_task_owner(task_id):
        return
    channel_layer = get_channel_layer()
    if channel_layer is None:
        return

    payload: dict[str, Any] = {"task_id": task_id, "status": status}
    summarized = _summarize_result(result)
    if summarized is not None:
        payload["result"] = summarized

    async_to_sync(channel_layer.group_send)(
        f"task.{task_id}",
        {"type": "task.status", **payload},
    )


def _summarize_result(result: object | None) -> object | None:
    if result is None:
        return None
    if isinstance(result, dict) and len(result) > 200:
        return {"_summary": True, "keys": len(result)}
    return result


__all__ = ["notify_task_status"]
