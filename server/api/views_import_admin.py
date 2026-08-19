"""Superuser control-plane endpoints for importer runtime administration."""

from __future__ import annotations

from rest_framework.request import Request
from rest_framework.response import Response

from core.importer.security import import_security_limits_snapshot, reload_import_security_limits
from server.api.api_view import api_view
from server.api.rbac import require_superuser
from server.api.route_registry import route


@route("import/admin/security-limits/", order=135)
@api_view(["GET"])
def import_security_limits_status(request: Request) -> Response:
    """Return the live cached importer limit policy snapshot (superuser only)."""
    deny = require_superuser(request)
    if deny:
        return deny
    return Response(import_security_limits_snapshot())


@route("import/admin/security-limits/reload/", order=136)
@api_view(["POST"])
def import_security_limits_reload(request: Request) -> Response:
    """Reload process-cached importer limits from the current environment (superuser only)."""
    deny = require_superuser(request)
    if deny:
        return deny
    limits = reload_import_security_limits()
    return Response(
        {
            "reloaded": True,
            **import_security_limits_snapshot(),
            "max_rows": int(limits.max_rows),
        }
    )


__all__ = [
    "import_security_limits_reload",
    "import_security_limits_status",
]
