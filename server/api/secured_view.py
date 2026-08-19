"""Canonical secured API view decorator."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterable
from contextlib import nullcontext
from typing import cast

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework.decorators import api_view as drf_api_view
from rest_framework.request import Request
from rest_framework.response import Response

from server.api.route_registry import get_route_policy, resolve_route_template
from server.api.view_helpers import request_correlation_id
from server.pg.uow import use_actor_context, use_security_context

ViewFunc = Callable[..., object]
logger = logging.getLogger(__name__)


def _route_template_for_request(request: Request) -> str:
    resolver = getattr(request, "resolver_match", None)
    route = str(getattr(resolver, "route", "") or "")
    path = str(getattr(request, "path", "") or "")
    return resolve_route_template(route, request_path=path)


def _policy_id_for_request(request: Request) -> str | None:
    template = _route_template_for_request(request)
    policy = get_route_policy(template)
    if policy is None:
        return None
    return policy.policy_id


def secured_api_view(
    methods: list[str] | tuple[str, ...],
    *,
    permission_classes: Iterable[type] | None = None,
    throttle_classes: Iterable[type] | None = None,
) -> Callable[[ViewFunc], ViewFunc]:
    """Wrap DRF api_view with an explicit security marker.

    This removes decorator ordering brittleness by always setting
    `_is_explicitly_secured = True` on the resulting view.
    """

    decorator = drf_api_view(methods)

    def _with_db_security_context(func: ViewFunc) -> ViewFunc:
        def _wrapped(*args: object, **kwargs: object) -> object:
            request = args[0] if args else None
            if not isinstance(request, Request):
                return func(*args, **kwargs)
            started_at = time.monotonic()
            template = _route_template_for_request(request)
            policy = get_route_policy(template) if template else None

            user = getattr(request, "user", None)
            is_authenticated = bool(user and getattr(user, "is_authenticated", False))
            agency_id: int | None = None
            is_superuser = False
            actor_id: int | None = None
            actor_email: str | None = None
            actor_role: str | None = None
            actor_is_owner = False
            status_code = 500
            outcome = "error"

            if is_authenticated:
                agency_id = getattr(user, "agency_id", None)
                if agency_id is None:
                    agency = getattr(user, "agency", None)
                    if agency is not None:
                        agency_id = int(agency.id)
                is_superuser = bool(getattr(user, "is_superuser", False))
                actor_id = getattr(user, "id", None)
                actor_email = getattr(user, "email", None)
                actor_role = getattr(user, "role", None)
                actor_is_owner = bool(getattr(user, "is_owner", False))

            security_ctx = use_security_context(
                agency_id=agency_id,
                is_superuser=is_superuser,
            )
            actor_ctx = use_actor_context(
                actor_id=actor_id,
                actor_email=actor_email,
                actor_role=str(actor_role) if actor_role else None,
                actor_is_owner=actor_is_owner,
            )
            try:
                with security_ctx if is_authenticated else nullcontext():
                    with actor_ctx if is_authenticated else nullcontext():
                        if is_authenticated and isinstance(actor_id, int) and template:
                            try:
                                from server.services import e2e_control

                                injected_fault = e2e_control.consume_route_fault(
                                    user_id=int(actor_id),
                                    route_template=template,
                                )
                            except Exception:
                                injected_fault = None
                                logger.warning(
                                    "Failed to evaluate desktop E2E route fault injection",
                                    exc_info=True,
                                )
                            if injected_fault is not None:
                                result = Response(
                                    injected_fault.payload(),
                                    status=injected_fault.status_code,
                                )
                                status_code = int(getattr(result, "status_code", 500) or 500)
                                outcome = "ok" if status_code < 500 else "error"
                                policy_id = _policy_id_for_request(request)
                                if policy_id and hasattr(result, "__setitem__"):
                                    result["X-Request-Policy"] = policy_id
                                return result
                        result = func(*args, **kwargs)
                        status_code = int(getattr(result, "status_code", 200) or 200)
                        outcome = "ok" if status_code < 500 else "error"
                        policy_id = _policy_id_for_request(request)
                        if policy_id and hasattr(result, "__setitem__"):
                            result["X-Request-Policy"] = policy_id
                        return result
            finally:
                duration_s = max(0.0, time.monotonic() - started_at)
                try:
                    from server.immoapp_server.business_metrics_runtime import (
                        record_http_request_latency,
                    )

                    route_name = policy.policy_id if policy is not None else (template or "unknown")
                    record_http_request_latency(
                        route_name=route_name,
                        status_code=status_code,
                        duration_s=duration_s,
                        outcome=outcome,
                    )
                    from server.services import latency_rollups

                    latency_rollups.record_latency_sample(
                        route_name=route_name,
                        duration_ms=duration_s * 1000.0,
                    )
                    if (
                        policy is not None
                        and policy.alert_budget.p95_ms > 0
                        and duration_s * 1000.0 > float(policy.alert_budget.p95_ms)
                    ):
                        from server.services import auth_security_alerts

                        auth_security_alerts.emit_security_alert(
                            reason_code="route_latency_budget_exceeded",
                            agency_id=agency_id,
                            user_id=int(actor_id) if isinstance(actor_id, int) else None,
                            identifier=actor_email
                            or (str(actor_id) if isinstance(actor_id, int) else None),
                            source_ip=request.META.get("REMOTE_ADDR"),
                            user_agent=request.META.get("HTTP_USER_AGENT"),
                            request_id=request_correlation_id(request),
                            details={
                                "policy_id": policy.policy_id,
                                "duration_ms": int(round(duration_s * 1000.0)),
                                "alert_p95_ms": int(policy.alert_budget.p95_ms),
                                "path": str(getattr(request, "path", "") or ""),
                            },
                            cooldown_identity=(f"{policy.policy_id}:{agency_id or 'none'}"),
                        )
                except Exception:
                    logger.warning("Failed to record request latency telemetry", exc_info=True)

        # Preserve DRF view policy attributes set by decorators such as
        # @permission_classes/@throttle_classes.
        for attr in (
            "permission_classes",
            "throttle_classes",
            "authentication_classes",
            "parser_classes",
            "renderer_classes",
            "schema",
        ):
            if hasattr(func, attr):
                setattr(_wrapped, attr, getattr(func, attr))

        return cast(ViewFunc, _wrapped)

    def _apply(func: ViewFunc) -> ViewFunc:
        wrapped = _with_db_security_context(func)
        if permission_classes is not None:
            wrapped.permission_classes = list(permission_classes)  # type: ignore[attr-defined]
        if throttle_classes is not None:
            wrapped.throttle_classes = list(throttle_classes)  # type: ignore[attr-defined]

        view = decorator(wrapped)
        view._is_explicitly_secured = True

        if getattr(view, "schema", None) is None:
            view = extend_schema(responses=OpenApiTypes.OBJECT)(view)
        return cast(ViewFunc, view)

    return _apply


__all__ = ["secured_api_view"]
