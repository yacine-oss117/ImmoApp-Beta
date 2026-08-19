"""Helpers for parsing values from loosely-typed form data."""

from __future__ import annotations

from collections.abc import Mapping


def get_str(data: Mapping[str, object], key: str, default: str = "") -> str:
    """Return a string value from a data mapping."""
    value = data.get(key, default)
    return str(value) if value is not None else default


def get_int(data: Mapping[str, object], key: str, default: int = 0) -> int:
    """Return an integer value from a data mapping."""
    value = data.get(key, default)
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(float(value.strip()))
        except ValueError:
            return default
    return default


def get_float(data: Mapping[str, object], key: str, default: float = 0.0) -> float:
    """Return a float value from a data mapping."""
    value = data.get(key, default)
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return default
    return default
