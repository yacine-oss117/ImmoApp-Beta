"""
Lookup API views for reference tables.
"""

from __future__ import annotations

from rest_framework.decorators import permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from server.api.api_view import api_view
from server.api.route_registry import route
from server.services import lookup

from .view_helpers import error, list_response, with_cache


@route("lookup/property-types/", order=67)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def lookup_property_types(request: Request) -> Response:
    """Return property types."""
    name = request.query_params.get("name")
    if name:
        return Response({"id": lookup.get_property_type_id(name)})
    items = [{"id": type_id, "name": name} for type_id, name in lookup.get_all_property_types()]
    return with_cache(list_response(items))


@route("lookup/property-types/<int:type_id>/", order=68)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def lookup_property_type_detail(request: Request, type_id: int) -> Response:
    """Return a property type by ID."""
    name = lookup.get_property_type_name(type_id)
    if not name:
        return error("Type not found", 404)
    return Response({"id": type_id, "name": name})


@route("lookup/actions/", order=69)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def lookup_actions(request: Request) -> Response:
    """Return action types."""
    name = request.query_params.get("name")
    if name:
        return Response({"id": lookup.get_action_id(name)})
    items = [{"id": action_id, "name": name} for action_id, name in lookup.get_all_actions()]
    return with_cache(list_response(items))


@route("lookup/actions/<int:action_id>/", order=70)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def lookup_action_detail(request: Request, action_id: int) -> Response:
    """Return an action by ID."""
    name = lookup.get_action_name(action_id)
    if not name:
        return error("Action not found", 404)
    return Response({"id": action_id, "name": name})


@route("lookup/wilayas/", order=71)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def lookup_wilayas(request: Request) -> Response:
    """Return wilayas."""
    name = request.query_params.get("name")
    if name:
        return Response({"id": lookup.get_wilaya_id(name)})
    items = [{"id": i, "name": n, "code": c} for i, n, c in lookup.get_all_wilayas()]
    return with_cache(list_response(items))


@route("lookup/wilayas/<int:wilaya_id>/", order=72)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def lookup_wilaya_detail(request: Request, wilaya_id: int) -> Response:
    """Return a wilaya by ID."""
    name = lookup.get_wilaya_name(wilaya_id)
    if not name:
        return error("Wilaya not found", 404)
    return Response({"id": wilaya_id, "name": name})
