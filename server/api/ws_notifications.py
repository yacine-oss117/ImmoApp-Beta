"""WebSocket consumer for user/agency notification streams."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from channels.generic.websocket import AsyncJsonWebsocketConsumer

from server.api.notifications import (
    GLOBAL_GROUP,
    group_agency,
    group_owner,
    group_role,
    group_user,
)
from server.api.ws_protocol import (
    AUTH_EXPIRING_LEAD_SECONDS,
    AUTH_EXPIRY_GRACE_SECONDS,
    CONTROL_AUTH_EXPIRING,
    CONTROL_FIELD,
    CONTROL_HEARTBEAT,
    CONTROL_PING,
    CONTROL_PONG,
    HEARTBEAT_INTERVAL_SECONDS,
    WS_CLOSE_UNAUTHORIZED,
    control_payload,
    scope_supports_v2,
)


class NotificationConsumer(AsyncJsonWebsocketConsumer):
    """Send real-time notifications to users based on scope groups."""

    groups: list[str]
    _heartbeat_task: asyncio.Task[None] | None = None
    _auth_expiry_task: asyncio.Task[None] | None = None
    _supports_v2: bool = False

    async def connect(self) -> None:
        user = self.scope.get("user")
        if not user or not getattr(user, "is_authenticated", False):
            await self.close(code=WS_CLOSE_UNAUTHORIZED)
            return

        self.groups = _groups_for_user(user)
        for group in self.groups:
            await self.channel_layer.group_add(group, self.channel_name)
        await self.accept()
        self._supports_v2 = scope_supports_v2(self.scope)
        if self._supports_v2:
            self._heartbeat_task = asyncio.create_task(self._heartbeat_worker())
            self._auth_expiry_task = asyncio.create_task(self._auth_expiry_worker())

    async def disconnect(self, _code: int) -> None:
        await self._cancel_control_tasks()
        for group in getattr(self, "groups", []):
            await self.channel_layer.group_discard(group, self.channel_name)

    async def receive_json(self, content: dict[str, Any], **kwargs: Any) -> None:
        _ = kwargs
        if not self._supports_v2:
            return
        if content.get(CONTROL_FIELD) == CONTROL_PING:
            await self.send_json(control_payload(CONTROL_PONG, ts=int(time.time())))

    async def notify(self, event: dict[str, Any]) -> None:
        payload = event.get("payload", {})
        await self.send_json(payload)

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


def _groups_for_user(user: Any) -> list[str]:
    groups: list[str] = []
    user_id = getattr(user, "id", None)
    if user_id is not None:
        groups.append(group_user(int(user_id)))

    agency_id = getattr(user, "agency_id", None)
    if agency_id is not None:
        agency_id = int(agency_id)
        groups.append(group_agency(agency_id))
        role = getattr(user, "role", "")
        if isinstance(role, str) and role:
            groups.append(group_role(agency_id, role))
        if getattr(user, "is_owner", False):
            groups.append(group_owner(agency_id))

    if getattr(user, "is_superuser", False):
        groups.append(GLOBAL_GROUP)

    # Deduplicate while preserving order
    seen: set[str] = set()
    result: list[str] = []
    for group in groups:
        if group not in seen:
            seen.add(group)
            result.append(group)
    return result


__all__ = ["NotificationConsumer"]
