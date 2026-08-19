"""API URL patterns built from declarative route decorators."""

from __future__ import annotations

from server.api.route_registry import build_urlpatterns

urlpatterns = build_urlpatterns()

__all__ = ["urlpatterns"]
