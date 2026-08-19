"""
QSettings schema validation and versioning helpers.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QSettings

SETTINGS_SCHEMA_VERSION = 3
SCHEMA_VERSION_KEY = "settings/schema_version"


@dataclass(frozen=True)
class SettingSpec:
    """Define a QSettings key, its default, and coercion function."""

    default: object
    coerce: Callable[[object], object]


def _coerce_bool(value: object, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "y", "on"}:
            return True
        if lowered in {"false", "0", "no", "n", "off"}:
            return False
    return default


def _coerce_int(value: object, default: int) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return default
    return default


def _coerce_str(value: object, default: str) -> str:
    if isinstance(value, str):
        return value
    if value is None:
        return default
    return str(value)


def _coerce_density(value: object, default: str) -> str:
    raw = _coerce_str(value, default).strip().lower()
    if raw in {"comfortable", "compact"}:
        return raw
    return default


def _spec_bool(default: bool) -> SettingSpec:
    return SettingSpec(default=default, coerce=lambda value: _coerce_bool(value, default))


def _spec_int(default: int) -> SettingSpec:
    return SettingSpec(default=default, coerce=lambda value: _coerce_int(value, default))


def _spec_str(default: str) -> SettingSpec:
    return SettingSpec(default=default, coerce=lambda value: _coerce_str(value, default))


def _spec_density(default: str = "compact") -> SettingSpec:
    return SettingSpec(default=default, coerce=lambda value: _coerce_density(value, default))


SETTINGS_SCHEMA: dict[str, SettingSpec] = {
    "time/offline_mode": _spec_bool(False),
    "time/auto_detect_tz": _spec_bool(True),
    "time/use_ntp": _spec_bool(True),
    "time/use_ntp_local": _spec_bool(True),
    "time/force_manual_tz": _spec_bool(False),
    "time/manual_tz": _spec_str(""),
    "ui/language": _spec_str("auto"),
    "ui/density": _spec_density("compact"),
    "ui/tab_preload": _spec_bool(True),
    "ui/max_threadpool": _spec_int(4),
}


def ensure_settings_schema_version(settings: QSettings) -> None:
    """Ensure the schema version key is present."""
    current = settings.value(SCHEMA_VERSION_KEY, 0, int)
    if isinstance(current, int) and current == SETTINGS_SCHEMA_VERSION:
        return
    settings.setValue(SCHEMA_VERSION_KEY, SETTINGS_SCHEMA_VERSION)


def apply_settings_schema(settings: QSettings) -> None:
    """Validate settings against the schema and write defaults/coerced values."""
    current_version = _coerce_int(settings.value(SCHEMA_VERSION_KEY, 0), 0)

    # Global density migration for rollout: legacy/missing "comfortable" becomes compact.
    if current_version < 3:
        current_density = settings.value("ui/density", None)
        normalized = str(current_density).strip().lower() if current_density is not None else ""
        if normalized in {"", "comfortable"}:
            settings.setValue("ui/density", "compact")

    ensure_settings_schema_version(settings)
    for key, spec in SETTINGS_SCHEMA.items():
        raw = settings.value(key, None)
        if raw is None:
            settings.setValue(key, spec.default)
            continue
        coerced = spec.coerce(raw)
        if coerced != raw or not isinstance(raw, type(coerced)):
            settings.setValue(key, coerced)
    settings.sync()
