"""
Dashboard API views.
"""

from __future__ import annotations

from rest_framework.decorators import permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from server.api.api_view import api_view
from server.api.route_registry import route
from server.services import dashboard


@route("dashboard/", order=66)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def dashboard_snapshot(request: Request) -> Response:
    """Return cached dashboard statistics."""
    return Response(dashboard.fetch_dashboard_stats())
