"""Safe casting helpers for mapping payload values to typed fields."""

from __future__ import annotations

from collections.abc import Mapping, Sequence


def as_str(value: object | None, default: str = "") -> str:
    """Return a string value with a safe default."""
    if value is None:
        return default
    if isinstance(value, str):
        return value
    return str(value)


def as_int(value: object | None, default: int = 0) -> int:
    """Return an int value with a safe default."""
    if value is None:
        return default
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float, str)):
        try:
            return int(value)
        except (TypeError, ValueError):
            return default
    return default


def as_optional_int(value: object | None) -> int | None:
    """Return an int if possible, otherwise None."""
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float, str)):
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
    return None


def as_optional_float(value: object | None) -> float | None:
    """Return a float if possible, otherwise None."""
    if value is None:
        return None
    if isinstance(value, (int, float, str)):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    return None


def row_value(row: Mapping[str, object], key: str) -> object | None:
    """Fetch a value from a mapping-like row, returning None if absent."""
    return row[key] if key in row.keys() else None


def row_at(row: Mapping[str, object] | Sequence[object], index: int) -> object | None:
    """Fetch a positional value from a mapping or sequence row."""
    if isinstance(row, Mapping):
        try:
            return list(row.values())[index]
        except IndexError:
            return None
    try:
        return row[index]
    except IndexError:
        return None
