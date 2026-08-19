"""Self-registration and onboarding endpoints."""

from __future__ import annotations

import logging
from collections.abc import Callable
from html import escape as esc
from typing import Any, TypeVar, cast

from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from rest_framework import status
from rest_framework.decorators import authentication_classes, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response

from server.api.api_view import api_view
from server.api.route_registry import route
from server.api.throttling import HeaderScopedRateThrottle as ScopedRateThrottle
from server.services import registration_lifecycle
from server.services.errors import NotFoundError, PermissionDeniedError

from .request_schemas_registration import (
    AcceptInviteSerializer,
    ActivationSerializer,
    RegistrationRequestSerializer,
)
from .validation import validate_payload
from .view_helpers import (
    error,
    request_correlation_id,
    safe_error_message,
    safe_forbidden_message,
    safe_not_found_message,
)

ViewFunc = TypeVar("ViewFunc", bound=Callable[..., object])
logger = logging.getLogger(__name__)


def _client_ip(request: Request) -> str | None:
    forwarded = str(request.META.get("HTTP_X_FORWARDED_FOR", "") or "")
    if forwarded:
        parts = [part.strip() for part in forwarded.split(",") if part.strip()]
        if parts:
            return parts[0]
    remote = str(request.META.get("REMOTE_ADDR", "") or "").strip()
    return remote or None


def _user_agent(request: Request) -> str | None:
    value = str(request.META.get("HTTP_USER_AGENT", "") or "").strip()
    return value[:512] or None


def _register_throttle(view: ViewFunc) -> ViewFunc:
    cast(Any, view).throttle_scope = "register"
    return view


def _activate_throttle(view: ViewFunc) -> ViewFunc:
    cast(Any, view).throttle_scope = "activate"
    return view


def _accept_invite_throttle(view: ViewFunc) -> ViewFunc:
    cast(Any, view).throttle_scope = "accept_invite"
    return view


def _shared_page_css(*, action_color: str) -> str:
    return (
        "<style>"
        "body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;"
        "max-width:680px;margin:32px auto;padding:16px;background:#f8fafc;color:#0f172a;}"
        ".card{background:#fff;border:1px solid #e2e8f0;border-radius:12px;padding:24px;"
        "box-shadow:0 1px 2px rgba(15,23,42,.08);}"
        "h2{margin:0 0 16px;font-size:22px;line-height:1.3;}"
        ".field{margin:8px 0;line-height:1.5;}"
        ".label{font-weight:600;color:#334155;}"
        ".muted{color:#64748b;font-size:14px;}"
        ".btn{margin-top:16px;padding:12px 24px;border:none;border-radius:8px;"
        f"background:{action_color};color:#fff;font-size:16px;font-weight:600;cursor:pointer;}}"
        ".btn:hover{opacity:.92;}"
        ".status{font-size:18px;font-weight:700;margin-bottom:8px;}"
        "</style>"
    )


def _build_review_page(details: dict[str, str], *, action: str, signed_token: str) -> str:
    action_label = "Approve" if action == "approve" else "Decline"
    action_color = "#22c55e" if action == "approve" else "#ef4444"
    return (
        "<!DOCTYPE html>"
        "<html><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>ImmoApp - {action_label} Registration</title>"
        f"{_shared_page_css(action_color=action_color)}"
        "</head><body>"
        "<div class='card'>"
        f"<h2>{action_label} Registration Request</h2>"
        f"<div class='field'><span class='label'>Agency:</span> {esc(str(details.get('agency_name', '')))}</div>"
        f"<div class='field'><span class='label'>Legal name:</span> {esc(str(details.get('legal_name', '')))}</div>"
        f"<div class='field'><span class='label'>Registry number:</span> {esc(str(details.get('registry_number', '')))}</div>"
        f"<div class='field'><span class='label'>Address:</span> {esc(str(details.get('address', '')))}</div>"
        f"<div class='field'><span class='label'>City:</span> {esc(str(details.get('city', '')))}</div>"
        f"<div class='field'><span class='label'>Postal code:</span> {esc(str(details.get('postal_code', '')))}</div>"
        "<hr>"
        f"<div class='field'><span class='label'>Owner:</span> {esc(str(details.get('owner_name', '')))}</div>"
        f"<div class='field'><span class='label'>Email:</span> {esc(str(details.get('owner_email', '')))}</div>"
        f"<div class='field'><span class='label'>Phone:</span> {esc(str(details.get('owner_phone', '')))}</div>"
        f"<div class='field'><span class='label'>Submitted:</span> {esc(str(details.get('submitted_at', '')))}</div>"
        "<form method='POST'>"
        f"<input type='hidden' name='signed_token' value='{esc(signed_token)}'>"
        f"<button type='submit' class='btn'>{action_label} this agency</button>"
        "</form>"
        "<p class='muted'>Use this page only if you trust the source of this request.</p>"
        "</div></body></html>"
    )


