"""
Simulation API views.
"""

from __future__ import annotations

from typing import Any, cast

from rest_framework import status
from rest_framework.decorators import permission_classes, throttle_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from server.api.api_view import api_view
from server.api.route_registry import route
from server.api.throttling import HeaderScopedRateThrottle as ScopedRateThrottle
from server.services import simulation

from .rbac import require_superuser
from .request_schemas import SimulationStartSerializer
from .validation import validate_payload
from .view_helpers import error


@route("simulation/start/", order=3)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
@throttle_classes([ScopedRateThrottle])
def simulation_start(request: Request) -> Response:
    """Start simulation or seed fake data for superusers."""
    deny = require_superuser(request)
    if deny:
        return deny
    payload, error_response = validate_payload(
        request.data if isinstance(request.data, dict) else {},
        SimulationStartSerializer,
        partial=True,
    )
    if error_response:
        return error_response
    payload = payload or {}
    mode = str(payload.get("mode") or "").strip().lower()
    seed_fake = bool(payload.get("seed_fake") or False)
    if mode in {"", "seed", "fake"} or seed_fake:
        kwargs: dict[str, int] = {}
        client_count = payload.get("client_count")
        listing_count = payload.get("listing_count")
        demandes_per_client = payload.get("demandes_per_client")
        offers_per_listing = payload.get("offers_per_listing")
        if isinstance(client_count, int):
            kwargs["client_count"] = client_count
        if isinstance(listing_count, int):
            kwargs["listing_count"] = listing_count
        if isinstance(demandes_per_client, int):
            kwargs["demandes_per_client"] = demandes_per_client
        if isinstance(offers_per_listing, int):
            kwargs["offers_per_listing"] = offers_per_listing
        counts = simulation.seed_fake_data(**kwargs)
        return Response({"mode": "seed", "counts": counts})
    if mode in {"clone", "copy"}:
        counts = simulation.clone_public_to_sim()
        return Response({"mode": "clone", "counts": counts})
    return error("Invalid simulation mode", status.HTTP_400_BAD_REQUEST)


@route("simulation/delete/", order=4)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
@throttle_classes([ScopedRateThrottle])
def simulation_delete(request: Request) -> Response:
    """Drop the simulation schema (superusers only)."""
    deny = require_superuser(request)
    if deny:
        return deny
    simulation.drop_sim_schema()
    return Response(status=status.HTTP_204_NO_CONTENT)


@route("simulation/save/", order=6)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
@throttle_classes([ScopedRateThrottle])
def simulation_save(request: Request) -> Response:
    """Save simulation data into public schema (superusers only)."""
    deny = require_superuser(request)
    if deny:
        return deny
    counts = simulation.save_sim_to_public()
    return Response({"counts": counts})


@route("simulation/status/", order=5)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def simulation_status(request: Request) -> Response:
    """Return the simulation schema status (superusers only)."""
    deny = require_superuser(request)
    if deny:
        return deny
    return Response(simulation.simulation_status())


cast(Any, simulation_start).throttle_scope = "simulation"
cast(Any, simulation_delete).throttle_scope = "simulation"
cast(Any, simulation_save).throttle_scope = "simulation"
