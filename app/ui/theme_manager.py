"""Runtime theme persistence and application helpers."""

from __future__ import annotations

from typing import cast

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QWidget

from app.constants import APP, ORG
from app.ui.theme_qss import build_stylesheet
from app.ui.theme_tokens import DEFAULT_THEME, available_themes, normalize_theme

THEME_KEY = "ui/theme"
DENSITY_KEY = "ui/density"


def current_theme(settings: QSettings | None = None) -> str:
    """Return the persisted theme."""
    s = settings or QSettings(ORG, APP)
    raw = s.value(THEME_KEY, DEFAULT_THEME, str)
    return normalize_theme(cast(str | None, raw))


def set_theme(theme_name: str, settings: QSettings | None = None) -> str:
    """Persist a validated theme and return it."""
    resolved = normalize_theme(theme_name)
    s = settings or QSettings(ORG, APP)
    s.setValue(THEME_KEY, resolved)
    s.sync()
    return resolved


def current_density(settings: QSettings | None = None) -> str:
    """Return the persisted UI density."""
    s = settings or QSettings(ORG, APP)
    raw = s.value(DENSITY_KEY, "compact", str)
    value = cast(str | None, raw)
    normalized = (value or "compact").strip().lower()
    return normalized if normalized in {"comfortable", "compact"} else "compact"


def set_density(density_name: str, settings: QSettings | None = None) -> str:
    """Persist a validated UI density and return it."""
    normalized = (density_name or "compact").strip().lower()
    resolved = normalized if normalized in {"comfortable", "compact"} else "compact"
    s = settings or QSettings(ORG, APP)
    s.setValue(DENSITY_KEY, resolved)
    s.sync()
    return resolved


def apply_theme(
    target: QApplication | QWidget | None = None,
    theme_name: str | None = None,
    density_name: str | None = None,
    *,
    persist: bool = False,
) -> str:
    """Apply a theme stylesheet to the app (or widget) and optionally persist."""
    resolved = normalize_theme(theme_name or current_theme())
    density = density_name or current_density()
    qss = build_stylesheet(resolved, density)

    target_obj = target or QApplication.instance()
    if isinstance(target_obj, (QApplication, QWidget)):
        target_obj.setStyleSheet(qss)

    if persist:
        set_theme(resolved)
    return resolved


def toggle_theme(target: QApplication | QWidget | None = None) -> str:
    """Toggle between dark and light themes."""
    new_theme = "light" if current_theme() == "dark" else "dark"
    return apply_theme(target, new_theme, persist=True)


__all__ = [
    "DENSITY_KEY",
    "THEME_KEY",
    "apply_theme",
    "available_themes",
    "current_density",
    "current_theme",
    "set_density",
    "set_theme",
    "toggle_theme",
]
