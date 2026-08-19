"""
Storage API views.
"""

from __future__ import annotations

from rest_framework import status
from rest_framework.decorators import permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from server.api.api_view import api_view
from server.api.idempotency_engine import check_idempotency, store_idempotency
from server.api.request_schemas import (
    StorageCompleteUploadSerializer,
    StorageDeleteSerializer,
    StoragePresignSerializer,
    StoragePresignUploadSerializer,
)
from server.api.route_registry import route
from server.api.validation import validate_payload
from server.api.view_helpers import error, safe_error_message, safe_not_found_message
from server.services import storage

from .rbac import require_manager


def _optional_int(value: object) -> int | None:
    return value if isinstance(value, int) else None


def _storage_error_response(exc: storage.StorageError) -> Response:
    message = str(exc).lower()
    if "not found" in message:
        return error(safe_not_found_message(exc), status.HTTP_404_NOT_FOUND)
    return error(safe_error_message(exc), status.HTTP_400_BAD_REQUEST)


@route("storage/presign/", order=121)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def storage_presign(request: Request) -> Response:
    """Generate a time-limited download URL for a stored object."""
    payload, error_response = validate_payload(
        request.data if isinstance(request.data, dict) else {},
        StoragePresignSerializer,
        partial=False,
    )
    if error_response:
        return error_response
    data = payload or {}
    storage_id = str(data.get("storage_id"))
    expires = data.get("expires_seconds")
    filename = str(data.get("filename") or "") or None
    try:
        expires_seconds = _optional_int(expires)
        url = storage.generate_download_url(
            storage_id,
            expires_seconds=expires_seconds,
            filename=filename,
        )
    except storage.StorageError as exc:
        return _storage_error_response(exc)
    return Response({"url": url, "expires_in": expires or storage.get_presign_default_seconds()})


@route("storage/presign-upload/", order=122)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def storage_presign_upload(request: Request) -> Response:
    """Generate a presigned POST for direct upload to object storage."""
    idem_ctx, idem_response = check_idempotency(request)
    if idem_response is not None:
        return idem_response
    payload, error_response = validate_payload(
        request.data if isinstance(request.data, dict) else {},
        StoragePresignUploadSerializer,
        partial=False,
    )
    if error_response:
        return error_response
    data = payload or {}
    try:
        size_bytes = _optional_int(data.get("size_bytes")) or 0
        expires_seconds = _optional_int(data.get("expires_seconds"))
        result = storage.generate_presigned_upload(
            filename=str(data.get("filename") or ""),
            content_type=str(data.get("content_type") or "") or None,
            purpose=str(data.get("purpose") or ""),
            size_bytes=size_bytes,
            user_id=getattr(request.user, "id", None),
            role=getattr(request.user, "role", None),
            created_ip=request.META.get("REMOTE_ADDR"),
            expires_seconds=expires_seconds,
        )
    except storage.StorageError as exc:
        return _storage_error_response(exc)
    response = Response(result)
    return store_idempotency(idem_ctx, response, request)


@route("storage/complete-upload/", order=123)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def storage_complete_upload(request: Request) -> Response:
    """Finalize a presigned upload by verifying the object and updating metadata."""
    idem_ctx, idem_response = check_idempotency(request)
    if idem_response is not None:
        return idem_response
    payload, error_response = validate_payload(
        request.data if isinstance(request.data, dict) else {},
        StorageCompleteUploadSerializer,
        partial=False,
    )
    if error_response:
        return error_response
    data = payload or {}
    try:
        result = storage.complete_presigned_upload(
            storage_id=str(data.get("storage_id")),
            user_id=getattr(request.user, "id", None),
            role=getattr(request.user, "role", None),
            created_ip=request.META.get("REMOTE_ADDR"),
        )
    except storage.StorageError as exc:
        return _storage_error_response(exc)
    response = Response(result)
    return store_idempotency(idem_ctx, response, request)


@route("storage/delete/", order=124)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def storage_delete(request: Request) -> Response:
    """Soft-delete a storage object and adjust quota counters."""
    idem_ctx, idem_response = check_idempotency(request)
    if idem_response is not None:
        return idem_response
    deny = require_manager(request)
    if deny:
        return deny
    payload, error_response = validate_payload(
        request.data if isinstance(request.data, dict) else {},
        StorageDeleteSerializer,
        partial=False,
    )
    if error_response:
        return error_response
    data = payload or {}
    try:
        deleted_bytes = storage.mark_storage_deleted(
            storage_id=str(data.get("storage_id")),
            user_id=getattr(request.user, "id", None),
            role=getattr(request.user, "role", None),
            created_ip=request.META.get("REMOTE_ADDR"),
        )
    except storage.StorageError as exc:
        return _storage_error_response(exc)
    response = Response({"deleted_bytes": deleted_bytes})
    return store_idempotency(idem_ctx, response, request)


__all__ = [
    "storage_complete_upload",
    "storage_delete",
    "storage_presign",
    "storage_presign_upload",
]
