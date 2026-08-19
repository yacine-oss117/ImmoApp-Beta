"""Service-layer error re-exports for API views."""

from __future__ import annotations

from core.data.errors import ConflictError, NotFoundError


class PermissionDeniedError(RuntimeError):
    """Raised when an actor lacks permission for an action."""


__all__ = ["ConflictError", "NotFoundError", "PermissionDeniedError"]
