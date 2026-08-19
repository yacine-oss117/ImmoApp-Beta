"""
User settings API views.
"""

from __future__ import annotations

from rest_framework import status
from rest_framework.decorators import permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from server.api.api_view import api_view
from server.api.route_registry import route
from server.services import agency_settings

from .request_schemas import UserSettingsSerializer
from .validation import validate_payload
from .view_helpers import actor


@route("settings/user/", order=82)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def user_settings(request: Request) -> Response:
    """Return user timezone/locale settings."""
    user = request.user
    payload = {
        "timezone": str(getattr(user, "timezone", "") or ""),
        "locale": str(getattr(user, "locale", "") or ""),
    }
    payload["agency_timezone"] = agency_settings.get_agency_setting("timezone", "")
    payload["agency_locale"] = agency_settings.get_agency_setting("locale", "")
    return Response(payload)


@route("settings/user/set/", order=83)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def user_settings_set(request: Request) -> Response:
    """Update user timezone/locale settings."""
    payload, error_response = validate_payload(
        request.data if isinstance(request.data, dict) else {},
        UserSettingsSerializer,
        partial=True,
    )
    if error_response:
        return error_response
    payload = payload or {}
    timezone_value = str(payload.get("timezone") or "").strip()
    locale_value = str(payload.get("locale") or "").strip()

    user = request.user
    updated_fields: list[str] = []
    if timezone_value:
        user.timezone = timezone_value
        updated_fields.append("timezone")
    if locale_value:
        user.locale = locale_value
        updated_fields.append("locale")
    if updated_fields:
        user.save(update_fields=updated_fields)

    if timezone_value:
        existing = agency_settings.get_agency_setting("timezone", "")
        if not existing:
            agency_id = getattr(request.user, "agency_id", None)
            if agency_id:
                agency_settings.set_agency_setting(
                    "timezone",
                    timezone_value,
                    agency_id,
                    actor=actor(request),
                )
    if locale_value:
        existing = agency_settings.get_agency_setting("locale", "")
        if not existing:
            agency_id = getattr(request.user, "agency_id", None)
            if agency_id:
                agency_settings.set_agency_setting(
                    "locale",
                    locale_value,
                    agency_id,
                    actor=actor(request),
                )

    return Response(status=status.HTTP_204_NO_CONTENT)
