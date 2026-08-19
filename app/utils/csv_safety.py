from __future__ import annotations


def csv_safe(value: object) -> str:
    text = "" if value is None else str(value)
    stripped = text.lstrip()
    if stripped.startswith(("=", "+", "-", "@")):
        return "'" + text
    return text
