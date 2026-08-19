from __future__ import annotations

import asyncio
from typing import Any

from core.contracts.ws_protocol import WS_CLOSE_UNAUTHORIZED
from server.api.ws_auth import WebSocketDenyAnonymousMiddleware


class _Inner:
    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        _ = scope, receive, send
        return None


class _AnonUser:
    is_anonymous = True


def test_ws_auth_rejects_anonymous_with_shared_close_code() -> None:
    middleware = WebSocketDenyAnonymousMiddleware(_Inner())
    events: list[dict[str, object]] = []

    async def _run() -> None:
        scope = {"user": _AnonUser()}

        async def _send(event: dict[str, object]) -> None:
            events.append(event)

        await middleware(scope, None, _send)

    asyncio.run(_run())
    assert events
    assert events[0].get("type") == "websocket.close"
    assert events[0].get("code") == WS_CLOSE_UNAUTHORIZED
