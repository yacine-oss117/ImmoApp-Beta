"""Local-only helper endpoints for native desktop E2E orchestration."""

from __future__ import annotations

from rest_framework import status
from rest_framework.decorators import permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from server.api.api_view import api_view
from server.api.route_registry import get_route_policy, route
from server.services import auth_sessions, e2e_control

from .view_helpers import error


def _disabled_response() -> Response | None:
    if e2e_control.e2e_test_mode_enabled():
        return None
    return error("Not found", status.HTTP_404_NOT_FOUND)


def _request_payload(request: Request) -> dict[str, object]:
    return request.data if isinstance(request.data, dict) else {}


def _current_sid(request: Request) -> str | None:
    token = getattr(request, "auth", None)
    if token is None:
        return None
    sid = token.get("sid") if hasattr(token, "get") else None
    return str(sid).strip() if sid else None


def _payload_int(value: object, *, default: int = 0) -> int:
    if value is None:
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return default


def _payload_float(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


@route("e2e/runtime/identity/", order=1529)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def e2e_runtime_identity(request: Request) -> Response:
    disabled = _disabled_response()
    if disabled is not None:
        return disabled
    _ = request
    return Response(e2e_control.runtime_identity())


@route("e2e/notifications/publish/", order=1530)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def e2e_publish_notification(request: Request) -> Response:
    disabled = _disabled_response()
    if disabled is not None:
        return disabled

    payload = _request_payload(request)
    user_id = _payload_int(payload.get("user_id") or getattr(request.user, "id", None))
    if user_id <= 0:
        return error("user_id required", status.HTTP_400_BAD_REQUEST)

    try:
        agency_id = int(getattr(request.user, "agency_id", 0) or 0)
    except (TypeError, ValueError):
        agency_id = 0
    event_type = str(payload.get("event_type", "") or "desktop.e2e.notification")
    title = str(payload.get("title", "") or "Desktop E2E notification")
    body = str(payload.get("body", "") or "Native desktop E2E notification delivered.")
    raw_data = payload.get("data", {})
    data = raw_data if isinstance(raw_data, dict) else {}
    e2e_control.publish_user_notification(
        agency_id=agency_id if agency_id > 0 else None,
        user_id=user_id,
        event_type=event_type,
        title=title,
        body=body,
        data={str(key): value for key, value in data.items()},
    )
    return Response(
        {
            "ok": True,
            "event_type": event_type,
            "title": title,
            "user_id": user_id,
        }
    )


@route("e2e/auth/revoke-other-sessions/", order=1531)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def e2e_revoke_other_sessions(request: Request) -> Response:
    disabled = _disabled_response()
    if disabled is not None:
        return disabled

    current_sid = _current_sid(request)
    revoked = auth_sessions.revoke_all_sessions(actor=request.user, except_session_id=current_sid)
    return Response({"ok": True, "revoked": int(revoked)})


@route("e2e/auth/revoke-session/", order=1532)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def e2e_revoke_session(request: Request) -> Response:
    disabled = _disabled_response()
    if disabled is not None:
        return disabled

    payload = _request_payload(request)
    session_id = str(payload.get("session_id") or "").strip()
    if not session_id:
        return error("session_id required", status.HTTP_400_BAD_REQUEST)
    try:
        auth_sessions.revoke_session(
            actor=request.user,
            session_id=session_id,
            reason="desktop_e2e_revoke",
        )
    except ValueError:
        return error("session_id is invalid or not revocable", status.HTTP_400_BAD_REQUEST)
    return Response({"ok": True, "session_id": session_id})


@route("e2e/imports/pause-next/", order=1533)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def e2e_pause_next_import(request: Request) -> Response:
    disabled = _disabled_response()
    if disabled is not None:
        return disabled

    payload = _request_payload(request)
    raw_seconds = payload.get("seconds", 8.0)
    seconds = _payload_float(raw_seconds)
    if seconds is None:
        return error("seconds must be a number", status.HTTP_400_BAD_REQUEST)
    normalized_seconds = e2e_control.schedule_next_import_pause(
        user_id=int(request.user.id),
        seconds=seconds,
    )
    return Response({"ok": True, "seconds": normalized_seconds})


@route("e2e/faults/inject/", order=1534)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def e2e_inject_fault(request: Request) -> Response:
    disabled = _disabled_response()
    if disabled is not None:
        return disabled

    payload = _request_payload(request)
    route_template = e2e_control.normalize_route_template(
        str(payload.get("route_template", "") or "")
    )
    if not route_template or get_route_policy(route_template) is None:
        return error(
            "route_template must reference a registered API route", status.HTTP_400_BAD_REQUEST
        )
    status_code = _payload_int(payload.get("status_code", 503), default=0)
    if status_code == 0:
        return error("status_code must be an integer", status.HTTP_400_BAD_REQUEST)
    if status_code < 400 or status_code > 599:
        return error("status_code must be between 400 and 599", status.HTTP_400_BAD_REQUEST)
    detail = str(payload.get("detail", "") or "Injected desktop E2E fault.")
    code = str(payload.get("code", "") or "E2E_FAULT")
    e2e_control.inject_route_fault(
        user_id=int(request.user.id),
        route_template=route_template,
        status_code=status_code,
        detail=detail,
        code=code,
    )
    return Response(
        {
            "ok": True,
            "route_template": route_template,
            "status_code": status_code,
            "code": code,
        }
    )


@route("e2e/entities/inspect/", order=1535)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def e2e_inspect_entity(request: Request) -> Response:
    disabled = _disabled_response()
    if disabled is not None:
        return disabled

    entity_type = str(request.query_params.get("entity_type", "") or "")
    record_id_raw = request.query_params.get("record_id")
    record_id: int | None
    try:
        record_id = int(record_id_raw) if record_id_raw not in (None, "") else None
    except (TypeError, ValueError):
        return error("record_id must be an integer", status.HTTP_400_BAD_REQUEST)
    phone = str(request.query_params.get("phone", "") or "")
    family_name = str(request.query_params.get("family_name", "") or "")
    try:
        payload = e2e_control.inspect_entity_state(
            entity_type=entity_type,
            record_id=record_id,
            phone=phone,
            family_name=family_name,
        )
    except ValueError:
        return error("entity inspection request is invalid", status.HTTP_400_BAD_REQUEST)
    return Response(payload)


__all__ = [
    "e2e_runtime_identity",
    "e2e_inject_fault",
    "e2e_inspect_entity",
    "e2e_pause_next_import",
    "e2e_publish_notification",
    "e2e_revoke_session",
    "e2e_revoke_other_sessions",
]
