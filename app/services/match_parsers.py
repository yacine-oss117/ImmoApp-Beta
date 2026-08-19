"""
Parsing helpers for match API payloads.
"""

from __future__ import annotations

from collections.abc import Callable

from app.models import Offer
from app.models_cast import as_int
from app.services.api_client import as_dict
from core.matcher.match_details import OfferMatch
from core.matcher.match_models import ClientMatchResult, MatchResult


def parse_counts(payload: object) -> dict[int, int]:
    data = as_dict(payload)
    raw_counts = data.get("counts") if "counts" in data else data
    if not isinstance(raw_counts, dict):
        return {}
    result: dict[int, int] = {}
    for key, value in raw_counts.items():
        try:
            key_int = int(key)
        except (TypeError, ValueError):
            continue
        result[key_int] = as_int(value, default=0)
    return result


def parse_client_match_response(payload: dict[str, object]) -> ClientMatchResult:
    def _as_int(value: object, default: int = 0) -> int:
        if value is None:
            return default
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, (int, float, str)):
            try:
                return int(value)
            except (TypeError, ValueError):
                return default
        return default

    def _as_float(value: object, default: float = 0.0) -> float:
        if value is None:
            return default
        if isinstance(value, (int, float, str)):
            try:
                return float(value)
            except (TypeError, ValueError):
                return default
        return default

    client_id = _as_int(payload.get("client_id", 0))
    total_unique = _as_int(payload.get("total_unique_offers", 0))
    demande_results_raw = payload.get("demande_results", [])
    demande_results: list[MatchResult] = []

    if isinstance(demande_results_raw, list):
        for item in demande_results_raw:
            if not isinstance(item, dict):
                continue
            demande_results.append(parse_match_result(item, _as_int=_as_int, _as_float=_as_float))

    return ClientMatchResult(
        client_id=client_id, total_unique_offers=total_unique, demande_results=demande_results
    )


def parse_match_result(
    item: dict[str, object],
    *,
    _as_int: Callable[[object, int], int] | None = None,
    _as_float: Callable[[object, float], float] | None = None,
) -> MatchResult:
    def _default_as_int(value: object, default: int = 0) -> int:
        if value is None:
            return default
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, (int, float, str)):
            try:
                return int(value)
            except (TypeError, ValueError):
                return default
        return default

    def _default_as_float(value: object, default: float = 0.0) -> float:
        if value is None:
            return default
        if isinstance(value, (int, float, str)):
            try:
                return float(value)
            except (TypeError, ValueError):
                return default
        return default

    as_int_fn = _as_int or _default_as_int
    as_float_fn = _as_float or _default_as_float

    matches_raw = item.get("matches", [])
    matches: list[OfferMatch] = []
    if isinstance(matches_raw, list):
        for match in matches_raw:
            if not isinstance(match, dict):
                continue
            offer_raw = match.get("offer", {})
            if not isinstance(offer_raw, dict):
                continue
            offer = Offer.from_row(offer_raw)
            matches.append(
                OfferMatch(
                    listing_id=as_int_fn(match.get("listing_id", offer.listing_id), 0),
                    offer=offer,
                    score=as_float_fn(match.get("score", 0.0), 0.0),
                )
            )

    return MatchResult(
        demande_id=as_int_fn(item.get("demande_id", 0), 0),
        demande_summary=str(item.get("demande_summary", "")),
        matches=matches,
        total_count=as_int_fn(item.get("total_count", len(matches)), len(matches)),
    )
