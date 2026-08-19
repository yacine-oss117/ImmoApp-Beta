"""Load optional local fonts and expose the system fallback chain."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QFontDatabase

_FONTS_DIR = Path(__file__).resolve().parents[1] / "assets" / "fonts"

SYSTEM_FONT_FALLBACKS = (
    "Noto Sans",
    "Noto Sans Arabic",
    "Segoe UI",
    "Arial",
    "Sans Serif",
)


def load_bundled_fonts() -> list[str]:
    """
    Load all bundled TTF/OTF fonts and return discovered family names.

    Font files are optional at runtime. Missing font assets are tolerated and
    callers can fall back to system fonts.
    """
    families: list[str] = []
    if not _FONTS_DIR.exists():
        return families

    for path in sorted(_FONTS_DIR.glob("*")):
        if path.suffix.lower() not in {".ttf", ".otf"}:
            continue
        font_id = QFontDatabase.addApplicationFont(str(path))
        if font_id < 0:
            continue
        loaded = QFontDatabase.applicationFontFamilies(font_id)
        for family in loaded:
            if family not in families:
                families.append(family)
    return families
