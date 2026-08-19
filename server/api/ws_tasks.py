"""WebSocket consumers for task status updates."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from channels.generic.websocket import AsyncJsonWebsocketConsumer

from server.api.task_registry import get_task_owner
from server.api.ws_protocol import (
    AUTH_EXPIRING_LEAD_SECONDS,
    AUTH_EXPIRY_GRACE_SECONDS,
    CONTROL_AUTH_EXPIRING,
    CONTROL_FIELD,
    CONTROL_HEARTBEAT,
    CONTROL_PING,
    CONTROL_PONG,
    HEARTBEAT_INTERVAL_SECONDS,
    WS_CLOSE_BAD_REQUEST,
    WS_CLOSE_FORBIDDEN,
    WS_CLOSE_UNAUTHORIZED,
    control_payload,
    scope_supports_v2,
)


class TaskStatusConsumer(AsyncJsonWebsocketConsumer):
    """Send task completion updates to connected clients."""

    group_name: str | None = None
    _heartbeat_task: asyncio.Task[None] | None = None
    _auth_expiry_task: asyncio.Task[None] | None = None
    _supports_v2: bool = False

    async def connect(self) -> None:
        user = self.scope.get("user")
        if not user or not getattr(user, "is_authenticated", False):
            await self.close(code=WS_CLOSE_UNAUTHORIZED)
            return

        task_id = self.scope.get("url_route", {}).get("kwargs", {}).get("task_id")
        if not task_id:
            await self.close(code=WS_CLOSE_BAD_REQUEST)
            return

        owner = get_task_owner(task_id)
        if not _can_access_task(user, owner):
            await self.close(code=WS_CLOSE_FORBIDDEN)
            return

        self.group_name = f"task.{task_id}"
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        self._supports_v2 = scope_supports_v2(self.scope)
        if self._supports_v2:
            self._heartbeat_task = asyncio.create_task(self._heartbeat_worker())
            self._auth_expiry_task = asyncio.create_task(self._auth_expiry_worker())

    async def disconnect(self, _code: int) -> None:
        await self._cancel_control_tasks()
        group_name = getattr(self, "group_name", None)
        if group_name:
            await self.channel_layer.group_discard(group_name, self.channel_name)

    async def receive_json(self, content: dict[str, Any], **kwargs: Any) -> None:
        _ = kwargs
        if not self._supports_v2:
            return
        if content.get(CONTROL_FIELD) == CONTROL_PING:
            await self.send_json(control_payload(CONTROL_PONG, ts=int(time.time())))

    async def task_status(self, event: dict[str, Any]) -> None:
        await self.send_json(event)

    async def _cancel_control_tasks(self) -> None:
        for task in (self._heartbeat_task, self._auth_expiry_task):
            if task is not None:
                task.cancel()
        self._heartbeat_task = None
        self._auth_expiry_task = None

    async def _heartbeat_worker(self) -> None:
        try:
            while True:
                await asyncio.sleep(max(1, HEARTBEAT_INTERVAL_SECONDS))
                await self.send_json(control_payload(CONTROL_HEARTBEAT, ts=int(time.time())))
        except asyncio.CancelledError:
            return
        except Exception:
            return

    async def _auth_expiry_worker(self) -> None:
        token_exp = self.scope.get("token_exp")
        if not isinstance(token_exp, int):
            return
        now = int(time.time())
        if token_exp <= now:
            await self.close(code=WS_CLOSE_UNAUTHORIZED)
            return
        lead = max(0, AUTH_EXPIRING_LEAD_SECONDS)
        if token_exp - now > lead:
            await asyncio.sleep((token_exp - now) - lead)
        expires_in = max(token_exp - int(time.time()), 0)
        if expires_in > 0:
            await self.send_json(
                control_payload(CONTROL_AUTH_EXPIRING, expires_in=expires_in, exp=token_exp)
            )
            await asyncio.sleep(expires_in + max(0, AUTH_EXPIRY_GRACE_SECONDS))
        await self.close(code=WS_CLOSE_UNAUTHORIZED)


def _can_access_task(user: Any, owner: dict[str, Any] | None) -> bool:
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    if owner is None:
        return False
    if getattr(user, "is_superuser", False):
        return True
    agency_id = getattr(user, "agency_id", None)
    return agency_id is not None and agency_id == owner.get("agency_id")


__all__ = ["TaskStatusConsumer"]
