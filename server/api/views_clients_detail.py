"""
Client detail, restore, and purge endpoints.
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
from server.services import clients
from server.services.errors import ConflictError, NotFoundError
from server.services.types import ClientInput

from .idempotency import check_idempotency, store_idempotency
from .rbac import require_hard_delete
from .request_schemas import ClientPayloadSerializer
from .response_schemas import ClientResponseSerializer
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


@route("clients/<int:client_id>/", order=14)
@api_view(["GET", "PUT", "DELETE"])
@permission_classes([IsAuthenticated])
def client_detail(request: Request, client_id: int) -> Response:
    """Get, update, or delete a client."""
    if request.method == "GET":
        include_deleted = parse_bool(request.query_params.get("include_deleted"), False)
        client = clients.get_client_by_id(client_id, include_deleted=include_deleted)
        if not client:
            return error("Client not found", status.HTTP_404_NOT_FOUND)

        data = ClientResponseSerializer(client).data
        return Response(data)

    if request.method == "PUT":
        idem_ctx, idem_response = check_idempotency(request)
        if idem_response:
            return idem_response

        data, error_response = validate_payload(
            request.data if isinstance(request.data, dict) else {},
            ClientPayloadSerializer,
            partial=True,
            require_row_version=True,
        )
        if error_response:
            return error_response

        client_input = cast(ClientInput, data or {})
        client_input["id"] = client_id

        try:
            result_id = clients.upsert_client(client_input, actor=actor(request))
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

    clients.delete_client(client_id, actor=actor(request))
    response = Response(status=status.HTTP_204_NO_CONTENT)
    return store_idempotency(idem_ctx, response, request)


@route("clients/<int:client_id>/restore/", order=15)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def client_restore(request: Request, client_id: int) -> Response:
    """Restore a deleted client."""
    idem_ctx, idem_response = check_idempotency(request)
    if idem_response:
        return idem_response

    clients.restore_client(client_id, actor=actor(request))
    response = Response(status=status.HTTP_204_NO_CONTENT)
    return store_idempotency(idem_ctx, response, request)


@route("clients/<int:client_id>/purge/", order=16)
@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def client_purge(request: Request, client_id: int) -> Response:
    """Purge a client and related data."""
    idem_ctx, idem_response = check_idempotency(request)
    if idem_response:
        return idem_response

    deny = require_hard_delete(request)
    if deny:
        return deny

    confirm = require_confirmation(request, f"PURGE_CLIENT_{client_id}")
    if confirm:
        return confirm
    clients.purge_client(client_id, actor=actor(request))
    response = Response(status=status.HTTP_204_NO_CONTENT)
    return store_idempotency(idem_ctx, response, request)


__all__ = ["client_detail", "client_purge", "client_restore"]
