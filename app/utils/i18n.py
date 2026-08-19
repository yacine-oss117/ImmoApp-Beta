"""
Internationalization helpers for UI text.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QLocale, QSettings, QTranslator

from app.constants import APP, ORG

logger = logging.getLogger(__name__)

I18N_DIR = Path(__file__).resolve().parent.parent / "i18n"
LANGUAGE_KEY = "ui/language"
_ACTIVE_TRANSLATOR: QTranslator | None = None


def tr(context: str, text: str) -> str:
    """Translate text using a Qt translation context."""
    return str(QCoreApplication.translate(context, text))


def tr_factory(context: str) -> Callable[[str], str]:
    """Return a translation function bound to a specific context."""

    def _tr(text: str) -> str:
        return str(QCoreApplication.translate(context, text))

    return _tr


def _language_candidates(language: str) -> list[str]:
    clean = language.replace("-", "_").strip()
    if not clean:
        return []
    parts = clean.split("_", 1)
    if len(parts) == 2:
        return [clean, parts[0]]
    return [clean]


def _english_only_candidates(candidates: list[str]) -> bool:
    if not candidates:
        return False
    normalized = [c.strip().lower() for c in candidates if c.strip()]
    return bool(normalized) and all(item == "en" or item.startswith("en_") for item in normalized)


def resolve_language(settings: QSettings | None = None) -> str:
    """Resolve language code from settings, defaulting to system locale."""
    if settings is None:
        settings = QSettings(ORG, APP)
    raw = settings.value(LANGUAGE_KEY, "auto", str)
    value = str(raw).strip() if raw else "auto"
    if value == "auto":
        return str(QLocale.system().name())
    return value


def install_translator(app: QCoreApplication, language: str | None = None) -> QTranslator | None:
    """
    Install the best available translation for the provided language code.

    Replaces any previously installed app translator and returns the new one, if any.
    """
    global _ACTIVE_TRANSLATOR
    if _ACTIVE_TRANSLATOR is not None:
        app.removeTranslator(_ACTIVE_TRANSLATOR)
        _ACTIVE_TRANSLATOR = None

    code = language or resolve_language()
    candidates = _language_candidates(code)
    if not candidates:
        return None

    translator = QTranslator(app)
    for candidate in candidates:
        path = I18N_DIR / f"{candidate}.qm"
        if path.exists() and translator.load(str(path)):
            app.installTranslator(translator)
            _ACTIVE_TRANSLATOR = translator
            logger.info("Loaded translation: %s", path)
            return translator

    # English defaults to source strings. Missing .qm for en_* is expected.
    if not _english_only_candidates(candidates):
        logger.debug("No translation found for %s (checked %s)", code, candidates)
    return None
