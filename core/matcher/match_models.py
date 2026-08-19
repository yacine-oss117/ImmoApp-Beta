"""
Match result data models shared between matcher and UI.
"""

from __future__ import annotations

from dataclasses import dataclass

from core.matcher.match_details import OfferMatch


@dataclass
class MatchResult:
    """Result of matching a single demande against offers."""

    demande_id: int
    demande_summary: str
    matches: list[OfferMatch]
    total_count: int

    @property
    def count(self) -> int:
        """Alias for total_count."""
        return self.total_count


@dataclass
class ClientMatchResult:
    """Complete match result for a client across all demandes."""

    client_id: int
    total_unique_offers: int
    demande_results: list[MatchResult]
