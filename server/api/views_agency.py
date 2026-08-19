"""
Agency settings API views.
"""

from __future__ import annotations

import base64

from rest_framework import status
from rest_framework.decorators import permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from server.api.api_view import api_view
from server.api.route_registry import route
from server.services import agency_settings, media

from .idempotency import check_idempotency, store_idempotency
from .rbac import require_manager
from .request_schemas import (
    AgencyMediaCompleteSerializer,
    AgencyMediaPresignSerializer,
    AgencySerialSerializer,
    AgencySettingSerializer,
)
from .validation import validate_payload
from .view_helpers import actor, agency_id, error, safe_error_message


def _optional_int(value: object) -> int | None:
    return value if isinstance(value, int) else None


@route("settings/agency/", order=75)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def agency_settings_all(request: Request) -> Response:
    """Return all agency settings."""
    return Response({"settings": agency_settings.get_all_agency_settings()})


@route("settings/agency/set/", order=77)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def agency_settings_set(request: Request) -> Response:
    """Update a single agency setting."""
    idem_ctx, idem_response = check_idempotency(request)
    if idem_response is not None:
        return idem_response
    deny = require_manager(request)
    if deny:
        return deny
    payload, error_response = validate_payload(
        request.data if isinstance(request.data, dict) else {},
        AgencySettingSerializer,
        partial=False,
    )
    if error_response:
        return error_response
    payload = payload or {}
    key = str(payload.get("key") or "")
    value = str(payload.get("value") or "")
    if key in {"agency_logo_path", "agency_signature_path"} and not value:
        kind = "logo" if key == "agency_logo_path" else "signature"
        media.remove_agency_media(
            kind,
            actor=actor(request),
            user_id=getattr(request.user, "id", None),
            role=getattr(request.user, "role", None),
            created_ip=request.META.get("REMOTE_ADDR"),
        )
        response = Response(status=status.HTTP_204_NO_CONTENT)
        return store_idempotency(idem_ctx, response, request)
    agency_settings.set_agency_setting(key, value, actor=actor(request))
    response = Response(status=status.HTTP_204_NO_CONTENT)
    return store_idempotency(idem_ctx, response, request)


@route("settings/agency/serial/", order=78)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def agency_settings_serial(request: Request) -> Response:
    """Generate a contract serial number for the agency."""
    idem_ctx, idem_response = check_idempotency(request)
    if idem_response is not None:
        return idem_response
    payload, error_response = validate_payload(
        request.data if isinstance(request.data, dict) else {},
        AgencySerialSerializer,
        partial=True,
    )
    if error_response:
        return error_response
    payload = payload or {}
    prefix = str(payload.get("prefix") or "C21")
    aid = agency_id(request)
    if aid is None:
        return error("agency_id is required", status.HTTP_403_FORBIDDEN)
    serial = agency_settings.generate_contract_serial(
        prefix,
        agency_id=aid,
    )
    response = Response({"serial": serial})
    return store_idempotency(idem_ctx, response, request)


@route("settings/agency/media/", order=79)
@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def agency_media(request: Request) -> Response:
    """Upload or download agency media assets."""
    if request.method == "GET":
        kind = request.query_params.get("kind")
        if not kind:
            return error("kind is required", status.HTTP_400_BAD_REQUEST)
        mode = str(request.query_params.get("mode") or "").lower()
        if mode != "inline":
            expires_raw = request.query_params.get("expires_seconds")
            expires_seconds: int | None = None
            if expires_raw:
                try:
                    expires_seconds = int(expires_raw)
                except ValueError:
                    return error("expires_seconds must be an integer", status.HTTP_400_BAD_REQUEST)
            media_url_payload = media.get_agency_media_url(kind, expires_seconds=expires_seconds)
            if not media_url_payload:
                return error("media not found", status.HTTP_404_NOT_FOUND)
            return Response(media_url_payload)

        media_blob = media.load_agency_media(kind)
        if not media_blob:
            url_payload = media.get_agency_media_url(kind)
            if url_payload:
                url_payload["inline"] = False
                return Response(url_payload)
            return error("media not found", status.HTTP_404_NOT_FOUND)
        filename, content = media_blob
        encoded = base64.b64encode(content).decode("ascii")
        return Response({"filename": filename, "content_b64": encoded})

    return error(
        "Use /settings/agency/media/presign or /settings/agency/media/complete",
        status.HTTP_405_METHOD_NOT_ALLOWED,
    )


@route("settings/agency/media/presign/", order=80)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def agency_media_presign(request: Request) -> Response:
    """Generate a presigned upload for agency media."""
    idem_ctx, idem_response = check_idempotency(request)
    if idem_response is not None:
        return idem_response
    deny = require_manager(request)
    if deny:
        return deny
    payload, error_response = validate_payload(
        request.data if isinstance(request.data, dict) else {},
        AgencyMediaPresignSerializer,
        partial=False,
    )
    if error_response:
        return error_response
    payload = payload or {}
    size_bytes = _optional_int(payload.get("size_bytes")) or 0
    expires_seconds = _optional_int(payload.get("expires_seconds"))
    try:
        result = media.prepare_agency_media_upload(
            str(payload.get("kind") or ""),
            str(payload.get("filename") or ""),
            str(payload.get("content_type") or "") or None,
            size_bytes,
            user_id=getattr(request.user, "id", None),
            role=getattr(request.user, "role", None),
            created_ip=request.META.get("REMOTE_ADDR"),
            expires_seconds=expires_seconds,
        )
    except ValueError as exc:
        return error(safe_error_message(exc), status.HTTP_400_BAD_REQUEST)
    except Exception as exc:
        return error(safe_error_message(exc), status.HTTP_400_BAD_REQUEST)
    response = Response(result)
    return store_idempotency(idem_ctx, response, request)


@route("settings/agency/media/complete/", order=81)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def agency_media_complete(request: Request) -> Response:
    """Finalize a presigned upload for agency media."""
    idem_ctx, idem_response = check_idempotency(request)
    if idem_response is not None:
        return idem_response
    deny = require_manager(request)
    if deny:
        return deny
    payload, error_response = validate_payload(
        request.data if isinstance(request.data, dict) else {},
        AgencyMediaCompleteSerializer,
        partial=False,
    )
    if error_response:
        return error_response
    payload = payload or {}
    try:
        storage_id = media.finalize_agency_media_upload(
            str(payload.get("kind") or ""),
            str(payload.get("storage_id") or ""),
            actor=actor(request),
            user_id=getattr(request.user, "id", None),
            role=getattr(request.user, "role", None),
            created_ip=request.META.get("REMOTE_ADDR"),
        )
    except ValueError as exc:
        return error(safe_error_message(exc), status.HTTP_400_BAD_REQUEST)
    except Exception as exc:
        return error(safe_error_message(exc), status.HTTP_400_BAD_REQUEST)
    response = Response({"storage_id": storage_id})
    return store_idempotency(idem_ctx, response, request)
