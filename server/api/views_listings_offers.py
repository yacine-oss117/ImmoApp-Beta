"""
Listing offers endpoints.
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
from server.services import offers
from server.services.types import OfferInput

from .idempotency import check_idempotency, store_idempotency
from .request_schemas import OfferPayloadSerializer
from .response_schemas import OfferResponseSerializer
from .validation import validate_payload
from .view_helpers import actor, error, list_response, parse_bool, parse_int, safe_error_message


@route("listings/<int:listing_id>/offers/", order=31)
@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def listing_offers(request: Request, listing_id: int) -> Response:
    """List offers for a listing."""
    if request.method == "POST":
        idem_ctx, idem_response = check_idempotency(request)
        if idem_response:
            return idem_response
        payload, error_response = validate_payload(
            request.data if isinstance(request.data, dict) else {},
            OfferPayloadSerializer,
            partial=False,
        )
        if error_response:
            return error_response
        try:
            offer_input = cast(OfferInput, payload or {})
            offer_id = offers.create_offer(listing_id, offer_input, actor=actor(request))
        except ValueError as exc:
            return error(safe_error_message(exc), status.HTTP_400_BAD_REQUEST)
        created = offers.get_offer_by_id(int(offer_id))
        response_payload: dict[str, object] = {"id": offer_id}
        if created is not None:
            response_payload["item"] = OfferResponseSerializer(created).data
        response = Response(response_payload, status=status.HTTP_201_CREATED)
        return store_idempotency(idem_ctx, response, request)

    limit = parse_int(request.query_params.get("limit"))
    offset = parse_int(request.query_params.get("offset"), default=0) or 0
    include_deleted = parse_bool(request.query_params.get("include_deleted"), False)
    items = offers.get_offers_for_listing(
        listing_id,
        limit=limit,
        offset=offset,
        include_deleted=include_deleted,
    )
    data = OfferResponseSerializer(items, many=True).data
    return list_response(data)


__all__ = ["listing_offers"]
