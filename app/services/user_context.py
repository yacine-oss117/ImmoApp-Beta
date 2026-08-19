"""Helpers to sync client timezone/locale to the server."""

from __future__ import annotations

import logging

from app.services.api_client import api_enabled
from app.services.user_settings_repository import set_user_settings
from app.utils.client_context import get_effective_locale, get_effective_timezone
from app.utils.qt_async import run_background

logger = logging.getLogger(__name__)


def sync_user_context() -> None:
    """Send local timezone/locale to the API server."""
    if not api_enabled():
        return
    tz = get_effective_timezone()
    loc = get_effective_locale()
    try:
        set_user_settings(timezone=tz, locale=loc)
    except Exception:
        logger.warning("Failed to sync user context", exc_info=True)


def sync_user_context_async() -> None:
    """Send local timezone/locale to the API server in a background thread."""
    run_background(sync_user_context)
