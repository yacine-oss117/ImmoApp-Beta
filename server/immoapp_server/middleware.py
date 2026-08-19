"""
Request middleware for simulation schema routing.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from ipaddress import ip_address, ip_network

from django.conf import settings
from django.http import HttpRequest, HttpResponse

from server.pg.tenant_context import use_tenant_context
from server.pg.uow import use_schema

_SCHEMA_HEADER = "X-Immoapp-Schema"
_SCHEMA_PARAM = "schema"
_ALLOWED = {"public", "sim"}


def _get_client_ip(request: HttpRequest) -> str:
    if settings.TRUST_PROXY:
        forwarded = str(request.META.get("HTTP_X_FORWARDED_FOR", "") or "")
        parts = [part.strip() for part in forwarded.split(",") if part.strip()]
        if parts:
            proxy_count = max(int(getattr(settings, "DJANGO_NUM_PROXIES", 0)), 0)
            if proxy_count > 0 and len(parts) > proxy_count:
                return parts[-(proxy_count + 1)]
            return parts[0]
    return str(request.META.get("REMOTE_ADDR", "") or "")


def _ip_allowed(ip: str, allowed: Sequence[str]) -> bool:
    if not allowed:
        return True
    try:
        ip_obj = ip_address(ip)
    except ValueError:
        return False
    for entry in allowed:
        if not entry:
            continue
        try:
            if "/" in entry:
                if ip_obj in ip_network(entry, strict=False):
                    return True
            elif ip_obj == ip_address(entry):
                return True
        except ValueError:
            continue
    return False


class AdminAccessMiddleware:
    """Restrict access to Django admin by path and IP allowlist."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self._get_response = get_response
        admin_path = getattr(settings, "DJANGO_ADMIN_PATH", "admin/")
        admin_path = admin_path.lstrip("/")
        self._admin_prefix = f"/{admin_path}"
        self._allowed_ips = list(getattr(settings, "ADMIN_ALLOWED_IPS", []))

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if self._admin_prefix and request.path.startswith(self._admin_prefix):
            if self._allowed_ips:
                client_ip = _get_client_ip(request)
                if not _ip_allowed(client_ip, self._allowed_ips):
                    return HttpResponse(status=403)
        return self._get_response(request)


class SchemaRoutingMiddleware:
    """Set the active Postgres schema based on request headers."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self._get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        header_value = request.headers.get(_SCHEMA_HEADER, "").strip().lower()
        param_value = request.GET.get(_SCHEMA_PARAM, "").strip().lower()
        schema = header_value or param_value or "public"
        if schema not in _ALLOWED:
            schema = "public"
        if schema == "sim":
            user = getattr(request, "user", None)
            is_superuser = bool(
                user and getattr(user, "is_authenticated", False) and user.is_superuser
            )
            if not is_superuser:
                schema = "public"
        with use_schema(schema):
            return self._get_response(request)


class SecurityContextMiddleware:
    """Attach tenant context to every authenticated request."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self._get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        user = getattr(request, "user", None)
        agency_id: int | None = None
        is_superuser = False
        if user and getattr(user, "is_authenticated", False):
            agency_id = getattr(user, "agency_id", None)
            if agency_id is None:
                agency = getattr(user, "agency", None)
                if agency is not None:
                    agency_id = int(agency.id)
            is_superuser = bool(getattr(user, "is_superuser", False))
        actor_id: int | None = None
        actor_email: str | None = None
        actor_role: str | None = None
        actor_is_owner = False
        if user and getattr(user, "is_authenticated", False):
            # Django user typically has id/email; keep it defensive.
            actor_id = getattr(user, "id", None)
            actor_email = getattr(user, "email", None)
            actor_role = getattr(user, "role", None)
            actor_is_owner = bool(getattr(user, "is_owner", False))

        with use_tenant_context(
            agency_id=agency_id,
            actor_id=actor_id,
            actor_email=actor_email,
            actor_role=str(actor_role) if actor_role else None,
            actor_is_owner=actor_is_owner,
            is_superuser=is_superuser,
            source="request_user",
        ):
            return self._get_response(request)


class CspHeaderMiddleware:
    """Attach a Content-Security-Policy header in production."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self._get_response = get_response
        self._enabled = bool(getattr(settings, "CSP_HEADER", "")) and not settings.DEBUG
        self._header = str(getattr(settings, "CSP_HEADER", ""))

    def __call__(self, request: HttpRequest) -> HttpResponse:
        response = self._get_response(request)
        if self._enabled and self._header and "Content-Security-Policy" not in response:
            response["Content-Security-Policy"] = self._header
        return response


class RateLimitHeadersMiddleware:
    """Attach rate limit headers when throttling is enabled."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self._get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        response = self._get_response(request)
        entries = getattr(request, "_rate_limit_headers", None)
        if isinstance(entries, list) and entries:
            # Choose the most restrictive limit (lowest remaining).
            chosen = sorted(entries, key=lambda item: item.get("remaining", 0))[0]
            limit = chosen.get("limit")
            remaining = chosen.get("remaining")
            reset = chosen.get("reset")
            if isinstance(limit, int):
                response["X-RateLimit-Limit"] = str(limit)
            if isinstance(remaining, int):
                response["X-RateLimit-Remaining"] = str(remaining)
            if isinstance(reset, int) and reset > 0:
                response["X-RateLimit-Reset"] = str(reset)
        return response


class DeprecationHeadersMiddleware:
    """Attach Deprecation/Sunset headers when configured."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self._get_response = get_response
        self._policies = list(getattr(settings, "API_DEPRECATION_POLICIES", []))

    def __call__(self, request: HttpRequest) -> HttpResponse:
        response = self._get_response(request)
        if not self._policies:
            return response
        path = request.path or ""
        for policy in self._policies:
            prefix = str(policy.get("path_prefix") or "")
            if not prefix or not path.startswith(prefix):
                continue
            if policy.get("deprecation"):
                response.setdefault("Deprecation", "true")
            sunset = policy.get("sunset")
            if sunset:
                response.setdefault("Sunset", str(sunset))
            successor = policy.get("successor")
            if successor:
                response.setdefault("Link", f'<{successor}>; rel="successor-version"')
            info = policy.get("info")
            if info:
                response.setdefault("Deprecation-Info", str(info))
            break
        return response


class CorrelationIdMiddleware:
    """Extract or generate correlation ID and set it in thread locals."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self._get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        from server.logging_config import set_correlation_id

        correlation_id = request.headers.get("X-Request-ID") or request.headers.get(
            "X-Correlation-ID"
        )
        if not correlation_id:
            import uuid

            correlation_id = str(uuid.uuid4())

        set_correlation_id(correlation_id)

        try:
            response = self._get_response(request)
            response["X-Request-ID"] = correlation_id
            return response
        finally:
            set_correlation_id(None)
