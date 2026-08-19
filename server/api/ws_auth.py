"""JWT auth middleware for WebSocket connections."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, cast

from channels.middleware import BaseMiddleware
from django.db import close_old_connections

from server.api.ws_protocol import WS_CLOSE_UNAUTHORIZED


class JwtAuthMiddleware(BaseMiddleware):
    """Attach a Django user to WebSocket scope using a JWT token."""

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> Any:
        close_old_connections()
        token = _extract_token(scope)
        scope["token_exp"] = _extract_token_exp(token) if token else None
        if token:
            user = await _get_user_from_token(token)
            scope["user"] = user
        else:
            scope["user"] = _anonymous_user()
        return await self.inner(scope, receive, send)


class WebSocketDenyAnonymousMiddleware(BaseMiddleware):
    """Reject WebSocket connections for anonymous users."""

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> Any:
        user = scope.get("user")
        if not user or user.is_anonymous:
            await send({"type": "websocket.close", "code": WS_CLOSE_UNAUTHORIZED})
            return
        return await self.inner(scope, receive, send)


def _extract_token(scope: dict[str, Any]) -> str | None:
    raw_headers = cast(Iterable[tuple[bytes, bytes]], scope.get("headers", []))
    headers = {k.lower(): v for k, v in raw_headers}
    auth_bytes = headers.get(b"authorization", b"")
    try:
        auth = auth_bytes.decode("utf-8")
    except UnicodeDecodeError:
        auth = ""
    if auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip()

    # Some desktop WebSocket clients cannot reliably send Authorization
    # during the handshake; allow a bearer token via subprotocol header.
    proto_bytes = headers.get(b"sec-websocket-protocol", b"")
    try:
        proto = proto_bytes.decode("utf-8")
    except UnicodeDecodeError:
        proto = ""
    if proto:
        for part in proto.split(","):
            candidate = part.strip()
            if candidate.lower().startswith("bearer."):
                token = candidate[7:].strip()
                if token:
                    return token
    return None


def _extract_token_exp(token: str) -> int | None:
    from rest_framework_simplejwt.tokens import AccessToken

    try:
        access = AccessToken(token)  # type: ignore[arg-type]
    except Exception:
        return None
    exp = access.get("exp")
    if isinstance(exp, int):
        return exp
    if isinstance(exp, str) and exp.isdigit():
        return int(exp)
    return None


async def _get_user_from_token(token: str) -> Any:
    from django.contrib.auth import get_user_model
    from rest_framework_simplejwt.tokens import AccessToken

    try:
        access = AccessToken(token)  # type: ignore[arg-type]
        user_id = access.get("user_id")
    except Exception:
        return _anonymous_user()

    if not user_id:
        return _anonymous_user()

    User = get_user_model()
    try:
        user = await User.objects.aget(id=user_id)
    except User.DoesNotExist:
        return _anonymous_user()
    return user


def _anonymous_user() -> Any:
    from django.contrib.auth.models import AnonymousUser

    return AnonymousUser()


def JwtAuthMiddlewareStack(inner: Any) -> JwtAuthMiddleware:
    """Helper to match Django Channels auth stack signature."""
    return JwtAuthMiddleware(inner)


__all__ = ["JwtAuthMiddlewareStack", "WebSocketDenyAnonymousMiddleware"]
