from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CreatedRowRef:
    """Explicit importer-side mapping from a source batch row to its created record id."""

    source_ordinal: int
    created_id: int


__all__ = ["CreatedRowRef"]
