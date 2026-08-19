"""
Listing list and search endpoints.
"""

from __future__ import annotations

import logging
from typing import cast

from rest_framework import status
from rest_framework.decorators import permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from server.api.api_view import api_view
from server.api.query_budget import guard_estimated_scan_rows
from server.api.route_registry import route
from server.services import e2e_control, listings
from server.services.cache_control import CacheNamespace
from server.services.cache_layers import get_response_cache
from server.services.cache_policies import LISTINGS_COUNT_POLICY, LISTINGS_LIST_POLICY
from server.services.cursor_pagination import normalize_limit
from server.services.errors import ConflictError, NotFoundError
from server.services.types import ListingInput

from .idempotency import check_idempotency, store_idempotency
from .request_schemas import ListingPayloadSerializer
from .response_schemas import ListingResponseSerializer
from .validation import validate_payload
from .view_helpers import (
    actor,
    conflict_error,
    error,
    parse_bool,
    parse_int,
    safe_error_message,
    safe_not_found_message,
)
from .view_helpers import (
    agency_id as request_agency_id,
)

logger = logging.getLogger(__name__)


@route("listings/", order=23)
@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def listings_list(request: Request) -> Response:
    """List or create listings."""
    if request.method == "POST":
        idem_ctx, idem_response = check_idempotency(request)
        if idem_response:
            return idem_response
        payload, error_response = validate_payload(
            request.data if isinstance(request.data, dict) else {},
            ListingPayloadSerializer,
            partial=False,
        )
        if error_response:
            return error_response
        try:
            listing_input = cast(ListingInput, payload or {})
            listing_id = listings.upsert_listing(listing_input, actor=actor(request))
        except ConflictError as exc:
            return conflict_error(
                str(exc),
                current_version=exc.current_version,
                current_record=exc.current_record,
            )
        except NotFoundError as exc:
            return error(safe_not_found_message(exc), status.HTTP_404_NOT_FOUND)
        except ValueError as exc:
            return error(safe_error_message(exc), status.HTTP_400_BAD_REQUEST)
        created = listings.get_listing_by_id(int(listing_id))
        response_payload: dict[str, object] = {"id": listing_id}
        if created is not None:
            response_payload["item"] = ListingResponseSerializer(created).data
        if e2e_control.e2e_test_mode_enabled():
            logger.info(
                "E2E listing create response snapshot listing_id=%s visible=%s admin=%s",
                int(listing_id),
                created is not None,
                e2e_control.inspect_entity_state(
                    entity_type="listing",
                    record_id=int(listing_id),
                ),
            )
        response = Response(response_payload, status=status.HTTP_201_CREATED)
        return store_idempotency(idem_ctx, response, request)

    limit = normalize_limit(request.query_params.get("limit"), default=50, minimum=1, maximum=200)
    offset = parse_int(request.query_params.get("offset"), default=0) or 0
    cursor = parse_int(request.query_params.get("cursor"))
    search = request.query_params.get("search", "")
    status_param = request.query_params.get("status", "available")
    include_deleted = parse_bool(request.query_params.get("include_deleted"), False)

    if cursor is not None:
        budget_response = guard_estimated_scan_rows(
            request,
            estimated_scan_rows=limit,
        )
        if budget_response is not None:
            return budget_response
        limit_value = limit
        items = listings.fetch_listings_cursor(
            limit=limit_value,
            cursor=cursor,
            search=search,
            status=status_param,
            include_deleted=include_deleted,
        )
        total = listings.get_total_listing_count(
            search=search,
            status=status_param,
            include_deleted=include_deleted,
        )
        next_cursor = items[-1].id if len(items) == limit_value else None

        data = ListingResponseSerializer(items, many=True).data
        return Response({"items": data, "total": total, "next_cursor": next_cursor})

    budget_response = guard_estimated_scan_rows(
        request,
        estimated_scan_rows=limit + offset,
    )
    if budget_response is not None:
        return budget_response

    user = getattr(request, "user", None)
    user_id = (
        int(getattr(user, "id", 0)) if user and getattr(user, "is_authenticated", False) else None
    )
    agency_id = request_agency_id(request)
    surface_generation = (
        listings.get_listings_surface_generation(agency_id=agency_id)
        if agency_id is not None
        else None
    )
    cache_key = (
        agency_id,
        user_id,
        limit,
        offset,
        str(search or ""),
        status_param if status_param is not None else None,
        bool(include_deleted),
        surface_generation,
    )
    use_cache = agency_id is not None
    use_cache = use_cache and (cursor is not None or (offset + limit <= 500))
    if search and not LISTINGS_LIST_POLICY["cache_search_queries"]:
        use_cache = False
    if use_cache:
        payload = cast(
            dict[str, object],
            get_response_cache().get_or_fill(
                namespace=CacheNamespace.LISTINGS_LIST,
                agency_id=agency_id,
                actor_id=user_id,
                query_key=cache_key,
                policy=LISTINGS_LIST_POLICY,
                fill_fn=lambda: _build_listings_list_payload(
                    limit=limit,
                    offset=offset,
                    search=search,
                    status_param=status_param,
                    include_deleted=include_deleted,
                ),
            ),
        )
        return Response(payload)
    payload = _build_listings_list_payload(
        limit=limit,
        offset=offset,
        search=search,
        status_param=status_param,
        include_deleted=include_deleted,
    )
    return Response(payload)


