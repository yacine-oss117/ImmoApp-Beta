"""
Match service - orchestration layer for match operations.
"""

from __future__ import annotations

from app.services.match_counts import (
    count_matches_for_all_clients,
    count_matches_for_clients,
    count_matches_for_demandes,
    count_matches_for_listings,
    count_matches_for_offers,
    count_matches_for_single_client,
    count_matches_for_wilaya_clients,
    start_count_matches_for_all_clients,
    start_count_matches_for_all_demandes,
    wait_for_task_counts,
)
from app.services.match_fetch import (
    expand_matches_for_demande,
    get_matches_for_client,
    get_matches_for_demande,
)
from core.matcher.match_details import OfferMatch
from core.matcher.match_models import ClientMatchResult, MatchResult

__all__ = [
    # Use-case functions
    "get_matches_for_client",
    "get_matches_for_demande",
    "expand_matches_for_demande",
    "count_matches_for_clients",
    "count_matches_for_all_clients",
    "start_count_matches_for_all_clients",
    "start_count_matches_for_all_demandes",
    "wait_for_task_counts",
    "count_matches_for_single_client",
    "count_matches_for_wilaya_clients",
    "count_matches_for_listings",
    "count_matches_for_offers",
    "count_matches_for_demandes",
    # Types for UI
    "OfferMatch",
    "ClientMatchResult",
    "MatchResult",
]
