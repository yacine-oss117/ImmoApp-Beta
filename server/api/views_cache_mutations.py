"""
Match cache mutation endpoints.
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

from .request_schemas import (
    CacheClientSerializer,
    CacheStoreCountSerializer,
    CacheStoreCountsSerializer,
    CacheWilayaSerializer,
)
from .validation import validate_payload
from .view_helpers import parse_int


def _payload_int(payload: dict[str, object], key: str) -> int:
    value = payload.get(key)
    return value if isinstance(value, int) else 0


@route("cache/match/count/", order=55)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def match_cache_store_count(request: Request) -> Response:
    """Store a single match count."""
    payload, error_response = validate_payload(
        request.data if isinstance(request.data, dict) else {},
        CacheStoreCountSerializer,
        partial=False,
    )
    if error_response:
        return error_response
    payload = payload or {}
    client_id = _payload_int(payload, "client_id")
    count = _payload_int(payload, "count")
    match_cache.store_count(client_id, count)
    return Response(status=status.HTTP_204_NO_CONTENT)


@route("cache/match/counts/", order=56)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def match_cache_store_counts(request: Request) -> Response:
    """Store multiple match counts."""
    validated, error_response = validate_payload(
        request.data if isinstance(request.data, dict) else {},
        CacheStoreCountsSerializer,
        partial=False,
    )
    if error_response:
        return error_response
    counts = (validated or {}).get("counts") or {}
    payload = (
        {
            int(key): int(value)
            for key, value in counts.items()
            if isinstance(key, str) and isinstance(value, int)
        }
        if isinstance(counts, dict)
        else {}
    )
    match_cache.store_counts_batch(payload)
    return Response(status=status.HTTP_204_NO_CONTENT)


@route("cache/match/mark-all/", order=57)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def match_cache_mark_all_dirty(request: Request) -> Response:
    """Mark all cache entries dirty."""
    match_cache.mark_all_dirty()
    return Response(status=status.HTTP_204_NO_CONTENT)


@route("cache/match/mark-client/", order=58)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def match_cache_mark_client_dirty(request: Request) -> Response:
    """Mark a client cache entry dirty."""
    validated, error_response = validate_payload(
        request.data if isinstance(request.data, dict) else {},
        CacheClientSerializer,
        partial=False,
    )
    if error_response:
        return error_response
    client_id = _payload_int(validated or {}, "client_id")
    match_cache.mark_client_dirty(client_id)
    return Response(status=status.HTTP_204_NO_CONTENT)


@route("cache/match/mark-wilaya/", order=59)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def match_cache_mark_wilaya_dirty(request: Request) -> Response:
    """Mark a wilaya cache entry dirty."""
    validated, error_response = validate_payload(
        request.data if isinstance(request.data, dict) else {},
        CacheWilayaSerializer,
        partial=False,
    )
    if error_response:
        return error_response
    validated = validated or {}
    wilaya_id_raw = validated.get("wilaya_id")
    wilaya_id = parse_int(wilaya_id_raw) if isinstance(wilaya_id_raw, str) else None
    wilaya = validated.get("wilaya")
    match_cache.mark_clients_in_wilaya_dirty(
        wilaya_id, wilaya=str(wilaya) if wilaya is not None else None
    )
    return Response(status=status.HTTP_204_NO_CONTENT)


@route("cache/match/clear/", order=60)
@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def match_cache_clear(request: Request) -> Response:
    """Clear the match cache."""
    match_cache.clear_all()
    return Response(status=status.HTTP_204_NO_CONTENT)


__all__ = [
    "match_cache_clear",
    "match_cache_mark_all_dirty",
    "match_cache_mark_client_dirty",
    "match_cache_mark_wilaya_dirty",
    "match_cache_store_count",
    "match_cache_store_counts",
]