@route("listings/count/", order=25)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def listings_count(request: Request) -> Response:
    """Return total listing count for filters."""
    search = request.query_params.get("search", "")
    status_param = request.query_params.get("status", "available")
    include_deleted = parse_bool(request.query_params.get("include_deleted"), False)
    user = getattr(request, "user", None)
    user_id = (
        int(getattr(user, "id", 0)) if user and getattr(user, "is_authenticated", False) else None
    )
    agency_id = request_agency_id(request)
    if agency_id is None:
        return Response(
            {
                "total": listings.get_total_listing_count(
                    search=search,
                    status=status_param,
                    include_deleted=include_deleted,
                )
            }
        )
    surface_generation = listings.get_listings_surface_generation(agency_id=agency_id)
    payload = cast(
        dict[str, object],
        get_response_cache().get_or_fill(
            namespace=CacheNamespace.LISTINGS_COUNT,
            agency_id=agency_id,
            actor_id=user_id,
            query_key=(
                agency_id,
                user_id,
                search,
                status_param,
                bool(include_deleted),
                surface_generation,
            ),
            policy=LISTINGS_COUNT_POLICY,
            fill_fn=lambda: {
                "total": listings.get_total_listing_count(
                    search=search,
                    status=status_param,
                    include_deleted=include_deleted,
                )
            },
        ),
    )
    return Response(payload)


@route("listings/deleted/", order=26)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def listings_deleted(request: Request) -> Response:
    """Return soft-deleted listings."""
    limit = normalize_limit(request.query_params.get("limit"), default=50, minimum=1, maximum=200)
    offset = parse_int(request.query_params.get("offset"), default=0) or 0
    search = request.query_params.get("search", "")
    items = listings.fetch_deleted_listings(limit=limit, offset=offset, search=search)
    total = listings.get_total_deleted_listing_count(search=search)

    data = ListingResponseSerializer(items, many=True).data
    return Response({"items": data, "total": total})


@route("listings/phone-duplicates/", order=27)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def listing_phone_duplicates(request: Request) -> Response:
    """Return duplicate listing IDs by phone."""
    phone = request.query_params.get("phone", "").strip()
    if not phone:
        return error("phone is required", status.HTTP_400_BAD_REQUEST)
    exclude_id = parse_int(request.query_params.get("exclude_id"))
    ids = listings.find_listing_ids_by_phone(phone, exclude_id)
    return Response({"ids": ids})


__all__ = [
    "listing_phone_duplicates",
    "listings_count",
    "listings_deleted",
    "listings_list",
]


def _build_listings_list_payload(
    *,
    limit: int,
    offset: int,
    search: str,
    status_param: str | None,
    include_deleted: bool,
) -> dict[str, object]:
    items, total = listings.fetch_listings_with_count(
        limit=limit,
        offset=offset,
        search=search,
        status=status_param,
        include_deleted=include_deleted,
    )
    data = ListingResponseSerializer(items, many=True).data
    return {"items": data, "total": total}
