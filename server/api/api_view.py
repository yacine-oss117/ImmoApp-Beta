"""Backward-compatible alias to the secured API view decorator."""

from __future__ import annotations

from server.api.secured_view import secured_api_view

api_view = secured_api_view

__all__ = ["api_view", "secured_api_view"]
