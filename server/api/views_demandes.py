"""
Demande-related API views.
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
from server.services.errors import ConflictError, NotFoundError
from server.services.types import DemandeInput

from .rbac import require_hard_delete
from .request_schemas import DemandePayloadSerializer
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


@route("demandes/deleted/", order=19)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def demandes_deleted(request: Request) -> Response:
    """Return soft-deleted demandes."""
    from .response_schemas import DemandeResponseSerializer

    limit = parse_int(request.query_params.get("limit"))
    offset = parse_int(request.query_params.get("offset"), default=0) or 0
    items = demandes.fetch_deleted_demandes(limit=limit, offset=offset)
    total = demandes.get_total_deleted_demande_count()

    data = DemandeResponseSerializer(items, many=True).data
    return Response({"items": data, "total": total})


@route("demandes/<int:demande_id>/", order=20)
@api_view(["GET", "PUT", "DELETE"])
@permission_classes([IsAuthenticated])
def demande_detail(request: Request, demande_id: int) -> Response:
    """Get, update, or delete a demande."""
    if request.method == "GET":
        from .response_schemas import DemandeResponseSerializer

        include_deleted = parse_bool(request.query_params.get("include_deleted"), False)
        demande = demandes.get_demande_by_id(demande_id, include_deleted=include_deleted)
        if not demande:
            return error("Demande not found", status.HTTP_404_NOT_FOUND)

        data = DemandeResponseSerializer(demande).data
        return Response(data)

    from .idempotency import check_idempotency, store_idempotency

    if request.method == "PUT":
        idem_ctx, idem_response = check_idempotency(request)
        if idem_response:
            return idem_response

        try:
            payload, error_response = validate_payload(
                request.data if isinstance(request.data, dict) else {},
                DemandePayloadSerializer,
                partial=True,
                require_row_version=True,
            )
            if error_response:
                return error_response

            demande_input = cast(DemandeInput, payload or {})
            demandes.update_demande(
                demande_id,
                demande_input,
                actor=actor(request),
            )
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

    demandes.delete_demande(demande_id, actor=actor(request))
    response = Response(status=status.HTTP_204_NO_CONTENT)
    return store_idempotency(idem_ctx, response, request)


@route("demandes/<int:demande_id>/restore/", order=21)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def demande_restore(request: Request, demande_id: int) -> Response:
    """Restore a deleted demande."""
    from .idempotency import check_idempotency, store_idempotency

    idem_ctx, idem_response = check_idempotency(request)
    if idem_response:
        return idem_response

    demandes.restore_demande(demande_id, actor=actor(request))
    response = Response(status=status.HTTP_204_NO_CONTENT)
    return store_idempotency(idem_ctx, response, request)


@route("demandes/<int:demande_id>/purge/", order=22)
@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def demande_purge(request: Request, demande_id: int) -> Response:
    """Purge a demande."""
    from .idempotency import check_idempotency, store_idempotency

    idem_ctx, idem_response = check_idempotency(request)
    if idem_response:
        return idem_response

    deny = require_hard_delete(request)
    if deny:
        return deny

    confirm = require_confirmation(request, f"PURGE_DEMANDE_{demande_id}")
    if confirm:
        return confirm
    demandes.purge_demande(demande_id, actor=actor(request))
    response = Response(status=status.HTTP_204_NO_CONTENT)
    return store_idempotency(idem_ctx, response, request)
