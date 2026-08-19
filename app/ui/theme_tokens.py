"""Theme token definitions for desktop UI."""

from __future__ import annotations

from typing import Final

ThemeName = str

_TOKENS: Final[dict[ThemeName, dict[str, str]]] = {
    "dark": {
        "BG": "#0f1220",
        "SURFACE": "#171a2b",
        "SURFACE_ALT": "#1f2338",
        "SURFACE_SOFT": "#262b43",
        "BORDER": "#303653",
        "TEXT": "#edf1ff",
        "TEXT_MUTED": "#aab3d1",
        "TEXT_DIM": "#8b95b7",
        "PRIMARY": "#5b8cff",
        "PRIMARY_HOVER": "#7da5ff",
        "PRIMARY_ACTIVE": "#4a79e6",
        "SUCCESS": "#22c55e",
        "WARNING": "#f59e0b",
        "DANGER": "#ef4444",
        "INFO": "#38bdf8",
        "CARD": "#15192a",
        "TABLE_ALT": "#14182a",
        "SELECTION": "#2e4a8a",
        "FOCUS": "#7da5ff",
        "SHADOW": "#00000055",
        "INPUT_BG": "#222743",
        "HEADER_BG": "#1a1f36",
        "MENU_BG": "#13172a",
        "GHOST_HOVER": "#2a3151",
        "SUCCESS_SOFT": "#123223",
        "WARNING_SOFT": "#3b2a0f",
        "DANGER_SOFT": "#3d1b23",
        "INFO_SOFT": "#123447",
        "STATUS_SCHEDULED": "#5b8cff",
        "STATUS_COMPLETED": "#22c55e",
        "STATUS_CANCELLED": "#ef4444",
        "STATUS_DRAFT": "#8b95b7",
        "STATUS_PENDING": "#f59e0b",
        "STATUS_SIGNED": "#22c55e",
        "STATUS_ARCHIVED": "#38bdf8",
        "IMPORT_INFO_BG": "#182744",
        "IMPORT_INFO_BORDER": "#5b8cff",
    },
    "light": {
        "BG": "#f4f6fb",
        "SURFACE": "#ffffff",
        "SURFACE_ALT": "#f7f9ff",
        "SURFACE_SOFT": "#eef2ff",
        "BORDER": "#d5dcef",
        "TEXT": "#13203b",
        "TEXT_MUTED": "#4d5b7d",
        "TEXT_DIM": "#6e7d9f",
        "PRIMARY": "#2f63da",
        "PRIMARY_HOVER": "#3e73ea",
        "PRIMARY_ACTIVE": "#2655bf",
        "SUCCESS": "#15803d",
        "WARNING": "#b45309",
        "DANGER": "#b91c1c",
        "INFO": "#0e7490",
        "CARD": "#ffffff",
        "TABLE_ALT": "#f8faff",
        "SELECTION": "#dbeafe",
        "FOCUS": "#2f63da",
        "SHADOW": "#10203f22",
        "INPUT_BG": "#ffffff",
        "HEADER_BG": "#eef2ff",
        "MENU_BG": "#ffffff",
        "GHOST_HOVER": "#e7edff",
        "SUCCESS_SOFT": "#e6f7ee",
        "WARNING_SOFT": "#fff4e5",
        "DANGER_SOFT": "#fdebec",
        "INFO_SOFT": "#e6f4ff",
        "STATUS_SCHEDULED": "#2f63da",
        "STATUS_COMPLETED": "#15803d",
        "STATUS_CANCELLED": "#b91c1c",
        "STATUS_DRAFT": "#6e7d9f",
        "STATUS_PENDING": "#b45309",
        "STATUS_SIGNED": "#15803d",
        "STATUS_ARCHIVED": "#0e7490",
        "IMPORT_INFO_BG": "#e9f1ff",
        "IMPORT_INFO_BORDER": "#2f63da",
    },
}

DEFAULT_THEME: Final[ThemeName] = "dark"


def available_themes() -> tuple[str, ...]:
    """Return supported theme names."""
    return tuple(_TOKENS.keys())


def normalize_theme(theme_name: str | None) -> str:
    """Normalize unknown names to a valid theme."""
    if not theme_name:
        return DEFAULT_THEME
    lowered = str(theme_name).strip().lower()
    if lowered in _TOKENS:
        return lowered
    return DEFAULT_THEME


def get_theme_tokens(theme_name: str | None) -> dict[str, str]:
    """Return a shallow copy of tokens for the requested theme."""
    return dict(_TOKENS[normalize_theme(theme_name)])
