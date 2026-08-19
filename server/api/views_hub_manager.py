"""Hub Manager owner-state and protected-action authorization endpoints."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, TypeVar, cast

from rest_framework import status
from rest_framework.decorators import authentication_classes, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from server.api.api_view import api_view
from server.api.request_schemas_hub_manager import (
    HubManagerAuthorizationConsumeSerializer,
    HubManagerAuthorizationIssueSerializer,
)
from server.api.route_registry import route
from server.api.throttling import HeaderScopedRateThrottle as ScopedRateThrottle
from server.api.validation import validate_payload
from server.services import hub_manager_access

ViewFunc = TypeVar("ViewFunc", bound=Callable[..., object])
logger = logging.getLogger(__name__)


def _scoped_throttle(scope: str) -> Callable[[ViewFunc], ViewFunc]:
    def _decorator(view: ViewFunc) -> ViewFunc:
        cast(Any, view).throttle_scope = scope
        return view

    return _decorator


@route("hub-manager/owner-state/", order=4)
@api_view(["GET"])
@authentication_classes([])
@permission_classes([AllowAny])
@throttle_classes([ScopedRateThrottle])
@_scoped_throttle("hub_manager_owner_state")
def hub_manager_owner_state(_request: Request) -> Response:
    try:
        payload = hub_manager_access.resolve_owner_state()
    except Exception:
        logger.exception("Hub Manager owner state lookup failed")
        return Response(
            {
                "kind": "immoapp_hub_manager_owner_state",
                "schema_version": 1,
                "state": "owner_account_missing",
                "setup_available": False,
                "activation_available": False,
                "reason_code": "owner_state_unavailable",
                "source": "hub_db",
            },
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    return Response(payload)


@route("hub-manager/authorizations/", order=5)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
@throttle_classes([ScopedRateThrottle])
@_scoped_throttle("hub_manager_authorization")
def hub_manager_authorization_issue(request: Request) -> Response:
    payload, error_response = validate_payload(
        request.data if isinstance(request.data, dict) else {},
        HubManagerAuthorizationIssueSerializer,
        partial=False,
    )
    if error_response:
        return error_response
    assert payload is not None
    action = str(payload.pop("action"))
    try:
        evidence = hub_manager_access.issue_authorization(
            actor=request.user,
            action=action,
            hub_binding={key: str(value) for key, value in payload.items()},
        )
    except hub_manager_access.HubManagerAccessError as exc:
        response_status = (
            status.HTTP_503_SERVICE_UNAVAILABLE
            if exc.reason_code.endswith("unavailable")
            else status.HTTP_403_FORBIDDEN
        )
        return Response({"reason_code": exc.reason_code}, status=response_status)
    return Response(evidence, status=status.HTTP_201_CREATED)


@route("hub-manager/authorizations/consume/", order=6)
@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
@throttle_classes([ScopedRateThrottle])
@_scoped_throttle("hub_manager_authorization_consume")
def hub_manager_authorization_consume(request: Request) -> Response:
    payload, error_response = validate_payload(
        request.data if isinstance(request.data, dict) else {},
        HubManagerAuthorizationConsumeSerializer,
        partial=False,
    )
    if error_response:
        return error_response
    assert payload is not None
    try:
        evidence = hub_manager_access.consume_authorization(
            nonce=str(payload["evidence_nonce"]),
            action=str(payload["action"]),
            hub_id=str(payload["hub_id"]),
        )
    except hub_manager_access.HubManagerAccessError as exc:
        response_status = (
            status.HTTP_503_SERVICE_UNAVAILABLE
            if exc.reason_code.endswith("unavailable")
            else status.HTTP_403_FORBIDDEN
        )
        return Response({"reason_code": exc.reason_code}, status=response_status)
    return Response(evidence)


__all__ = [
    "hub_manager_authorization_consume",
    "hub_manager_authorization_issue",
    "hub_manager_owner_state",
]
