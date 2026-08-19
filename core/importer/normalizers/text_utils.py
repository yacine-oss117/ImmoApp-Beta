"""Shared text normalization helpers for importer normalizers."""

from __future__ import annotations

import re

ARABIC_DIGITS: dict[str, str] = {
    "٠": "0",
    "١": "1",
    "٢": "2",
    "٣": "3",
    "٤": "4",
    "٥": "5",
    "٦": "6",
    "٧": "7",
    "٨": "8",
    "٩": "9",
    "۰": "0",
    "۱": "1",
    "۲": "2",
    "۳": "3",
    "۴": "4",
    "۵": "5",
    "۶": "6",
    "۷": "7",
    "۸": "8",
    "۹": "9",
}

_WHITESPACE_RE = re.compile(r"\s+")
_LABEL_SEPARATOR_RE = re.compile(r"^\s*(?P<label>[a-z0-9 _-]+?)\s*[:=\-]\s*")

_TYPOGRAPHIC_TRANSLATION = str.maketrans(
    {
        "“": '"',
        "”": '"',
        "„": '"',
        "«": '"',
        "»": '"',
        "‘": "'",
        "’": "'",
        "‚": "'",
        "\xa0": " ",
        "\u202f": " ",
        "\u2007": " ",
        "\u200b": None,
        "\u200c": None,
        "\u200d": None,
        "\u2060": None,
        "\ufeff": None,
        "–": "-",
        "—": "-",
        "−": "-",
    }
)
_ARABIC_DIGIT_TRANSLATION = str.maketrans(ARABIC_DIGITS)
_ACCENT_TRANSLATION = str.maketrans(
    {
        "é": "e",
        "è": "e",
        "ê": "e",
        "ë": "e",
        "à": "a",
        "â": "a",
        "ä": "a",
        "î": "i",
        "ï": "i",
        "ô": "o",
        "ö": "o",
        "ù": "u",
        "û": "u",
        "ü": "u",
        "ç": "c",
        "É": "E",
        "È": "E",
        "Ê": "E",
        "Ë": "E",
        "À": "A",
        "Â": "A",
        "Ä": "A",
        "Î": "I",
        "Ï": "I",
        "Ô": "O",
        "Ö": "O",
        "Ù": "U",
        "Û": "U",
        "Ü": "U",
        "Ç": "C",
    }
)
_CONTROL_TRANSLATION = str.maketrans(
    {codepoint: None for codepoint in (*range(0x00, 0x09), 0x0B, 0x0C, *range(0x0E, 0x20), 0x7F)}
)
_DEFAULT_LABELS = {
    "budget",
    "mobile",
    "phone",
    "portable",
    "price",
    "prix",
    "surface",
    "superficie",
    "tel",
    "telephone",
}


def convert_arabic_digits(text: str) -> str:
    """Convert Arabic-Indic and Persian digits to Latin digits."""
    if not text:
        return ""
    return str(text).translate(_ARABIC_DIGIT_TRANSLATION)


def strip_accents(text: str) -> str:
    """Strip the French accent superset used across importer normalizers."""
    if not text:
        return ""
    return str(text).translate(_ACCENT_TRANSLATION)


def normalize_whitespace(text: str) -> str:
    """Collapse repeated whitespace and trim the result."""
    if not text:
        return ""
    return _WHITESPACE_RE.sub(" ", str(text)).strip()


def canonicalize_text(text: str) -> str:
    """Apply shared importer-safe canonicalization."""
    if not text:
        return ""
    resolved = str(text).replace("&nbsp;", " ").translate(_TYPOGRAPHIC_TRANSLATION)
    resolved = convert_arabic_digits(resolved)
    resolved = strip_accents(resolved).lower()
    resolved = resolved.translate(_CONTROL_TRANSLATION)
    return normalize_whitespace(resolved)


def strip_labels(text: str, labels: set[str] | None = None) -> str:
    """Remove a known field label prefix such as ``tel:`` or ``prix:``."""
    normalized = canonicalize_text(text)
    if not normalized:
        return ""

    match = _LABEL_SEPARATOR_RE.match(normalized)
    if not match:
        return normalized

    allowed_labels = {
        canonicalize_text(label) for label in (labels if labels is not None else _DEFAULT_LABELS)
    }
    if match.group("label") not in allowed_labels:
        return normalized
    return normalized[match.end() :].strip()


__all__ = [
    "ARABIC_DIGITS",
    "canonicalize_text",
    "convert_arabic_digits",
    "normalize_whitespace",
    "strip_accents",
    "strip_labels",
]
