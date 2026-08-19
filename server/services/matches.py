"""
Postgres-backed match queries using the shared matcher engine.

Note: agency_id is optional to allow superuser cross-tenant reads.
"""

from __future__ import annotations

import logging
import os

from core.data import demande_repository as demande_data
from core.data import lookup_tables
from core.data import match_pairs as match_pairs_data
from core.matcher import match_counter
from core.matcher.match_details import OfferMatch
from core.matcher.match_details import get_matches_for_demande as get_matches_for_demande_detail
from core.matcher.match_models import ClientMatchResult, MatchResult
from core.matcher.match_query_sql import ACTIVE_LISTING, ACTIVE_OFFER
from core.matcher.match_scoring import format_demande_summary
from core.utils.common import coerce_number
from server.immoapp_server.observability import business_span
from server.pg.uow import PgSession, get_current_agency_id, get_uow
from server.services.match_jobs import enqueue_rebuild_demande_pairs

logger = logging.getLogger(__name__)

__all__ = [
    "OfferMatch",
    "ClientMatchResult",
    "MatchResult",
    "get_matches_for_client",
    "get_matches_for_demande",
    "count_matches_for_clients",
    "count_matches_for_all_clients",
    "count_matches_for_all_demandes",
    "count_matches_for_single_client",
    "count_matches_for_wilaya_clients",
    "count_matches_for_all_listings",
    "count_matches_for_all_offers",
    "count_matches_for_listings",
    "count_matches_for_offers",
    "count_matches_for_demandes",
]

_MATCH_CACHE_ONLY = os.environ.get("MATCH_CACHE_ONLY", "1") != "0"


def _needs_pair_rebuild(session: PgSession, demande_id: int) -> bool:
    """Return True if candidates exist but active/visible pairs are missing."""
    has_candidates = session.execute(
        "SELECT 1 FROM match_candidates WHERE demande_id = %s LIMIT 1",
        (demande_id,),
    ).fetchone()
    if not has_candidates:
        return False
    has_active_pairs = session.execute(
        f"""
        SELECT 1
        FROM match_pairs mp
        JOIN offers o ON o.id = mp.offer_id AND {ACTIVE_OFFER.sql}
        JOIN listings l ON l.id = o.listing_id AND {ACTIVE_LISTING.sql}
        WHERE mp.demande_id = %s
        LIMIT 1
        """,
        (demande_id,),
    ).fetchone()
    return not has_active_pairs


def _ensure_pairs_enqueued(session: PgSession, demande_id: int) -> None:
    if not _MATCH_CACHE_ONLY or not _needs_pair_rebuild(session, demande_id):
        return

    agency_id = get_current_agency_id()
    if agency_id is None:
        row = session.execute(
            """
            SELECT c.agency_id
            FROM demandes d
            JOIN clients c ON c.id = d.client_id
            WHERE d.id = %s
            LIMIT 1
            """,
            (demande_id,),
        ).fetchone()
        agency_raw = row.get("agency_id") if row else None
        if isinstance(agency_raw, int) and agency_raw > 0:
            agency_id = agency_raw
    enqueue_rebuild_demande_pairs(demande_id, agency_id=agency_id)


def _hydrate_pairs_inline_on_cache_miss(
    session: PgSession,
    *,
    demande_id: int,
    limit: int,
) -> bool:
    """
    Fallback for cache-only mode: if candidates exist but active pairs are missing,
    rebuild pairs inline so a single API request can return data.
    """
    if not _MATCH_CACHE_ONLY:
        return False
    if not _needs_pair_rebuild(session, demande_id):
        return False
    try:
        stored_count, _ranked_count = (
            match_pairs_data.rebuild_pairs_for_demande_from_candidates_sql(
                session,
                demande_id,
                limit=limit,
            )
        )
        return stored_count > 0
    except Exception:
        # Any SQL error leaves the transaction in aborted state; reset so the
        # outer read path can continue and return a stable response.
        try:
            session.rollback()
        except Exception:
            pass
        logger.warning(
            "Inline pair hydration failed for demande_id=%s; returning cache miss fallback",
            demande_id,
            exc_info=True,
        )
        return False


def get_matches_for_client(
    client_id: int,
    *,
    limit_per_demande: int = 50,
    score_threshold: float = 0.0,
) -> ClientMatchResult:
    """Retrieve comprehensive match results for a client across all their active demandes."""
    with business_span(
        "matcher.fetch_matches_for_client",
        attributes={
            "match.client_id": client_id,
            "match.limit_per_demande": limit_per_demande,
            "match.score_threshold": score_threshold,
        },
    ) as span:
        with get_uow().transaction() as session:
            status_row = session.execute(
                "SELECT c.status FROM clients c WHERE c.id = %s AND c.deleted_at IS NULL",
                (client_id,),
            ).fetchone()
            if not status_row or status_row["status"] != "active":
                span.set_attribute("match.client_active", False)
                span.set_attribute("match.total_unique_offers", 0)
                return ClientMatchResult(
                    client_id=client_id,
                    total_unique_offers=0,
                    demande_results=[],
                )

            span.set_attribute("match.client_active", True)
            demandes = demande_data.get_demandes_for_client(session, client_id)
            span.set_attribute("match.demandes_count", len(demandes))
            threshold = coerce_number(score_threshold) or 0.0
            unique_offer_ids: set[int] | None = set() if threshold > 0 else None
            demande_results: list[MatchResult] = []

            for demande in demandes:
                matches, total_count, offer_ids = get_matches_for_demande_detail(
                    session,
                    demande,
                    limit=limit_per_demande,
                    offset=0,
                    score_threshold=threshold,
                )
                if total_count == 0:
                    _ensure_pairs_enqueued(session, demande.id)
                    if _hydrate_pairs_inline_on_cache_miss(
                        session,
                        demande_id=demande.id,
                        limit=limit_per_demande,
                    ):
                        matches, total_count, offer_ids = get_matches_for_demande_detail(
                            session,
                            demande,
                            limit=limit_per_demande,
                            offset=0,
                            score_threshold=threshold,
                        )
                if unique_offer_ids is not None and offer_ids:
                    unique_offer_ids.update(offer_ids)

                summary = format_demande_summary(demande)
                demande_results.append(
                    MatchResult(
                        demande_id=demande.id,
                        demande_summary=summary,
                        matches=matches,
                        total_count=total_count,
                    )
                )

            demande_results.sort(key=lambda r: r.count, reverse=True)

            if unique_offer_ids is not None:
                total_unique_offers = len(unique_offer_ids)
            else:
                total_unique_offers = match_counter.count_single_client_cte(session, client_id)

            span.set_attribute("match.total_unique_offers", total_unique_offers)
            return ClientMatchResult(
                client_id=client_id,
                total_unique_offers=total_unique_offers,
                demande_results=demande_results,
            )


