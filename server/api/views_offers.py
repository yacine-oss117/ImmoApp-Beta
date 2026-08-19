"""
Offer-related API views.
"""

from __future__ import annotations

from typing import cast

from rest_framework import status
from rest_framework.decorators import permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from server.api.api_view import api_view
from server.api.idempotency_engine import check_idempotency, store_idempotency
from server.api.route_registry import route
from server.services import offer_photos, offers
from server.services.errors import ConflictError, NotFoundError
from server.services.types import OfferInput

from .rbac import require_hard_delete
from .request_schemas import OfferPayloadSerializer, OfferPhotoCreateSerializer
from .validation import validate_payload
from .view_helpers import (
    actor,
    conflict_error,
    error,
    parse_bool,
    parse_int,
    require_confirmation,
    safe_error_message,
    safe_not_found_message,
)


@route("offers/deleted/", order=34)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def offers_deleted(request: Request) -> Response:
    """Return soft-deleted offers."""
    from .response_schemas import OfferResponseSerializer

    limit = parse_int(request.query_params.get("limit"))
    offset = parse_int(request.query_params.get("offset"), default=0) or 0
    items = offers.fetch_deleted_offers(limit=limit, offset=offset)
    total = offers.get_total_deleted_offer_count()

    data = OfferResponseSerializer(items, many=True).data
    return Response({"items": data, "total": total})


@route("offers/<int:offer_id>/photos/", order=36)
@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def offer_photos_endpoint(request: Request, offer_id: int) -> Response:
    """List or attach photos for an offer."""
    if request.method == "GET":
        from .response_schemas import OfferPhotoResponseSerializer

        include_deleted = parse_bool(request.query_params.get("include_deleted"), False)
        items = offer_photos.list_offer_photos(
            offer_id=offer_id,
            include_deleted=include_deleted,
        )
        data = OfferPhotoResponseSerializer(items, many=True).data
        return Response({"items": data, "total": len(data)})

    payload, error_response = validate_payload(
        request.data if isinstance(request.data, dict) else {},
        OfferPhotoCreateSerializer,
        partial=False,
    )
    if error_response:
        return error_response
    from .response_schemas import OfferPhotoResponseSerializer

    idem_ctx, idem_response = check_idempotency(request)
    if idem_response:
        return idem_response
    payload = payload or {}
    try:
        position_raw = payload.get("position")
        position = position_raw if isinstance(position_raw, int) else 0
        attach_result = offer_photos.add_offer_photo(
            offer_id=offer_id,
            storage_id=str(payload.get("storage_id")),
            position=position,
            user_id=getattr(request.user, "id", None),
            role=getattr(request.user, "role", None),
            created_ip=request.META.get("REMOTE_ADDR"),
        )
        photo_id = attach_result.photo_id
    except NotFoundError as exc:
        return error(safe_not_found_message(exc), status.HTTP_404_NOT_FOUND)
    except ValueError as exc:
        return error(safe_error_message(exc), status.HTTP_400_BAD_REQUEST)
    photo = offer_photos.get_offer_photo_by_id(photo_id=photo_id)
    item = OfferPhotoResponseSerializer(photo or {"id": photo_id, "offer_id": offer_id}).data
    response = Response({"id": photo_id, "item": item}, status=attach_result.status_code)
    return store_idempotency(idem_ctx, response, request)


@route("offers/photos/<int:photo_id>/", order=37)
@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def offer_photo_delete(request: Request, photo_id: int) -> Response:
    """Soft-delete a single offer photo."""
    idem_ctx, idem_response = check_idempotency(request)
    if idem_response:
        return idem_response

    deleted = offer_photos.delete_offer_photo(
        photo_id=photo_id,
        user_id=getattr(request.user, "id", None),
        role=getattr(request.user, "role", None),
        created_ip=request.META.get("REMOTE_ADDR"),
    )
    if not deleted:
        response = error("Offer photo not found", status.HTTP_404_NOT_FOUND)
        return store_idempotency(idem_ctx, response, request)
    response = Response(status=status.HTTP_204_NO_CONTENT)
    return store_idempotency(idem_ctx, response, request)


@route("offers/<int:offer_id>/", order=35)
@api_view(["GET", "PUT", "DELETE"])
@permission_classes([IsAuthenticated])
def offer_detail(request: Request, offer_id: int) -> Response:
    """Get, update, or delete an offer."""
    if request.method == "GET":
        from .response_schemas import OfferResponseSerializer

        include_deleted = parse_bool(request.query_params.get("include_deleted"), False)
        offer = offers.get_offer_by_id(offer_id, include_deleted=include_deleted)
        if not offer:
            return error("Offer not found", status.HTTP_404_NOT_FOUND)

        data = OfferResponseSerializer(offer).data
        return Response(data)

    if request.method == "PUT":
        idem_ctx, idem_response = check_idempotency(request)
        if idem_response:
            return idem_response

        data, error_response = validate_payload(
            request.data if isinstance(request.data, dict) else {},
            OfferPayloadSerializer,
            partial=True,
            require_row_version=True,
        )
        if error_response:
            return error_response

        payload_dict = data or {}
        payload_dict["id"] = offer_id
        offer_input = cast(OfferInput, payload_dict)

        try:
            offers.update_offer(offer_id, offer_input, actor=actor(request))
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

        response = Response(status=status.HTTP_204_NO_CONTENT)
        return store_idempotency(idem_ctx, response, request)

    # DELETE
    idem_ctx, idem_response = check_idempotency(request)
    if idem_response:
        return idem_response

    offers.delete_offer(offer_id, actor=actor(request))
    response = Response(status=status.HTTP_204_NO_CONTENT)
    return store_idempotency(idem_ctx, response, request)


@route("offers/<int:offer_id>/restore/", order=38)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def offer_restore(request: Request, offer_id: int) -> Response:
    """Restore a deleted offer."""
    idem_ctx, idem_response = check_idempotency(request)
    if idem_response:
        return idem_response

    offers.restore_offer(offer_id, actor=actor(request))
    response = Response(status=status.HTTP_204_NO_CONTENT)
    return store_idempotency(idem_ctx, response, request)


@route("offers/<int:offer_id>/purge/", order=39)
@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def offer_purge(request: Request, offer_id: int) -> Response:
    """Purge an offer."""
    idem_ctx, idem_response = check_idempotency(request)
    if idem_response:
        return idem_response

    deny = require_hard_delete(request)
    if deny:
        return deny

    confirm = require_confirmation(request, f"PURGE_OFFER_{offer_id}")
    if confirm:
        return confirm
    offers.purge_offer(offer_id, actor=actor(request))
    response = Response(status=status.HTTP_204_NO_CONTENT)
    return store_idempotency(idem_ctx, response, request)
