"""
Client list and search endpoints.
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
from server.services import clients, e2e_control
from server.services.cache_control import CacheNamespace
from server.services.cache_layers import get_response_cache
from server.services.cache_policies import CLIENTS_COUNT_POLICY, CLIENTS_LIST_POLICY
from server.services.cursor_pagination import normalize_limit
from server.services.errors import ConflictError, NotFoundError
from server.services.types import ClientInput

from .idempotency import check_idempotency, store_idempotency
from .request_schemas import ClientPayloadSerializer
from .response_schemas import ClientResponseSerializer
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


@route("clients/", order=9)
@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def clients_list(request: Request) -> Response:
    """List or create clients."""
    if request.method == "POST":
        idem_ctx, idem_response = check_idempotency(request)
        if idem_response:
            return idem_response
        payload, error_response = validate_payload(
            request.data if isinstance(request.data, dict) else {},
            ClientPayloadSerializer,
            partial=False,
        )
        if error_response:
            return error_response
        try:
            client_input = cast(ClientInput, payload or {})
            client_id = clients.upsert_client(client_input, actor=actor(request))
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
        created = clients.get_client_by_id(int(client_id))
        response_payload: dict[str, object] = {"id": client_id}
        if created is not None:
            response_payload["item"] = ClientResponseSerializer(created).data
        if e2e_control.e2e_test_mode_enabled():
            logger.info(
                "E2E client create response snapshot client_id=%s visible=%s admin=%s",
                int(client_id),
                created is not None,
                e2e_control.inspect_entity_state(
                    entity_type="client",
                    record_id=int(client_id),
                ),
            )
        response = Response(response_payload, status=status.HTTP_201_CREATED)
        return store_idempotency(idem_ctx, response, request)

    limit = normalize_limit(request.query_params.get("limit"), default=50, minimum=1, maximum=200)
    offset = parse_int(request.query_params.get("offset"), default=0) or 0
    cursor = parse_int(request.query_params.get("cursor"))
    search = request.query_params.get("search", "")
    status_param = request.query_params.get("status", "active")
    include_deleted = parse_bool(request.query_params.get("include_deleted"), False)
    # fields used to be parsed here but logic was removed; keeping param for compatibility

    if cursor is not None:
        budget_response = guard_estimated_scan_rows(
            request,
            estimated_scan_rows=limit,
        )
        if budget_response is not None:
            return budget_response
        limit_value = limit
        items = clients.fetch_clients_cursor(
            limit=limit_value,
            cursor=cursor,
            search=search,
            status=status_param,
            include_deleted=include_deleted,
        )
        total = clients.get_total_client_count(
            search=search,
            status=status_param,
            include_deleted=include_deleted,
        )
        next_cursor = items[-1].id if len(items) == limit_value else None

        data = ClientResponseSerializer(items, many=True).data
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
        clients.get_clients_surface_generation(agency_id=agency_id)
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
    if search and not CLIENTS_LIST_POLICY["cache_search_queries"]:
        use_cache = False
    if use_cache:
        payload = cast(
            dict[str, object],
            get_response_cache().get_or_fill(
                namespace=CacheNamespace.CLIENTS_LIST,
                agency_id=agency_id,
                actor_id=user_id,
                query_key=cache_key,
                policy=CLIENTS_LIST_POLICY,
                fill_fn=lambda: _build_clients_list_payload(
                    limit=limit,
                    offset=offset,
                    search=search,
                    status_param=status_param,
                    include_deleted=include_deleted,
                ),
            ),
        )
        return Response(payload)
    payload = _build_clients_list_payload(
        limit=limit,
        offset=offset,
        search=search,
        status_param=status_param,
        include_deleted=include_deleted,
    )
    return Response(payload)


@route("clients/count/", order=11)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def clients_count(request: Request) -> Response:
    """Return total client count for filters."""
    search = request.query_params.get("search", "")
    status_param = request.query_params.get("status", "active")
    include_deleted = parse_bool(request.query_params.get("include_deleted"), False)
    user = getattr(request, "user", None)
    user_id = (
        int(getattr(user, "id", 0)) if user and getattr(user, "is_authenticated", False) else None
    )
    agency_id = request_agency_id(request)
    if agency_id is None:
        return Response(
            {
                "total": clients.get_total_client_count(
                    search=search,
                    status=status_param,
                    include_deleted=include_deleted,
                )
            }
        )
    surface_generation = clients.get_clients_surface_generation(agency_id=agency_id)
    payload = cast(
        dict[str, object],
        get_response_cache().get_or_fill(
            namespace=CacheNamespace.CLIENTS_COUNT,
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
            policy=CLIENTS_COUNT_POLICY,
            fill_fn=lambda: {
                "total": clients.get_total_client_count(
                    search=search,
                    status=status_param,
                    include_deleted=include_deleted,
                )
            },
        ),
    )
    return Response(payload)


@route("clients/deleted/", order=12)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def clients_deleted(request: Request) -> Response:
    """Return soft-deleted clients."""
    limit = normalize_limit(request.query_params.get("limit"), default=50, minimum=1, maximum=200)
    offset = parse_int(request.query_params.get("offset"), default=0) or 0
    search = request.query_params.get("search", "")
    items = clients.fetch_deleted_clients(limit=limit, offset=offset, search=search)
    total = clients.get_total_deleted_client_count(search=search)

    data = ClientResponseSerializer(items, many=True).data
    return Response({"items": data, "total": total})


@route("clients/phone-duplicates/", order=13)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def client_phone_duplicates(request: Request) -> Response:
    """Return duplicate client IDs by phone."""
    phone = request.query_params.get("phone", "").strip()
    if not phone:
        return error("phone is required", status.HTTP_400_BAD_REQUEST)
    exclude_id = parse_int(request.query_params.get("exclude_id"))
    ids = clients.find_client_ids_by_phone(phone, exclude_id)
    return Response({"ids": ids})


__all__ = [
    "client_phone_duplicates",
    "clients_count",
    "clients_deleted",
    "clients_list",
]


def _build_clients_list_payload(
    *,
    limit: int,
    offset: int,
    search: str,
    status_param: str | None,
    include_deleted: bool,
) -> dict[str, object]:
    items, total = clients.fetch_clients_with_count(
        limit=limit,
        offset=offset,
        search=search,
        status=status_param,
        include_deleted=include_deleted,
    )
    data = ClientResponseSerializer(items, many=True).data
    return {"items": data, "total": total}
