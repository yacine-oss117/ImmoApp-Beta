"""
Detailed match retrieval utilities.

API:
- All functions REQUIRE conn parameter (injected from services layer)
- Matcher is pure computation - no connection management
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from core.data import match_pairs as match_pairs_data
from core.matcher.ports.db import DbSession
from core.models_cast import as_optional_float
from core.models_demande import Demande
from core.models_offer import Offer

logger = logging.getLogger(__name__)


@dataclass
class OfferMatch:
    """A matched offer with its score."""

    listing_id: int
    offer: Offer
    score: float


def get_matches_for_demande(
    session: DbSession,
    demande: Demande,
    limit: int = 50,
    offset: int = 0,
    score_threshold: float = 0.0,
    agency_id: int | None = None,
) -> tuple[list[OfferMatch], int, set[int]]:
    """
    Get detailed matches using junction tables (O(log n)).

    Args:
        session: Database session (DbSession protocol)
        demande: Demande to find matches for
        limit: Maximum number of matches to return
        score_threshold: Minimum score to include

    Returns:
        Tuple of (matches, total_count, offer_ids)
    """
    try:
        rows: list[dict[str, object]] = []
        total_count = 0
        if score_threshold <= 0.0:
            rows = match_pairs_data.fetch_pairs_with_offers(
                session, demande.id, limit=limit, offset=offset
            )
            total_count = match_pairs_data.count_pairs_for_demande(session, demande.id)
        if not rows and offset == 0:
            logger.info(
                "Match cache empty for demande %s; cache-only read path in effect",
                demande.id,
            )

        matches: list[OfferMatch] = []
        for row in rows:
            offer = Offer.from_row(row)
            if "score" in row:
                score = as_optional_float(row.get("score")) or 0.0
            else:
                # Pair cache stores score; this fallback protects against corrupted rows.
                score = 0.0
            matches.append(OfferMatch(listing_id=offer.listing_id, offer=offer, score=score))

        matches.sort(key=lambda m: m.score, reverse=True)

        threshold = float(score_threshold or 0.0)
        if threshold > 0:
            filtered = [m for m in matches if m.score >= threshold]
            offer_ids = {m.offer.id for m in filtered}
        else:
            filtered = matches
            offer_ids = set()

        if total_count == 0:
            total_count = len(filtered)
        if limit and len(filtered) > limit:
            filtered = filtered[:limit]
        return filtered, total_count, offer_ids

    except Exception as exc:
        logger.error("Detailed match fetch failed for demande %s", demande.id, exc_info=True)
        raise RuntimeError(f"Detailed match fetch failed for demande {demande.id}") from exc
