"""Client context helpers for locale/timezone discovery."""

from __future__ import annotations

from PySide6.QtCore import QSettings

from app.constants import APP, ORG
from app.utils.i18n import resolve_language
from app.utils.time_service import _normalize_iana_id
from app.utils.time_service_helpers import _local_iana_tz


def get_effective_timezone() -> str:
    """Return the active IANA timezone based on settings and system defaults."""
    s = QSettings(ORG, APP)
    force_manual = bool(s.value("time/force_manual_tz", False, bool))
    if force_manual:
        manual = str(s.value("time/manual_tz", "", str) or "").strip()
        normalized = _normalize_iana_id(manual) or manual
        if normalized:
            return normalized
    auto_tz = bool(s.value("time/auto_detect_tz", True, bool))
    if auto_tz:
        cached = str(s.value("cache/tz_name", "", str) or "").strip()
        if cached:
            return cached
    return str(_local_iana_tz() or "")


def get_effective_locale() -> str:
    """Return the active locale, falling back to the system locale."""
    raw = str(resolve_language() or "")
    return raw.replace("_", "-")
