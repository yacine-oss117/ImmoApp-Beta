"""CRM contract API views."""

from __future__ import annotations

from typing import cast

from rest_framework import status
from rest_framework.decorators import permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from server.api.api_view import api_view
from server.api.route_registry import route
from server.services import crm
from server.services.errors import ConflictError, NotFoundError
from server.services.types import ContractInput

from .rbac import require_hard_delete
from .request_schemas import ContractCancelSerializer, ContractPayloadSerializer
from .response_schemas import ContractResponseSerializer
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


@route("crm/contracts/", order=90)
@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def crm_contracts(request: Request) -> Response:
    """List or create contracts."""
    if request.method == "POST":
        from .idempotency import check_idempotency, store_idempotency

        idem_ctx, idem_response = check_idempotency(request)
        if idem_response:
            return idem_response

        try:
            payload, error_response = validate_payload(
                request.data if isinstance(request.data, dict) else {},
                ContractPayloadSerializer,
                partial=False,
            )
            if error_response:
                return error_response
            contract_input = cast(ContractInput, payload or {})
            contract_id = crm.create_contract(contract_input, actor=actor(request))
        except ValueError as exc:
            return error(safe_error_message(exc), status.HTTP_400_BAD_REQUEST)

        created = crm.get_contract_by_id(int(contract_id))
        response_payload: dict[str, object] = {"id": contract_id}
        if created is not None:
            response_payload["item"] = ContractResponseSerializer(created).data
        response = Response(response_payload, status=status.HTTP_201_CREATED)
        return store_idempotency(idem_ctx, response, request)

    status_param = request.query_params.get("status")
    contract_type = request.query_params.get("contract_type")
    limit = parse_int(request.query_params.get("limit"), default=100) or 100
    offset = parse_int(request.query_params.get("offset"), default=0) or 0
    items = crm.fetch_contracts(
        status=status_param,
        contract_type=contract_type,
        limit=limit,
        offset=offset,
    )
    total = crm.get_total_contract_count(
        status=status_param,
        contract_type=contract_type,
    )
    data = ContractResponseSerializer(items, many=True).data
    return Response({"items": data, "total": total})


@route("crm/contracts/deleted/", order=92)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def crm_contracts_deleted(request: Request) -> Response:
    """Return soft-deleted contracts."""
    limit = parse_int(request.query_params.get("limit"), default=100) or 100
    offset = parse_int(request.query_params.get("offset"), default=0) or 0
    items = crm.fetch_deleted_contracts(limit=limit, offset=offset)
    total = crm.get_total_deleted_contract_count()
    data = ContractResponseSerializer(items, many=True).data
    return Response({"items": data, "total": total})


