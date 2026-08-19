"""Request-level query budget guards derived from route policy metadata."""

from __future__ import annotations

from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response

from server.api.route_registry import get_route_policy, resolve_route_template


def _max_scan_rows(request: Request) -> int | None:
    resolver = getattr(request, "resolver_match", None)
    route = str(getattr(resolver, "route", "") or "")
    path = str(getattr(request, "path", "") or "")
    template = resolve_route_template(route, request_path=path)
    policy = get_route_policy(template)
    if policy is None:
        return None
    return int(policy.alert_budget.max_scan_rows)


def guard_estimated_scan_rows(
    request: Request,
    *,
    estimated_scan_rows: int,
) -> Response | None:
    budget = _max_scan_rows(request)
    if budget is None:
        return None
    estimated = max(0, int(estimated_scan_rows))
    if estimated <= budget:
        return None
    return Response(
        {
            "code": "QUERY_BUDGET_EXCEEDED",
            "detail": "Query budget exceeded. Reduce requested window.",
            "max_scan_rows": budget,
            "estimated_scan_rows": estimated,
        },
        status=status.HTTP_400_BAD_REQUEST,
    )


__all__ = ["guard_estimated_scan_rows"]
