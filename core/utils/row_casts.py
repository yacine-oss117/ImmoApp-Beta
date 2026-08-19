"""
Helpers for converting DB row values into concrete Python types.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal


def as_int(value: object) -> int:
    """Return value as int or raise if it cannot be coerced."""
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, Decimal):
        return int(value)
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        return int(value)
    raise TypeError(f"Expected int-compatible value, got {type(value).__name__}")


def as_optional_int(value: object) -> int | None:
    """Return value as int or None when empty."""
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    return as_int(value)


def as_str(value: object, *, default: str | None = None) -> str:
    """Return value as str or default when None."""
    if isinstance(value, str):
        return value
    if value is None:
        if default is None:
            raise TypeError("Expected str but value is None")
        return default
    return str(value)


def as_optional_str(value: object) -> str | None:
    """Return value as str or None when empty."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return str(value)


def as_bool(value: object, *, default: bool | None = None) -> bool:
    """Return value as bool or default when None."""
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "y"}:
            return True
        if normalized in {"false", "0", "no", "n", ""}:
            return False
    if value is None and default is not None:
        return default
    raise TypeError(f"Expected bool-compatible value, got {type(value).__name__}")


def row_int(row: Mapping[str, object], key: str) -> int:
    """Return an int value from the row."""
    return as_int(row.get(key))


def row_optional_int(row: Mapping[str, object], key: str) -> int | None:
    """Return an optional int value from the row."""
    return as_optional_int(row.get(key))


def row_str(row: Mapping[str, object], key: str, default: str | None = None) -> str:
    """Return a str value from the row."""
    return as_str(row.get(key), default=default)


def row_optional_str(row: Mapping[str, object], key: str) -> str | None:
    """Return an optional str value from the row."""
    return as_optional_str(row.get(key))


def row_bool(row: Mapping[str, object], key: str, default: bool | None = None) -> bool:
    """Return a bool value from the row."""
    return as_bool(row.get(key), default=default)
