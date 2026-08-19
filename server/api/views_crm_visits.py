"""CRM visit API views."""

from __future__ import annotations

from rest_framework import status
from rest_framework.decorators import permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from server.api.api_view import api_view
from server.api.route_registry import route
from server.services import crm
from server.services.errors import ConflictError, NotFoundError

from .rbac import require_hard_delete
from .request_schemas import VisitPayloadSerializer, VisitUpdateSerializer
from .response_schemas import VisitResponseSerializer
from .validation import validate_payload
from .view_helpers import (
    actor,
    conflict_error,
    error,
    parse_int,
    require_confirmation,
    safe_error_message,
    safe_not_found_message,
)


@route("crm/visits/", order=104)
@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def crm_visits(request: Request) -> Response:
    """List or create visits."""
    if request.method == "POST":
        from .idempotency import check_idempotency, store_idempotency

        idem_ctx, idem_response = check_idempotency(request)
        if idem_response:
            return idem_response

        payload, error_response = validate_payload(
            request.data if isinstance(request.data, dict) else {},
            VisitPayloadSerializer,
            partial=False,
        )
        if error_response:
            return error_response
        visit_id = crm.create_visit(dict(payload or {}), actor=actor(request))
        created = crm.get_visit_by_id(int(visit_id))
        response_payload: dict[str, object] = {"id": visit_id}
        if created is not None:
            response_payload["item"] = VisitResponseSerializer(created).data
        response = Response(response_payload, status=status.HTTP_201_CREATED)
        return store_idempotency(idem_ctx, response, request)

    limit = parse_int(request.query_params.get("limit"), default=100) or 100
    offset = parse_int(request.query_params.get("offset"), default=0) or 0
    status_param = request.query_params.get("status")
    client_id = parse_int(request.query_params.get("client_id"))
    scheduled_date = request.query_params.get("scheduled_date")
    items = crm.fetch_visits(
        limit=limit,
        offset=offset,
        client_id=client_id,
        status=status_param,
        scheduled_date=scheduled_date,
    )
    total = crm.get_total_visit_count(
        client_id=client_id,
        status=status_param,
        scheduled_date=scheduled_date,
    )
    data = VisitResponseSerializer(items, many=True).data
    return Response({"items": data, "total": total})


@route("crm/visits/deleted/", order=106)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def crm_visits_deleted(request: Request) -> Response:
    """Return soft-deleted visits."""
    limit = parse_int(request.query_params.get("limit"), default=100) or 100
    offset = parse_int(request.query_params.get("offset"), default=0) or 0
    items = crm.fetch_deleted_visits(limit=limit, offset=offset)
    total = crm.get_total_deleted_visit_count()
    data = VisitResponseSerializer(items, many=True).data
    return Response({"items": data, "total": total})


@route("crm/visits/<int:visit_id>/", order=107)
@api_view(["PUT", "DELETE"])
@permission_classes([IsAuthenticated])
def crm_visit_detail(request: Request, visit_id: int) -> Response:
    """Update or delete a visit."""
    from .idempotency import check_idempotency, store_idempotency

    if request.method == "PUT":
        idem_ctx, idem_response = check_idempotency(request)
        if idem_response:
            return idem_response

        payload, error_response = validate_payload(
            request.data if isinstance(request.data, dict) else {},
            VisitUpdateSerializer,
            partial=True,
            require_row_version=True,
        )
        if error_response:
            return error_response
        try:
            crm.update_visit(visit_id, dict(payload or {}), actor=actor(request))
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

    idem_ctx, idem_response = check_idempotency(request)
    if idem_response:
        return idem_response

    crm.delete_visit(visit_id, actor=actor(request))
    response = Response(status=status.HTTP_204_NO_CONTENT)
    return store_idempotency(idem_ctx, response, request)


@route("crm/visits/<int:visit_id>/restore/", order=108)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def crm_visit_restore(request: Request, visit_id: int) -> Response:
    """Restore a deleted visit."""
    from .idempotency import check_idempotency, store_idempotency

    idem_ctx, idem_response = check_idempotency(request)
    if idem_response:
        return idem_response

    crm.restore_visit(visit_id, actor=actor(request))
    response = Response(status=status.HTTP_204_NO_CONTENT)
    return store_idempotency(idem_ctx, response, request)


@route("crm/visits/<int:visit_id>/purge/", order=109)
@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def crm_visit_purge(request: Request, visit_id: int) -> Response:
    """Purge a visit."""
    from .idempotency import check_idempotency, store_idempotency

    idem_ctx, idem_response = check_idempotency(request)
    if idem_response:
        return idem_response

    deny = require_hard_delete(request)
    if deny:
        return deny

    confirm = require_confirmation(request, f"PURGE_VISIT_{visit_id}")
    if confirm:
        return confirm
    crm.purge_visit(visit_id, actor=actor(request))
    response = Response(status=status.HTTP_204_NO_CONTENT)
    return store_idempotency(idem_ctx, response, request)


__all__ = [
    "crm_visits",
    "crm_visits_deleted",
    "crm_visit_detail",
    "crm_visit_restore",
    "crm_visit_purge",
]