def _build_result_page(message: str, *, success: bool = True) -> str:
    action_color = "#22c55e" if success else "#ef4444"
    status_label = "Done" if success else "Action Required"
    return (
        "<!DOCTYPE html>"
        "<html><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<title>ImmoApp - Registration Review</title>"
        f"{_shared_page_css(action_color=action_color)}"
        "</head><body>"
        "<div class='card'>"
        f"<div class='status'>{esc(status_label)}</div>"
        f"<div class='field'>{esc(message)}</div>"
        "</div></body></html>"
    )


def _validation_error_response(exc: DjangoValidationError) -> Response:
    if hasattr(exc, "message_dict"):
        errors = dict(getattr(exc, "message_dict", {}) or {})
    else:
        messages = list(getattr(exc, "messages", []) or [])
        errors = {"non_field_errors": messages or ["Invalid request"]}
    return error("Invalid request", status.HTTP_400_BAD_REQUEST, errors=errors)


@route("auth/register/", order=12)
@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([ScopedRateThrottle])
@_register_throttle
def auth_register(request: Request) -> Response:
    payload, error_response = validate_payload(
        request.data if isinstance(request.data, dict) else {},
        RegistrationRequestSerializer,
        partial=False,
    )
    if error_response:
        return error_response
    try:
        result = registration_lifecycle.submit_registration(
            data=payload or {},
            source_ip=_client_ip(request),
            user_agent=_user_agent(request),
            request_id=request_correlation_id(request),
        )
    except registration_lifecycle.RegistrationUnavailableError:
        return Response(
            {
                "code": "REGISTRATION_UNAVAILABLE",
                "detail": "Registration is not available at this time.",
            },
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    except registration_lifecycle.EmailQueueUnavailableError:
        return Response(
            {
                "code": "EMAIL_QUEUE_UNAVAILABLE",
                "detail": "Email delivery queue is temporarily unavailable.",
            },
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    except ValueError as exc:
        return error(safe_error_message(exc), status.HTTP_400_BAD_REQUEST)
    return Response(result, status=status.HTTP_200_OK)


@route("auth/register/approve/<str:signed_token>/", order=13)
@csrf_exempt
@api_view(["GET", "POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def auth_register_approve(request: Request, signed_token: str) -> Response:
    """GET shows confirmation page; POST applies approval mutation."""
    try:
        record = registration_lifecycle.load_registration_for_review(signed_token=signed_token)
    except PermissionDeniedError:
        return HttpResponse(
            _build_result_page("Invalid or expired approval link.", success=False),
            status=403,
            content_type="text/html",
        )
    except NotFoundError:
        return HttpResponse(
            _build_result_page("Registration request not found.", success=False),
            status=404,
            content_type="text/html",
        )
    except ValueError:
        return HttpResponse(
            _build_result_page("Registration request is no longer pending.", success=False),
            status=409,
            content_type="text/html",
        )
    if request.method == "GET":
        details = registration_lifecycle.registration_review_details(record)
        return HttpResponse(
            _build_review_page(details, action="approve", signed_token=signed_token),
            content_type="text/html",
        )
    try:
        registration_lifecycle.approve_registration_by_token(signed_token=signed_token)
    except PermissionDeniedError:
        return HttpResponse(
            _build_result_page("Invalid or expired approval link.", success=False),
            status=403,
            content_type="text/html",
        )
    except NotFoundError:
        return HttpResponse(
            _build_result_page("Registration request not found.", success=False),
            status=404,
            content_type="text/html",
        )
    except registration_lifecycle.EmailQueueUnavailableError:
        return HttpResponse(
            _build_result_page(
                "Approval saved, but email queue is unavailable. Try again shortly.", success=False
            ),
            status=503,
            content_type="text/html",
        )
    except ValueError:
        return HttpResponse(
            _build_result_page("Registration request is no longer pending.", success=False),
            status=409,
            content_type="text/html",
        )
    except Exception:
        logger.exception("Registration approval failed unexpectedly")
        return HttpResponse(
            _build_result_page(
                "We could not complete this approval right now. Please try again shortly.",
                success=False,
            ),
            status=500,
            content_type="text/html",
        )
    return HttpResponse(
        _build_result_page(
            "Agency approved. The owner's email is queued for delivery.",
            success=True,
        ),
        status=200,
        content_type="text/html",
    )


@route("auth/register/blacklist/<str:signed_token>/", order=14)
@csrf_exempt
@api_view(["GET", "POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def auth_register_blacklist(request: Request, signed_token: str) -> Response:
    """GET shows confirmation page; POST applies blacklist mutation."""
    try:
        record = registration_lifecycle.load_registration_for_review(signed_token=signed_token)
    except PermissionDeniedError:
        return HttpResponse(
            _build_result_page("Invalid or expired blacklist link.", success=False),
            status=403,
            content_type="text/html",
        )
    except NotFoundError:
        return HttpResponse(
            _build_result_page("Registration request not found.", success=False),
            status=404,
            content_type="text/html",
        )
    except ValueError:
        return HttpResponse(
            _build_result_page("Registration request is no longer pending.", success=False),
            status=409,
            content_type="text/html",
        )
    if request.method == "GET":
        details = registration_lifecycle.registration_review_details(record)
        return HttpResponse(
            _build_review_page(details, action="blacklist", signed_token=signed_token),
            content_type="text/html",
        )
    try:
        registration_lifecycle.blacklist_registration_by_token(signed_token=signed_token)
    except PermissionDeniedError:
        return HttpResponse(
            _build_result_page("Invalid or expired blacklist link.", success=False),
            status=403,
            content_type="text/html",
        )
    except NotFoundError:
        return HttpResponse(
            _build_result_page("Registration request not found.", success=False),
            status=404,
            content_type="text/html",
        )
    except registration_lifecycle.EmailQueueUnavailableError:
        return HttpResponse(
            _build_result_page(
                "Decision saved, but email queue is unavailable. Try again shortly.", success=False
            ),
            status=503,
            content_type="text/html",
        )
    except ValueError:
        return HttpResponse(
            _build_result_page("Registration request is no longer pending.", success=False),
            status=409,
            content_type="text/html",
        )
    except Exception:
        logger.exception("Registration blacklist failed unexpectedly")
        return HttpResponse(
            _build_result_page(
                "We could not complete this decision right now. Please try again shortly.",
                success=False,
            ),
            status=500,
            content_type="text/html",
        )
    return HttpResponse(
        _build_result_page(
            "Registration declined. Notification email is queued for delivery.", success=True
        ),
        status=200,
        content_type="text/html",
    )


@route("auth/activate/", order=15)
@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([ScopedRateThrottle])
@_activate_throttle
def auth_activate(request: Request) -> Response:
    payload, error_response = validate_payload(
        request.data if isinstance(request.data, dict) else {},
        ActivationSerializer,
        partial=False,
    )
    if error_response:
        return error_response
    try:
        result = registration_lifecycle.activate_owner(
            email=str((payload or {}).get("email") or ""),
            activation_code=str((payload or {}).get("activation_code") or ""),
            password=str((payload or {}).get("password") or ""),
            source_ip=_client_ip(request),
            user_agent=_user_agent(request),
            request_id=request_correlation_id(request),
        )
    except PermissionDeniedError as exc:
        return error(safe_forbidden_message(exc), status.HTTP_403_FORBIDDEN)
    except NotFoundError as exc:
        return error(safe_not_found_message(exc), status.HTTP_404_NOT_FOUND)
    except DjangoValidationError as exc:
        return _validation_error_response(exc)
    except ValueError as exc:
        return error(safe_error_message(exc), status.HTTP_400_BAD_REQUEST)
    return Response(result, status=status.HTTP_200_OK)


@route("auth/accept-invite/", order=16)
@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([ScopedRateThrottle])
@_accept_invite_throttle
def auth_accept_invite(request: Request) -> Response:
    payload, error_response = validate_payload(
        request.data if isinstance(request.data, dict) else {},
        AcceptInviteSerializer,
        partial=False,
    )
    if error_response:
        return error_response
    try:
        result = registration_lifecycle.accept_invite(
            invite_code=str((payload or {}).get("invite_code") or ""),
            email=str((payload or {}).get("email") or ""),
            password=str((payload or {}).get("password") or ""),
            source_ip=_client_ip(request),
            user_agent=_user_agent(request),
            request_id=request_correlation_id(request),
        )
    except PermissionDeniedError as exc:
        return error(safe_forbidden_message(exc), status.HTTP_403_FORBIDDEN)
    except DjangoValidationError as exc:
        return _validation_error_response(exc)
    except ValueError as exc:
        return error(safe_error_message(exc), status.HTTP_400_BAD_REQUEST)
    return Response(result, status=status.HTTP_200_OK)


__all__ = [
    "auth_accept_invite",
    "auth_activate",
    "auth_register",
    "auth_register_approve",
    "auth_register_blacklist",
]
