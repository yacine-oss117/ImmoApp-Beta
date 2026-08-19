"""
Lightweight SQL fragment builder.

Provides structured composition of SQL snippets with optional parameters,
avoiding ad-hoc string concatenation in query assembly.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class SqlFragment:
    """A SQL fragment with an ordered parameter list."""

    sql: str
    params: tuple[object, ...] = ()

    def and_(self, other: SqlFragment) -> SqlFragment:
        return SqlFragment(
            f"({self.sql}) AND ({other.sql})",
            self.params + other.params,
        )

    def or_(self, other: SqlFragment) -> SqlFragment:
        return SqlFragment(
            f"({self.sql}) OR ({other.sql})",
            self.params + other.params,
        )


def and_all(fragments: Iterable[SqlFragment]) -> SqlFragment:
    items = [fragment for fragment in fragments if fragment.sql.strip()]
    if not items:
        return SqlFragment("1=1")
    combined = items[0]
    for fragment in items[1:]:
        combined = combined.and_(fragment)
    return combined


def or_all(fragments: Iterable[SqlFragment]) -> SqlFragment:
    items = [fragment for fragment in fragments if fragment.sql.strip()]
    if not items:
        return SqlFragment("1=0")
    combined = items[0]
    for fragment in items[1:]:
        combined = combined.or_(fragment)
    return combined


__all__ = ["SqlFragment", "and_all", "or_all"]
