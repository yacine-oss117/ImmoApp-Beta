"""
Middleware to enforce security policies across the API.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from django.http import JsonResponse
from rest_framework import status

if TYPE_CHECKING:
    from django.http import HttpRequest, HttpResponse


# Views that are explicitly allowed to be public
PUBLIC_API_ALLOW_LIST = {
    "health",
    "health_liveness",
    "health_readiness",
    "health_snapshot",
}


class PermissionEnforcementMiddleware:
    """
    Enforces that every API view has an explicit permission_classes attribute.
    This implements 'Default-Deny' by blocking any view that was forgotten
    to be decorated with @permission_classes.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        return self.get_response(request)

    def process_view(
        self,
        request: HttpRequest,
        view_func: Callable[..., object],
        view_args: list[object],
        view_kwargs: dict[str, object],
    ) -> HttpResponse | None:
        # 1. Skip if not an API request
        if not request.path.startswith("/api/v1/"):
            return None

        if request.path.startswith("/api/v1/e2e/"):
            from server.services import e2e_control

            if not e2e_control.e2e_test_mode_enabled():
                return JsonResponse({"detail": "Not found"}, status=status.HTTP_404_NOT_FOUND)

        # 2. Skip if explicitly public
        # DRF wrapper might obscure the original name, but wraps usually preserves it
        func_name = getattr(view_func, "__name__", "")
        if func_name in PUBLIC_API_ALLOW_LIST:
            return None

        # 3. Check for Explicit Security Marker (Structural Immunity)
        # Our custom @api_view attaches _is_explicitly_secured = True
        # if @permission_classes was applied below it.
        is_explicit = getattr(view_func, "_is_explicitly_secured", False)

        if not is_explicit:
            return JsonResponse(
                {
                    "error": "Security Policy Required",
                    "detail": f"The view '{func_name}' lacks an explicit security policy. Application is in 'Default-Deny' mode.",
                    "code": "SECURITY_POLICY_MISSING",
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        return None
