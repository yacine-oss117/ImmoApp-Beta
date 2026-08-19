"""
Secrets backend status API.
"""

from __future__ import annotations

from rest_framework.request import Request
from rest_framework.response import Response

from server.api.api_view import api_view
from server.api.rbac import require_superuser
from server.api.route_registry import route
from server.secret_store.loader import get_secrets_status


@route("secrets/status/", order=125)
@api_view(["GET"])
def secrets_status(request: Request) -> Response:
    """Return non-sensitive secrets backend status (superuser only)."""
    deny = require_superuser(request)
    if deny:
        return deny
    return Response(get_secrets_status())
