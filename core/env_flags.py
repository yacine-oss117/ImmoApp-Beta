"""Shared environment boolean parsing for security-sensitive runtime flags."""

from __future__ import annotations

import os

BOOLEAN_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
BOOLEAN_FALSE_VALUES = frozenset({"", "0", "false", "no", "off"})
BOOLEAN_ACCEPTED_VALUES = BOOLEAN_TRUE_VALUES | BOOLEAN_FALSE_VALUES


class EnvBoolError(ValueError):
    """Raised when an environment boolean has an unsupported value."""


def parse_bool_env_value(name: str, value: str | None, *, default: bool = False) -> bool:
    """Parse an env boolean with the repo-wide strict boolean contract.

    Truthy values are ``1``, ``true``, ``yes``, and ``on``.
    Falsy values are unset, empty string, ``0``, ``false``, ``no``, and ``off``.
    Matching is case-insensitive and ignores surrounding whitespace.
    """

    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in BOOLEAN_TRUE_VALUES:
        return True
    if normalized in BOOLEAN_FALSE_VALUES:
        return False
    accepted = ", ".join(sorted(BOOLEAN_ACCEPTED_VALUES - {""}))
    raise EnvBoolError(f"{name} must be a boolean value ({accepted}); got {value!r}.")


def bool_env(name: str, *, default: bool = False) -> bool:
    return parse_bool_env_value(name, os.environ.get(name), default=default)


def auth_session_tracking_enabled() -> bool:
    return bool_env("IMMOAPP_AUTH_SESSION_TRACKING_ENABLED")


def require_session_id_claim() -> bool:
    return bool_env("IMMOAPP_REQUIRE_SESSION_ID_CLAIM")


__all__ = [
    "BOOLEAN_ACCEPTED_VALUES",
    "BOOLEAN_FALSE_VALUES",
    "BOOLEAN_TRUE_VALUES",
    "EnvBoolError",
    "auth_session_tracking_enabled",
    "bool_env",
    "parse_bool_env_value",
    "require_session_id_claim",
]
