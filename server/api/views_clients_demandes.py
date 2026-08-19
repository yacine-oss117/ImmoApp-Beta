"""
Client demandes endpoints.
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
from server.services import demandes
from server.services.types import DemandeInput

from .idempotency import check_idempotency, store_idempotency
from .request_schemas import DemandePayloadSerializer
from .response_schemas import DemandeResponseSerializer
from .validation import validate_payload
from .view_helpers import (
    actor,
    error,
    list_response,
    parse_bool,
    parse_int,
    safe_error_message,
)


@route("clients/<int:client_id>/demandes/", order=17)
@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def client_demandes(request: Request, client_id: int) -> Response:
    """List or create demandes for a client."""
    if request.method == "POST":
        idem_ctx, idem_response = check_idempotency(request)
        if idem_response:
            return idem_response
        payload, error_response = validate_payload(
            request.data if isinstance(request.data, dict) else {},
            DemandePayloadSerializer,
            partial=False,
        )
        if error_response:
            return error_response
        try:
            payload = payload or {}
            payload["client_id"] = client_id
            demande_input = cast(DemandeInput, payload)

            demande_id = demandes.create_demande(
                client_id,
                demande_input,
                actor=actor(request),
            )
        except ValueError as exc:
            return error(safe_error_message(exc), status.HTTP_400_BAD_REQUEST)
        created = demandes.get_demande_by_id(int(demande_id))
        response_payload: dict[str, object] = {"id": demande_id}
        if created is not None:
            response_payload["item"] = DemandeResponseSerializer(created).data
        response = Response(response_payload, status=status.HTTP_201_CREATED)
        return store_idempotency(idem_ctx, response, request)

    limit = parse_int(request.query_params.get("limit"))
    offset = parse_int(request.query_params.get("offset"), default=0) or 0
    include_deleted = parse_bool(request.query_params.get("include_deleted"), False)
    items = demandes.get_demandes_for_client(
        client_id,
        limit=limit,
        offset=offset,
        include_deleted=include_deleted,
    )
    data = DemandeResponseSerializer(items, many=True).data
    return list_response(data)


__all__ = ["client_demandes"]