def get_matches_for_demande(
    demande_id: int,
    *,
    limit: int = 50,
    offset: int = 0,
    score_threshold: float = 0.0,
) -> MatchResult | None:
    """Retrieve match results for a single demande."""
    with business_span(
        "matcher.fetch_matches_for_demande",
        attributes={
            "match.demande_id": demande_id,
            "match.limit": limit,
            "match.offset": offset,
            "match.score_threshold": score_threshold,
        },
    ) as span:
        with get_uow().transaction() as session:
            demande = demande_data.get_demande_by_id(session, demande_id, include_deleted=False)
            if not demande:
                span.set_attribute("match.demande_exists", False)
                return None

            span.set_attribute("match.demande_exists", True)
            threshold = coerce_number(score_threshold) or 0.0
            matches, total_count, _offer_ids = get_matches_for_demande_detail(
                session,
                demande,
                limit=limit,
                offset=offset,
                score_threshold=threshold,
            )
            span.set_attribute("match.total_count", total_count)
            span.set_attribute("match.returned_count", len(matches))
            if offset == 0 and total_count == 0:
                _ensure_pairs_enqueued(session, demande.id)
                rebuilt_inline = _hydrate_pairs_inline_on_cache_miss(
                    session,
                    demande_id=demande.id,
                    limit=limit,
                )
                if rebuilt_inline:
                    matches, total_count, _offer_ids = get_matches_for_demande_detail(
                        session,
                        demande,
                        limit=limit,
                        offset=offset,
                        score_threshold=threshold,
                    )
                span.set_attribute("match.rebuild_enqueued", True)
                span.set_attribute("match.rebuilt_inline", rebuilt_inline)
            else:
                span.set_attribute("match.rebuild_enqueued", False)
                span.set_attribute("match.rebuilt_inline", False)
            summary = format_demande_summary(demande)
            return MatchResult(
                demande_id=demande.id,
                demande_summary=summary,
                matches=matches,
                total_count=total_count,
            )


def count_matches_for_clients(client_ids: list[int]) -> dict[int, int]:
    """Batch count matches for a specific list of client IDs."""
    if not client_ids:
        return {}
    with get_uow().session() as session:
        return match_counter.batch_count_clients_paginated(session, client_ids)


def count_matches_for_all_clients() -> dict[int, int]:
    """Count matches for all active clients in the database."""
    with get_uow().session() as session:
        return match_counter.batch_count_all_clients_cte(session)


def count_matches_for_all_demandes() -> dict[int, int]:
    """Count matches for all active demandes in the database."""
    with get_uow().session() as session:
        return match_counter.batch_count_all_demandes_cte(session)


def count_matches_for_single_client(client_id: int) -> int:
    """Count unique offer matches for a single client."""
    with get_uow().session() as session:
        return match_counter.count_single_client_cte(session, client_id)


def count_matches_for_wilaya_clients(
    wilaya_id: int | None = None,
    *,
    wilaya: str | None = None,
) -> dict[int, int]:
    """Count matches for all clients residing in a specific wilaya."""
    with get_uow().session() as session:
        resolved_id = wilaya_id
        if resolved_id in (None, 0) and wilaya:
            resolved_id = lookup_tables.get_wilaya_id(session, wilaya)
        return match_counter.count_clients_in_wilaya_cte(session, resolved_id)


def count_matches_for_all_listings() -> dict[int, int]:
    """Count matches for all active listings."""
    with get_uow().session() as session:
        return match_counter.batch_count_all_listings_cte(session)


def count_matches_for_all_offers() -> dict[int, int]:
    """Count matches for all active offers."""
    with get_uow().session() as session:
        return match_counter.batch_count_all_offers_cte(session)


def count_matches_for_listings(listing_ids: list[int]) -> dict[int, int]:
    """Batch count matches for a specific list of listing IDs."""
    if not listing_ids:
        return {}
    with get_uow().session() as session:
        return match_counter.batch_count_listings_paginated(session, listing_ids)


def count_matches_for_offers(offer_ids: list[int]) -> dict[int, int]:
    """Batch count matches (compatible demands) for a list of offer IDs."""
    if not offer_ids:
        return {}
    with get_uow().session() as session:
        return match_counter.count_offers_by_ids(session, offer_ids)


def count_matches_for_demandes(demande_ids: list[int]) -> dict[int, int]:
    """Batch count matches (compatible offers) for a list of demande IDs."""
    if not demande_ids:
        return {}
    with get_uow().session() as session:
        return match_counter.count_demandes_by_ids(session, demande_ids)
