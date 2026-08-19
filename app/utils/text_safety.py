"""Helpers for safe text rendering in the desktop UI."""

from __future__ import annotations

import re
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]")


def strip_control_chars(text: str) -> str:
    """Remove non-printable control characters from text."""
    return _CONTROL_CHARS.sub("", text)


def to_plain_text(value: Any) -> str:
    """Convert a value to plain text safe for display."""
    if value is None:
        return ""
    return strip_control_chars(str(value))


def set_label_plain_text(label: QLabel, value: Any) -> None:
    """Set QLabel text in plain-text mode (no rich text parsing)."""
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setText(to_plain_text(value))


def set_label_rich_text(label: QLabel, value: str) -> None:
    """Set QLabel text as trusted rich text (caller must escape)."""
    label.setTextFormat(Qt.TextFormat.RichText)
    label.setText(value)
