"""
Location management API views.
"""

from __future__ import annotations

from rest_framework.decorators import permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from server.api.api_view import api_view
from server.api.route_registry import route
from server.services import locations

from .idempotency import check_idempotency, store_idempotency
from .request_schemas import (
    LocationCreateSerializer,
    LocationDeleteSerializer,
    LocationRenameSerializer,
)
from .validation import validate_payload


@route("locations/", order=73)
@api_view(["GET", "POST", "PUT", "DELETE"])
@permission_classes([IsAuthenticated])
def locations_endpoint(request: Request) -> Response:
    """List or modify custom locations."""
    if request.method == "GET":
        items = locations.get_all_locations()
        return Response({"items": items, "total": len(items)})
    if request.method == "POST":
        idem_ctx, idem_response = check_idempotency(request)
        if idem_response is not None:
            return idem_response
        payload, error_response = validate_payload(
            request.data if isinstance(request.data, dict) else {},
            LocationCreateSerializer,
            partial=False,
        )
        if error_response:
            return error_response
        name = str((payload or {}).get("name") or "").strip()
        response = Response({"created": locations.add_location(name)})
        return store_idempotency(idem_ctx, response, request)
    if request.method == "PUT":
        idem_ctx, idem_response = check_idempotency(request)
        if idem_response is not None:
            return idem_response
        payload, error_response = validate_payload(
            request.data if isinstance(request.data, dict) else {},
            LocationRenameSerializer,
            partial=False,
        )
        if error_response:
            return error_response
        payload = payload or {}
        old_name = str(payload.get("old_name") or "").strip()
        new_name = str(payload.get("new_name") or "").strip()
        response = Response({"updated": locations.update_location(old_name, new_name)})
        return store_idempotency(idem_ctx, response, request)
    idem_ctx, idem_response = check_idempotency(request)
    if idem_response is not None:
        return idem_response
    payload, error_response = validate_payload(
        request.data if isinstance(request.data, dict) else {},
        LocationDeleteSerializer,
        partial=False,
    )
    if error_response:
        return error_response
    name = str((payload or {}).get("name") or "").strip()
    response = Response({"deleted": locations.delete_location(name)})
    return store_idempotency(idem_ctx, response, request)
