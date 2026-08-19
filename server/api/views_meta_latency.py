"""Latency rollup visibility endpoint for ops debugging."""

from __future__ import annotations

from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from server.api.route_registry import route
from server.api.secured_view import secured_api_view
from server.services.cursor_pagination import normalize_limit
from server.services.latency_rollups import (
    list_latency_snapshots,
    rollup_window_seconds,
    route_latency_snapshot,
)

from .rbac import require_superuser


@route("meta/latency/", order=161)
@secured_api_view(["GET"], permission_classes=[IsAuthenticated])
def meta_latency(request: Request) -> Response:
    deny = require_superuser(request)
    if deny:
        return deny
    route_name = str(request.query_params.get("route_name") or "").strip() or None
    limit = normalize_limit(request.query_params.get("limit"), default=50, minimum=1, maximum=500)
    if route_name:
        snap = route_latency_snapshot(route_name)
        items = [snap] if snap is not None else []
    else:
        items = list_latency_snapshots(limit=limit)
    return Response(
        {
            "items": items,
            "total": len(items),
            "window_seconds": rollup_window_seconds(),
        }
    )


__all__ = ["meta_latency"]
