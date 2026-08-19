"""
SQL identifier validation helpers for defensive query construction.
"""

from __future__ import annotations

import re

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def ensure_safe_identifier(
    name: str,
    *,
    allowed: set[str] | None = None,
    kind: str = "identifier",
) -> str:
    """Validate a SQL identifier against a strict whitelist pattern."""
    if allowed is not None and name not in allowed:
        raise ValueError(f"Invalid {kind}: {name!r}")
    if not _IDENTIFIER_RE.fullmatch(name):
        raise ValueError(f"Unsafe {kind}: {name!r}")
    return name


def validate_identifier(
    name: str,
    *,
    allowed: set[str] | None = None,
    kind: str = "identifier",
) -> str:
    """Validate a SQL identifier against a strict whitelist pattern."""
    return ensure_safe_identifier(name, allowed=allowed, kind=kind)
