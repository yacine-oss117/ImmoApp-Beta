"""
Match fetch helpers (client/demande).
"""

from __future__ import annotations

from app.services.api_client import api_get, api_post, as_dict
from app.services.match_parsers import parse_client_match_response, parse_match_result
from core.matcher.match_models import ClientMatchResult, MatchResult


def get_matches_for_client(
    client_id: int,
    limit_per_demande: int = 50,
    score_threshold: float = 0.0,
) -> ClientMatchResult:
    """Get detailed match results for a client, grouped by demande."""
    response = api_get(
        f"/matches/client/{client_id}",
        params={"limit": limit_per_demande, "threshold": score_threshold},
    )
    payload = as_dict(response)
    item = payload.get("item")
    match_payload = item if isinstance(item, dict) else payload
    return parse_client_match_response(match_payload)


def get_matches_for_demande(
    demande_id: int,
    *,
    limit: int = 50,
    offset: int = 0,
    score_threshold: float = 0.0,
) -> MatchResult | None:
    """Fetch matches for a single demande with pagination."""
    response = api_get(
        f"/matches/demandes/{demande_id}",
        params={"limit": limit, "offset": offset, "threshold": score_threshold},
    )
    payload = as_dict(response)
    item = payload.get("item")
    if not isinstance(item, dict):
        return None
    return parse_match_result(item)


def expand_matches_for_demande(demande_id: int) -> str | None:
    """Trigger background expansion to compute all matches for a demande."""
    response = api_post(f"/matches/demandes/{demande_id}/expand/", {})
    payload = as_dict(response)
    task_id = payload.get("task_id")
    return task_id if isinstance(task_id, str) and task_id else None
