"""
Centralized SQL builders for match counting and detailed match queries.

This module re-exports the canonical builders from submodules to keep imports stable.
"""

from core.matcher.match_query_counts import (
    build_client_counts_query,
    build_demande_counts_query,
    build_demande_match_count_query,
    build_listing_counts_query,
    build_offer_counts_query,
    build_single_client_count_query,
    build_wilaya_client_counts_query,
)
from core.matcher.match_query_cte import MatchQuery, build_match_cte
from core.matcher.match_query_details import build_demande_detail_matches_query

__all__ = [
    "MatchQuery",
    "build_match_cte",
    "build_client_counts_query",
    "build_single_client_count_query",
    "build_demande_counts_query",
    "build_listing_counts_query",
    "build_offer_counts_query",
    "build_wilaya_client_counts_query",
    "build_demande_match_count_query",
    "build_demande_detail_matches_query",
]
