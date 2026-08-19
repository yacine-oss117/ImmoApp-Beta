"""
Matching API views.
"""

from __future__ import annotations

import os
from collections.abc import Callable

from rest_framework import status
from rest_framework.decorators import permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from server.api.api_view import api_view
from server.api.route_registry import route
from server.async_task_identity import build_request_async_task_identity
from server.services import (
    match_all_scheduler,
    matches,
    work_admission,
)

from .request_schemas_cache import CacheIdsSerializer, MatchAllTargetAgencySerializer
from .response_schemas import (
    ClientMatchResultResponseSerializer,
    MatchResultResponseSerializer,
)
from .task_registry import register_task
from .tasks import (
    count_matches_all_clients_task,
    count_matches_all_demandes_task,
    count_matches_all_listings_task,
    count_matches_all_offers_task,
    expand_match_pairs_for_demande,
)
from .validation import validate_payload
from .view_helpers import error, is_superuser, parse_int

_MATCH_ALL_RETRY_AFTER = int(os.environ.get("MATCH_ALL_RETRY_AFTER_SECONDS", "10"))
_MATCH_ALL_BACKPRESSURE_LIMIT = 1
_MATCH_ALL_LEASE_SECONDS = int(os.environ.get("MATCH_ALL_ACTIVE_TASK_TTL_SECONDS", "1800"))
_MATCH_ALL_TASK_NAME = "matches_all"
_MISSING_IDS_CODE = "MISSING_IDS"
_INVALID_IDS_CODE = "INVALID_IDS"
_MATCH_ALL_DISABLED_CODE = "MATCH_ALL_DISABLED"


def _match_all_disabled() -> bool:
    value = os.environ.get("IMMOAPP_DISABLE_MATCH_ALL_ENDPOINTS", "0").strip().lower()
    return value in {"1", "true", "yes", "on"}


def _stream_key(kind: str) -> str:
    return f"{kind}:all"


