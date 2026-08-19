"""
Health check API views.
"""

from __future__ import annotations

import os

from rest_framework import status
from rest_framework.decorators import api_view as drf_api_view
from rest_framework.decorators import permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from server.api.api_view import api_view
from server.api.route_registry import route
from server.services import health as health_service


@route("health/", order=0)
@api_view(["GET"])
@permission_classes([AllowAny])
def health(_request: Request) -> Response:
    """Backward-compatible health endpoint (same as liveness)."""
    return Response(health_service.liveness())


@route("health/live/", order=1)
@api_view(["GET"])
@permission_classes([AllowAny])
def health_liveness(_request: Request) -> Response:
    """Liveness probe: process is running."""
    return Response(health_service.liveness())


@route("health/ready/", order=2)
@api_view(["GET"])
@permission_classes([AllowAny])
def health_readiness(_request: Request) -> Response:
    """Readiness probe: dependencies are reachable."""
    payload = health_service.readiness()
    code = status.HTTP_200_OK if payload.get("ready") else status.HTTP_503_SERVICE_UNAVAILABLE
    return Response(payload, status=code)


@route("hub/front-door/identity/", order=3)
@api_view(["GET"])
@permission_classes([AllowAny])
def hub_front_door_identity(_request: Request) -> Response:
    """Return non-secret identity data used by desktop clients to validate Hub front-door access."""
    return Response(
        {
            "kind": "immoapp_hub_front_door_identity",
            "schema_version": 1,
            "service": "immoapp-api",
            "protocol": "http",
            "front_door_required": True,
            "front_door_marker_header": "X-ImmoApp-Front-Door",
            "health_path": "/api/v1/health/",
            "api_version": os.environ.get("IMMOAPP_API_VERSION", "v1"),
            "build_identity": {
                "git_sha": os.environ.get("IMMOAPP_BUILD_GIT_SHA", ""),
                "version": os.environ.get("IMMOAPP_SERVER_VERSION", ""),
            },
        }
    )


@route("health/snapshot/", order=7)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def health_snapshot(request: Request) -> Response:
    """Return a detailed health snapshot."""
    include_tenant_usage = bool(getattr(request.user, "is_superuser", False))
    return Response(health_service.health_snapshot(include_tenant_usage=include_tenant_usage))


@route("firewall-verification/", order=8)
@drf_api_view(["GET"])
def firewall_verification(_request: Request) -> Response:
    """
    A view with no security decorator.
    Used by CI to verify the PermissionEnforcementMiddleware is active.
    """
    return Response({"status": "firewall_inactive"})
