"""
Match cache status/read endpoints.
"""

from __future__ import annotations

from rest_framework import status
from rest_framework.decorators import permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from server.api.api_view import api_view
from server.api.route_registry import route
from server.services import match_cache

from .request_schemas import CacheIdsSerializer
from .validation import validate_payload
from .view_helpers import error, parse_int


@route("cache/match/status/", order=50)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def match_cache_status(request: Request) -> Response:
    """Return match cache status."""
    _ = request
    is_clean = match_cache.is_cache_clean()
    dirty_count = match_cache.get_dirty_client_count()
    missing_count = match_cache.get_missing_client_count()
    return Response(
        {
            "is_clean": is_clean,
            "dirty": dirty_count,
            "missing": missing_count,
        }
    )


@route("cache/match/dirty/", order=51)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def match_cache_dirty(request: Request) -> Response:
    """Return dirty match cache entries."""
    limit = parse_int(request.query_params.get("limit"), default=100) or 100
    after_id = parse_int(request.query_params.get("after_id"), default=0) or 0
    ids, next_cursor, has_more = match_cache.get_dirty_client_ids_page(
        limit=limit,
        after_id=after_id,
    )
    return Response({"ids": ids, "next_cursor": next_cursor, "has_more": has_more})


@route("cache/match/missing/", order=52)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def match_cache_missing(request: Request) -> Response:
    """Return missing match cache entries."""
    limit = parse_int(request.query_params.get("limit"), default=100) or 100
    after_id = parse_int(request.query_params.get("after_id"), default=0) or 0
    ids, next_cursor, has_more = match_cache.get_missing_client_ids_page(
        limit=limit,
        after_id=after_id,
    )
    return Response({"ids": ids, "next_cursor": next_cursor, "has_more": has_more})


@route("cache/match/get/", order=53)
@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def match_cache_get_counts(request: Request) -> Response:
    """Return match cache counts for a list of client IDs."""
    payload = request.data if isinstance(request.data, dict) else {}
    ids: list[int] = []
    if request.method == "POST" or "ids" in payload:
        validated, error_response = validate_payload(payload, CacheIdsSerializer, partial=False)
        if error_response:
            return error_response
        validated_ids = (validated or {}).get("ids", [])
        if isinstance(validated_ids, list):
            ids = [int(v) for v in validated_ids]
    else:
        raw_ids = request.query_params.getlist("client_id")
        ids = [int(i) for i in raw_ids if str(i).isdigit()]
    if not ids:
        return error("client_id is required", status.HTTP_400_BAD_REQUEST)
    counts, count_meta = match_cache.get_cached_counts_batch_with_meta(ids)
    return Response({"counts": counts, "count_meta": count_meta})


@route("cache/match/batch/", order=53)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def match_cache_batch_counts(request: Request) -> Response:
    """Alias for batch cache counts endpoint."""
    return match_cache_get_counts(request)


__all__ = [
    "match_cache_dirty",
    "match_cache_batch_counts",
    "match_cache_get_counts",
    "match_cache_missing",
    "match_cache_status",
]