def _coalesced_or_backpressured_task(
    *,
    kind: str,
    request: Request,
    launch_task: Callable[[dict[str, object]], object],
) -> Response:
    if _match_all_disabled():
        return Response(
            {
                "code": _MATCH_ALL_DISABLED_CODE,
                "detail": "Tenant-wide match-all recompute is disabled by runtime policy.",
            },
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    if not is_superuser(request):
        return error("Forbidden", status.HTTP_403_FORBIDDEN)
    target_agency_id, error_response = _parse_match_all_target_agency(request)
    if error_response is not None:
        return error_response
    assert target_agency_id is not None
    task_identity = build_request_async_task_identity(request, agency_id=target_agency_id)
    if task_identity is None:
        return error("Agency scope is required", status.HTTP_400_BAD_REQUEST)
    admission = work_admission.admit_match_all(
        agency_id=target_agency_id,
        task_name=_MATCH_ALL_TASK_NAME,
        default_limit=_MATCH_ALL_BACKPRESSURE_LIMIT,
        retry_after_seconds=_MATCH_ALL_RETRY_AFTER,
    )
    runtime_profile = str(admission.runtime_profile or "yellow")
    max_in_flight = max(1, int(admission.fair_share_limit or 1))
    if not admission.allowed:
        response = Response(
            {
                "code": "MATCH_ALL_BACKPRESSURE",
                "detail": "Backlog too high; retry later",
                "coalesced": False,
                "runtime_profile": runtime_profile,
                "fair_share_limit": max_in_flight,
                "admission_mode": admission.admission_mode,
            },
            status=status.HTTP_429_TOO_MANY_REQUESTS,
        )
        response["Retry-After"] = str(max(1, int(admission.retry_after or _MATCH_ALL_RETRY_AFTER)))
        return response

    scheduled = match_all_scheduler.schedule_tenant_fair_task(
        task_name=_MATCH_ALL_TASK_NAME,
        stream_key=_stream_key(kind),
        agency_id=target_agency_id,
        lease_seconds=_MATCH_ALL_LEASE_SECONDS,
        max_in_flight=max_in_flight,
        launch_task=lambda: launch_task(dict(task_identity)),
    )
    if scheduled["status"] == "coalesced":
        response = Response(
            {
                "task_id": scheduled["task_id"],
                "state": scheduled["state"],
                "coalesced": True,
                "runtime_profile": runtime_profile,
                "fair_share_limit": max_in_flight,
                "admission_mode": admission.admission_mode,
            },
            status=status.HTTP_202_ACCEPTED,
        )
        response["Retry-After"] = str(_MATCH_ALL_RETRY_AFTER)
        return response
    if scheduled["status"] == "backpressure":
        response = Response(
            {
                "code": "MATCH_ALL_BACKPRESSURE",
                "detail": "Backlog too high; retry later",
                "coalesced": False,
                "runtime_profile": runtime_profile,
                "fair_share_limit": max_in_flight,
                "admission_mode": admission.admission_mode,
            },
            status=status.HTTP_429_TOO_MANY_REQUESTS,
        )
        response["Retry-After"] = str(_MATCH_ALL_RETRY_AFTER)
        return response
    task_id = str(scheduled["task_id"] or "")
    if not task_id:
        return error("Failed to schedule task", status.HTTP_500_INTERNAL_SERVER_ERROR)
    register_task(
        task_id,
        user_id=getattr(request.user, "id", None),
        agency_id=target_agency_id,
    )
    response = Response(
        {
            "task_id": task_id,
            "coalesced": False,
            "runtime_profile": runtime_profile,
            "fair_share_limit": max_in_flight,
            "admission_mode": admission.admission_mode,
        },
        status=status.HTTP_202_ACCEPTED,
    )
    response["Retry-After"] = str(_MATCH_ALL_RETRY_AFTER)
    return response


def _parse_match_all_target_agency(request: Request) -> tuple[int | None, Response | None]:
    payload, error_response = validate_payload(
        request.data if isinstance(request.data, dict) else {},
        MatchAllTargetAgencySerializer,
        partial=False,
    )
    if error_response is not None:
        return None, error_response
    agency = (payload or {}).get("agency_id")
    if isinstance(agency, int):
        return int(agency), None
    return None, error("Agency scope is required", status.HTTP_400_BAD_REQUEST)


def _parse_ids_payload(request: Request) -> tuple[list[int] | None, Response | None]:
    if request.method == "POST":
        payload = request.data if isinstance(request.data, dict) else {}
        raw_ids = payload.get("ids")
        if raw_ids is None or raw_ids == []:
            return [], None
        validated, error_response = validate_payload(payload, CacheIdsSerializer)
        if error_response is not None:
            return None, error_response
        validated_ids = (validated or {}).get("ids", [])
        ids = [int(v) for v in validated_ids] if isinstance(validated_ids, list) else []
        return ids, None

    raw_values = list(request.query_params.getlist("id")) + list(
        request.query_params.getlist("ids")
    )
    if len(raw_values) == 1 and "," in raw_values[0]:
        raw_values = [part.strip() for part in raw_values[0].split(",")]

    parsed_ids: list[int] = []
    for value in raw_values:
        token = str(value).strip()
        if not token:
            continue
        if not token.isdigit():
            return None, Response(
                {
                    "code": _INVALID_IDS_CODE,
                    "detail": "All ids must be positive integers.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        parsed = int(token)
        if parsed <= 0:
            return None, Response(
                {
                    "code": _INVALID_IDS_CODE,
                    "detail": "All ids must be positive integers.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        parsed_ids.append(parsed)
    return parsed_ids, None


def _missing_ids_response(*, kind: str) -> Response:
    return Response(
        {
            "code": _MISSING_IDS_CODE,
            "detail": (
                "This endpoint is batch-only. Provide one or more ids via `id`/`ids` "
                "query params or POST payload. For full-tenant recomputation use the "
                "admin async endpoint."
            ),
            "async_endpoint": f"/api/v1/matches/{kind}/all/",
        },
        status=status.HTTP_400_BAD_REQUEST,
    )


@route("matches/client/<int:client_id>/", order=40)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def matches_for_client(request: Request, client_id: int) -> Response:
    """Return matches for a specific client."""
    limit = parse_int(request.query_params.get("limit"), default=50) or 50
    result = matches.get_matches_for_client(client_id, limit_per_demande=limit)
    return Response({"item": ClientMatchResultResponseSerializer(result).data})


@route("matches/demandes/<int:demande_id>/", order=41)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def matches_for_demande(request: Request, demande_id: int) -> Response:
    """Return matches for a specific demande with pagination."""
    limit = parse_int(request.query_params.get("limit"), default=50) or 50
    offset = parse_int(request.query_params.get("offset"), default=0) or 0
    threshold = request.query_params.get("threshold")
    result = matches.get_matches_for_demande(
        demande_id,
        limit=limit,
        offset=offset,
        score_threshold=threshold,
    )
    if result is None:
        return Response({"item": None})
    return Response({"item": MatchResultResponseSerializer(result).data})


@route("matches/demandes/<int:demande_id>/expand/", order=42)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def matches_expand_demande(request: Request, demande_id: int) -> Response:
    """Trigger expansion to compute all match pairs for a demande."""
    task_identity = build_request_async_task_identity(request)
    if task_identity is None:
        return error("Agency scope is required", status.HTTP_400_BAD_REQUEST)
    resolved_agency_id = task_identity["agency_id"]
    assert isinstance(resolved_agency_id, int)
    task = expand_match_pairs_for_demande.delay(demande_id, **task_identity)
    register_task(task.id, user_id=getattr(request.user, "id", None), agency_id=resolved_agency_id)
    return Response({"task_id": task.id})


@route("matches/clients/counts/", order=43)
@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def matches_count_clients(request: Request) -> Response:
    """Return match counts for selected clients (batch-only)."""
    ids, error_response = _parse_ids_payload(request)
    if error_response is not None:
        return error_response
    if not ids:
        return _missing_ids_response(kind="clients")
    counts = matches.count_matches_for_clients(ids)
    return Response({"counts": counts})


@route("matches/clients/all/", order=44)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def matches_count_all_clients(request: Request) -> Response:
    """Trigger background count for all clients (admin/internal async endpoint)."""
    return _coalesced_or_backpressured_task(
        kind="clients",
        request=request,
        launch_task=lambda task_identity: count_matches_all_clients_task.apply_async(
            kwargs=task_identity,
            queue="rebuild_batch",
        ),
    )


@route("matches/demandes/all/", order=46)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def matches_count_all_demandes(request: Request) -> Response:
    """Trigger background count for all demandes (admin/internal async endpoint)."""
    return _coalesced_or_backpressured_task(
        kind="demandes",
        request=request,
        launch_task=lambda task_identity: count_matches_all_demandes_task.apply_async(
            kwargs=task_identity,
            queue="rebuild_batch",
        ),
    )


@route("matches/listings/all/", order=50)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def matches_count_all_listings(request: Request) -> Response:
    """Trigger background count for all listings (admin/internal async endpoint)."""
    return _coalesced_or_backpressured_task(
        kind="listings",
        request=request,
        launch_task=lambda task_identity: count_matches_all_listings_task.apply_async(
            kwargs=task_identity,
            queue="rebuild_batch",
        ),
    )


@route("matches/offers/all/", order=51)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def matches_count_all_offers(request: Request) -> Response:
    """Trigger background count for all offers (admin/internal async endpoint)."""
    return _coalesced_or_backpressured_task(
        kind="offers",
        request=request,
        launch_task=lambda task_identity: count_matches_all_offers_task.apply_async(
            kwargs=task_identity,
            queue="rebuild_batch",
        ),
    )


@route("matches/clients/wilaya/", order=45)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def matches_count_wilaya_clients(request: Request) -> Response:
    """Return match counts for a wilaya."""
    wilaya_id = parse_int(request.query_params.get("wilaya_id"))
    wilaya = request.query_params.get("wilaya")
    results = matches.count_matches_for_wilaya_clients(wilaya_id=wilaya_id, wilaya=wilaya)
    return Response({"counts": results})


@route("matches/demandes/counts/", order=47)
@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def matches_count_demandes(request: Request) -> Response:
    """Return match counts for selected demandes (batch-only)."""
    ids, error_response = _parse_ids_payload(request)
    if error_response is not None:
        return error_response
    if not ids:
        return _missing_ids_response(kind="demandes")
    results = matches.count_matches_for_demandes(ids)
    return Response({"counts": results})


@route("matches/listings/counts/", order=48)
@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def matches_count_listings(request: Request) -> Response:
    """Return match counts for selected listings (batch-only)."""
    ids, error_response = _parse_ids_payload(request)
    if error_response is not None:
        return error_response
    if not ids:
        return _missing_ids_response(kind="listings")
    results = matches.count_matches_for_listings(ids)
    return Response({"counts": results})


@route("matches/offers/counts/", order=49)
@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def matches_count_offers(request: Request) -> Response:
    """Return match counts for selected offers (batch-only)."""
    ids, error_response = _parse_ids_payload(request)
    if error_response is not None:
        return error_response
    if not ids:
        return _missing_ids_response(kind="offers")
    results = matches.count_matches_for_offers(ids)
    return Response({"counts": results})