@route("crm/contracts/<int:contract_id>/", order=93)
@api_view(["GET", "PUT", "DELETE"])
@permission_classes([IsAuthenticated])
def crm_contract_detail(request: Request, contract_id: int) -> Response:
    """Get, update, or delete a contract."""
    if request.method == "GET":
        contract = crm.get_contract_by_id(contract_id, include_deleted=True)
        if not contract:
            return error("Contract not found", status.HTTP_404_NOT_FOUND)
        data = ContractResponseSerializer(contract).data
        return Response(data)
    from .idempotency import check_idempotency, store_idempotency

    if request.method == "PUT":
        idem_ctx, idem_response = check_idempotency(request)
        if idem_response:
            return idem_response
        try:
            payload, error_response = validate_payload(
                request.data if isinstance(request.data, dict) else {},
                ContractPayloadSerializer,
                partial=True,
                require_row_version=True,
            )
            if error_response:
                return error_response
            contract_input = cast(ContractInput, payload or {})
            crm.update_contract(
                contract_id,
                contract_input,
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

    try:
        crm.delete_contract(contract_id, actor=actor(request))
    except ConflictError as exc:
        return conflict_error(str(exc), field="status")
    except NotFoundError as exc:
        return error(safe_not_found_message(exc), status.HTTP_404_NOT_FOUND)
    response = Response(status=status.HTTP_204_NO_CONTENT)
    return store_idempotency(idem_ctx, response, request)


@route("crm/contracts/<int:contract_id>/restore/", order=94)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def crm_contract_restore(request: Request, contract_id: int) -> Response:
    """Restore a deleted contract."""
    crm.restore_contract(contract_id, actor=actor(request))
    return Response(status=status.HTTP_204_NO_CONTENT)


@route("crm/contracts/<int:contract_id>/purge/", order=95)
@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def crm_contract_purge(request: Request, contract_id: int) -> Response:
    """Purge a contract."""
    from .idempotency import check_idempotency, store_idempotency

    idem_ctx, idem_response = check_idempotency(request)
    if idem_response:
        return idem_response

    deny = require_hard_delete(request)
    if deny:
        return deny

    confirm = require_confirmation(request, f"PURGE_CONTRACT_{contract_id}")
    if confirm:
        return confirm
    crm.purge_contract(contract_id, actor=actor(request))
    response = Response(status=status.HTTP_204_NO_CONTENT)
    return store_idempotency(idem_ctx, response, request)


@route("crm/contracts/<int:contract_id>/print/", order=96)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def crm_contract_print(request: Request, contract_id: int) -> Response:
    """Trigger contract printing."""
    try:
        crm.print_contract(contract_id, actor=actor(request))
    except ConflictError as exc:
        return conflict_error(str(exc), field="status")
    except NotFoundError as exc:
        return error(safe_not_found_message(exc), status.HTTP_404_NOT_FOUND)
    return Response(status=status.HTTP_204_NO_CONTENT)


@route("crm/contracts/<int:contract_id>/activate/", order=97)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def crm_contract_activate(request: Request, contract_id: int) -> Response:
    """Activate a contract."""
    from .idempotency import check_idempotency, store_idempotency

    idem_ctx, idem_response = check_idempotency(request)
    if idem_response:
        return idem_response

    try:
        crm.activate_contract(contract_id, actor=actor(request))
    except ConflictError as exc:
        return conflict_error(str(exc), field="status")
    except NotFoundError as exc:
        return error(safe_not_found_message(exc), status.HTTP_404_NOT_FOUND)
    except ValueError as exc:
        return error(safe_error_message(exc), status.HTTP_400_BAD_REQUEST)
    response = Response(status=status.HTTP_204_NO_CONTENT)
    return store_idempotency(idem_ctx, response, request)


@route("crm/contracts/<int:contract_id>/cancel/", order=98)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def crm_contract_cancel(request: Request, contract_id: int) -> Response:
    """Cancel a contract."""
    from .idempotency import check_idempotency, store_idempotency

    idem_ctx, idem_response = check_idempotency(request)
    if idem_response:
        return idem_response

    payload, error_response = validate_payload(
        request.data if isinstance(request.data, dict) else {},
        ContractCancelSerializer,
        partial=True,
    )
    if error_response:
        return error_response
    restore_status_raw = (payload or {}).get("restore_status")
    if isinstance(restore_status_raw, bool):
        restore_status = restore_status_raw
    else:
        restore_status = parse_bool(
            str(restore_status_raw) if restore_status_raw is not None else None,
            True,
        )
    try:
        crm.cancel_contract(
            contract_id,
            restore_status=restore_status,
            actor=actor(request),
        )
    except ConflictError as exc:
        return conflict_error(str(exc), field="status")
    except NotFoundError as exc:
        return error(safe_not_found_message(exc), status.HTTP_404_NOT_FOUND)
    except ValueError as exc:
        return error(safe_error_message(exc), status.HTTP_400_BAD_REQUEST)
    response = Response(status=status.HTTP_204_NO_CONTENT)
    return store_idempotency(idem_ctx, response, request)


__all__ = [
    "crm_contracts",
    "crm_contracts_deleted",
    "crm_contract_detail",
    "crm_contract_restore",
    "crm_contract_purge",
    "crm_contract_print",
    "crm_contract_activate",
    "crm_contract_cancel",
]
