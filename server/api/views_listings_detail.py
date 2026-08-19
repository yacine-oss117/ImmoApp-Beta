"""
Listing detail, restore, and purge endpoints.
"""

from __future__ import annotations

from typing import cast

from rest_framework import status
from rest_framework.decorators import permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from server.api.api_view import api_view
from server.api.route_registry import route
from server.services import listings
from server.services.errors import ConflictError, NotFoundError
from server.services.types import ListingInput

from .idempotency import check_idempotency, store_idempotency
from .rbac import require_hard_delete
from .request_schemas import ListingPayloadSerializer
from .response_schemas import ListingResponseSerializer
from .validation import validate_payload
from .view_helpers import (
    actor,
    conflict_error,
    error,
    parse_bool,
    require_confirmation,
    safe_error_message,
    safe_not_found_message,
)


@route("listings/<int:listing_id>/", order=28)
@api_view(["GET", "PUT", "DELETE"])
@permission_classes([IsAuthenticated])
def listing_detail(request: Request, listing_id: int) -> Response:
    """Get, update, or delete a listing."""
    if request.method == "GET":
        include_deleted = parse_bool(request.query_params.get("include_deleted"), False)
        listing = listings.get_listing_by_id(listing_id, include_deleted=include_deleted)
        if not listing:
            return error("Listing not found", status.HTTP_404_NOT_FOUND)

        data = ListingResponseSerializer(listing).data
        return Response(data)

    if request.method == "PUT":
        idem_ctx, idem_response = check_idempotency(request)
        if idem_response:
            return idem_response

        data, error_response = validate_payload(
            request.data if isinstance(request.data, dict) else {},
            ListingPayloadSerializer,
            partial=True,
            require_row_version=True,
        )
        if error_response:
            return error_response

        listing_input = cast(ListingInput, data or {})
        listing_input["id"] = listing_id

        try:
            result_id = listings.upsert_listing(listing_input, actor=actor(request))
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
        response = Response({"id": result_id})
        return store_idempotency(idem_ctx, response, request)

    # DELETE
    idem_ctx, idem_response = check_idempotency(request)
    if idem_response:
        return idem_response

    listings.delete_listing(listing_id, actor=actor(request))
    response = Response(status=status.HTTP_204_NO_CONTENT)
    return store_idempotency(idem_ctx, response, request)


@route("listings/<int:listing_id>/restore/", order=29)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def listing_restore(request: Request, listing_id: int) -> Response:
    """Restore a deleted listing."""
    idem_ctx, idem_response = check_idempotency(request)
    if idem_response:
        return idem_response

    listings.restore_listing(listing_id, actor=actor(request))
    response = Response(status=status.HTTP_204_NO_CONTENT)
    return store_idempotency(idem_ctx, response, request)


@route("listings/<int:listing_id>/purge/", order=30)
@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def listing_purge(request: Request, listing_id: int) -> Response:
    """Purge a listing and related data."""
    idem_ctx, idem_response = check_idempotency(request)
    if idem_response:
        return idem_response

    deny = require_hard_delete(request)
    if deny:
        return deny

    confirm = require_confirmation(request, f"PURGE_LISTING_{listing_id}")
    if confirm:
        return confirm
    listings.purge_listing(listing_id, actor=actor(request))
    response = Response(status=status.HTTP_204_NO_CONTENT)
    return store_idempotency(idem_ctx, response, request)


__all__ = ["listing_detail", "listing_purge", "listing_restore"]
