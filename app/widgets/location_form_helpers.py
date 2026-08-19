"""
Shared helpers for location-aware forms.
"""

from __future__ import annotations

import logging
import weakref
from collections.abc import Callable

from PySide6.QtWidgets import QWidget

from app.services.locations_repository import add_location, get_all_locations, peek_cached_locations
from app.utils.i18n import tr_factory
from app.utils.qt_async import is_qt_object_alive, run_background_result

logger = logging.getLogger(__name__)
_TR = tr_factory("LocationFormHelpers")


def normalize_location_with_wilaya(name: str, wilaya: str) -> str:
    """Normalize a location label and append wilaya when no suffix is present."""
    normalized_name = (name or "").strip()
    normalized_wilaya = (wilaya or "").strip()
    if not normalized_name:
        return ""
    if normalized_wilaya and "," not in normalized_name:
        return f"{normalized_name}, {normalized_wilaya}"
    return normalized_name


def prime_locations_non_blocking(
    parent: QWidget,
    on_locations: Callable[[list[str]], None],
    *,
    on_error: Callable[[str], None] | None = None,
) -> list[str]:
    """
    Return cached locations immediately and refresh in background.

    The callback is always invoked on the UI thread.
    """
    cached = peek_cached_locations()
    if cached:
        on_locations(cached)
    refresh_locations_async(parent, on_locations, on_error=on_error)
    return cached


def refresh_locations_async(
    parent: QWidget,
    on_locations: Callable[[list[str]], None],
    on_error: Callable[[str], None] | None = None,
) -> None:
    """Refresh locations in a background thread and publish on UI thread."""
    parent_ref = weakref.ref(parent)

    def _emit_locations(locations: list[str]) -> None:
        if not is_qt_object_alive(parent_ref()):
            return
        on_locations(locations)

    def _emit_error(exc: Exception) -> None:
        if not is_qt_object_alive(parent_ref()):
            return
        if on_error is not None:
            message = _TR("Failed to refresh locations from server.")
            if str(exc):
                message = f"{message} ({exc})"
            on_error(message)

    def _task() -> list[str]:
        return get_all_locations()

    def _on_error(exc: Exception) -> None:
        logger.warning("Background locations refresh failed: %s", exc)
        _emit_error(exc)

    run_background_result(_task, _emit_locations, _on_error)


def add_location_with_wilaya_async(
    parent: QWidget,
    name: str,
    wilaya: str,
    *,
    on_success: Callable[[str], None] | None = None,
    on_error: Callable[[str], None] | None = None,
) -> str:
    """Persist a location in background and notify callbacks on the UI thread."""
    full_name = normalize_location_with_wilaya(name, wilaya)
    if not full_name:
        if on_error is not None:
            on_error(_TR("Location name is required."))
        return ""

    parent_ref = weakref.ref(parent)

    def _emit_success(_created: bool) -> None:
        if not is_qt_object_alive(parent_ref()):
            return
        if on_success is not None:
            on_success(full_name)

    def _emit_error(message: str) -> None:
        if not is_qt_object_alive(parent_ref()):
            return
        if on_error is not None:
            on_error(message)

    def _task() -> bool:
        created = add_location(full_name)
        if created or full_name in peek_cached_locations():
            return True
        raise RuntimeError(_TR("Location was not created."))

    def _on_error(exc: Exception) -> None:
        logger.error("Async add location failed for %s: %s", full_name, exc)
        message = _TR("Failed to save location.")
        if str(exc):
            message = f"{message} ({exc})"
        _emit_error(message)

    run_background_result(_task, _emit_success, _on_error)
    return full_name
