"""
In-memory match count state for UI usage.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field


@dataclass
class MatchCountState:
    """Tracks computed match counts for clients."""

    _counts: dict[int, int] = field(default_factory=dict)

    def set_count(self, client_id: int, count: int) -> None:
        """Set or update the match count for a specific client."""
        self._counts[client_id] = count

    def update_counts(self, counts: Mapping[int, int]) -> None:
        """Batch update multiple client match counts."""
        self._counts.update(counts)

    def get_count(self, client_id: int) -> int | None:
        """Retrieve the currently stored match count for a client."""
        return self._counts.get(client_id)

    def clear(self) -> None:
        """Remove all stored match counts."""
        self._counts.clear()

    def missing_ids(self, client_ids: Iterable[int]) -> list[int]:
        """Return a list of IDs from the input that are not in the current state."""
        return [client_id for client_id in client_ids if client_id not in self._counts]
