"""
Match count helpers and background task orchestration.
"""

from __future__ import annotations

from app.models_cast import as_int
from app.services.api_client import api_get, api_post, as_dict
from app.services.api_types import ParamsDict
from app.services.match_parsers import parse_counts
from app.services.task_status import get_task_status
from app.utils.task_push import wait_for_task_notification


def count_matches_for_clients(client_ids: list[int]) -> dict[int, int]:
    """Count matches for a list of clients via the API."""
    if not client_ids:
        return {}

    response = api_post("/matches/clients/counts", {"ids": client_ids})
    return parse_counts(response)


def count_matches_for_all_clients() -> dict[int, int]:
    """Count matches for ALL clients using background jobs."""
    task_id = start_count_matches_for_all_clients()
    if not task_id:
        return {}
    return wait_for_task_counts(task_id)


def start_count_matches_for_all_clients() -> str | None:
    """Start a background job to count matches for all clients."""
    response = api_post("/matches/clients/all", {})
    payload = as_dict(response)
    task_id = payload.get("task_id")
    return task_id if isinstance(task_id, str) and task_id else None


def start_count_matches_for_all_demandes() -> str | None:
    """Start a background job to count matches for all demandes."""
    response = api_post("/matches/demandes/all", {})
    payload = as_dict(response)
    task_id = payload.get("task_id")
    return task_id if isinstance(task_id, str) and task_id else None


def wait_for_task_counts(task_id: str, *, max_wait_sec: float = 300.0) -> dict[int, int]:
    """Poll task status until complete and return counts payload."""
    payload = wait_for_task_notification(task_id, timeout_sec=min(30.0, max_wait_sec))
    if isinstance(payload, dict):
        status = payload.get("status")
        if status == "SUCCESS":
            result_payload = payload.get("result")
            if result_payload is not None:
                return parse_counts(result_payload)
            return parse_counts(get_task_status(task_id).get("result"))
        if status in {"FAILURE", "REVOKED"}:
            return {}

    import time

    started = time.monotonic()
    while True:
        payload = get_task_status(task_id)
        status = payload.get("status")
        if status == "SUCCESS":
            return parse_counts(payload.get("result"))
        if status in {"FAILURE", "REVOKED"}:
            return {}
        if time.monotonic() - started >= max_wait_sec:
            return {}
        time.sleep(0.5)


def count_matches_for_single_client(client_id: int) -> int:
    """Count matches for a single client using the API."""
    response = api_post("/matches/clients/counts", {"ids": [client_id]})
    return as_int(parse_counts(response).get(client_id, 0), default=0)


def count_matches_for_wilaya_clients(
    wilaya: str | None = None, wilaya_id: int | None = None
) -> dict[int, int]:
    """Count matches for all clients in a specific wilaya using UoW."""
    from app.services.lookup_service import get_wilaya_id

    resolved_id = wilaya_id
    if resolved_id is None and wilaya:
        resolved_id = get_wilaya_id(wilaya)
    params: ParamsDict = {"wilaya_id": resolved_id}
    if wilaya is not None:
        params["wilaya"] = wilaya
    response = api_get("/matches/clients/wilaya", params=params)
    return parse_counts(response)


def count_matches_for_listings(listing_ids: list[int]) -> dict[int, int]:
    """Count matching demandes for a list of listings via the API."""
    if not listing_ids:
        return {}
    response = api_post("/matches/listings/counts", {"ids": listing_ids})
    return parse_counts(response)


def count_matches_for_offers(offer_ids: list[int]) -> dict[int, int]:
    """Count matching demandes for a list of offers via the API."""
    if not offer_ids:
        return {}
    response = api_post("/matches/offers/counts", {"ids": offer_ids})
    return parse_counts(response)


def count_matches_for_demandes(demande_ids: list[int]) -> dict[int, int]:
    """Count matches for a list of demandes via the API."""
    if not demande_ids:
        return {}
    response = api_post("/matches/demandes/counts", {"ids": demande_ids})
    return parse_counts(response)
