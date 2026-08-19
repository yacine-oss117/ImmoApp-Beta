"""Import upload/presign endpoints."""

from __future__ import annotations

import os
from pathlib import Path
from typing import cast

from rest_framework import status
from rest_framework.decorators import parser_classes, permission_classes
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from server.api.api_view import api_view
from server.api.import_helpers import get_parser_for_file
from server.api.request_schemas import ImportCompleteSerializer, ImportPresignSerializer
from server.api.route_registry import route
from server.api.task_registry import register_task
from server.api.tasks import import_parse_task
from server.api.validation import validate_payload
from server.api.view_helpers import (
    error,
    request_correlation_id,
    safe_error_message,
    safe_forbidden_message,
)
from server.imports.models import ImportJob
from server.services.import_admission_service import admit_import_parse
from server.services.import_parsers import normalize_import_entity_type
from server.services.import_service import (
    ImportPermissionError,
    ImportService,
    get_active_schema,
)
from server.services.storage import (
    StorageError,
    complete_presigned_upload,
    generate_presigned_upload,
    store_fileobj,
)
from server.services.storage_config import get_storage_config
from server.services.storage_errors import StorageNotReadyError
from server.services.work_admission import AdmissionMode


def _optional_int(value: object) -> int | None:
    return value if isinstance(value, int) else None


def _import_parse_backpressure_response(*, retry_after: int) -> Response:
    response = Response(
        {
            "code": "IMPORT_PARSE_BACKPRESSURE",
            "detail": "Import parsing capacity is temporarily saturated for this agency.",
            "admission_mode": "rejected",
            "execution_profile_hint": "red",
            "poll_after_ms": _parse_poll_after_ms(),
        },
        status=status.HTTP_429_TOO_MANY_REQUESTS,
    )
    response["Retry-After"] = str(max(1, int(retry_after or 10)))
    return response


def _parse_poll_after_ms() -> int:
    return 150


def _admission_mode_label(value: object, *, degraded: bool = False) -> AdmissionMode:
    mode = str(value or "").strip().lower()
    if mode in {"normal", "degraded", "queued", "rejected"}:
        return cast(AdmissionMode, mode)
    return "degraded" if degraded else "normal"


def _parse_admission_payload(*, admission: object) -> dict[str, object]:
    execution_profile = str(getattr(admission, "execution_profile", "yellow") or "yellow")
    degraded = bool(getattr(admission, "degraded", False))
    return {
        "poll_after_ms": _parse_poll_after_ms(),
        "admission_mode": _admission_mode_label(
            getattr(admission, "admission_mode", ""),
            degraded=degraded,
        ),
        "execution_profile_hint": execution_profile,
    }


def _is_account_scope_error(exc: Exception) -> bool:
    message = str(exc or "").lower()
    return "agency_id is required" in message or "account scope" in message


def _account_scope_response(request: Request) -> Response:
    return Response(
        {
            "code": "IMPORT_ACCOUNT_SCOPE_REQUIRED",
            "detail": "Your account is not ready for imports yet.",
            "correlation_id": request_correlation_id(request) or "",
        },
        status=status.HTTP_403_FORBIDDEN,
    )


def _storage_not_ready_response(exc: StorageNotReadyError) -> Response:
    return Response(
        {
            "code": str(exc.code or "IMPORT_STORAGE_NOT_READY"),
            "detail": str(exc or "Import storage is not ready yet."),
            "retry_after_ms": int(getattr(exc, "retry_after_ms", 1500) or 1500),
            "retryable": True,
        },
        status=status.HTTP_503_SERVICE_UNAVAILABLE,
    )


@route("import/presign/", order=128)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def import_presign(request: Request) -> Response:
    """Generate a presigned upload for an import file."""
    try:
        ImportService(request.user)
    except ImportPermissionError as e:
        return error(safe_forbidden_message(e), status.HTTP_403_FORBIDDEN)

    payload, error_response = validate_payload(
        request.data if isinstance(request.data, dict) else {},
        ImportPresignSerializer,
        partial=False,
    )
    if error_response:
        return error_response
    data = payload or {}
    filename = str(data.get("filename") or "")
    parser_entry = get_parser_for_file(filename)
    if not parser_entry:
        return error(
            f"Unsupported file type: {Path(filename).suffix}",
            status.HTTP_400_BAD_REQUEST,
        )
    _, file_type = parser_entry
    try:
        size_bytes = _optional_int(data.get("size_bytes")) or 0
        expires_seconds = _optional_int(data.get("expires_seconds"))
        result = generate_presigned_upload(
            filename=filename,
            content_type=str(data.get("content_type") or "") or None,
            purpose="import",
            size_bytes=size_bytes,
            user_id=getattr(request.user, "id", None),
            role=getattr(request.user, "role", None),
            created_ip=request.META.get("REMOTE_ADDR"),
            expires_seconds=expires_seconds,
        )
    except StorageNotReadyError as exc:
        return _storage_not_ready_response(exc)
    except RuntimeError as exc:
        if _is_account_scope_error(exc):
            return _account_scope_response(request)
        raise
    except StorageError as exc:
        return error(safe_error_message(exc), status.HTTP_400_BAD_REQUEST)
    result["file_type"] = file_type
    return Response(result)


@route("import/complete/", order=129)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def import_complete(request: Request) -> Response:
    """Finalize presigned import upload and queue parsing."""
    try:
        service = ImportService(request.user)
    except ImportPermissionError as e:
        return error(safe_forbidden_message(e), status.HTTP_403_FORBIDDEN)

    payload, error_response = validate_payload(
        request.data if isinstance(request.data, dict) else {},
        ImportCompleteSerializer,
        partial=False,
    )
    if error_response:
        return error_response
    data = payload or {}
    filename = str(data.get("filename") or "")
    storage_id = str(data.get("storage_id") or "")

    parser_entry = get_parser_for_file(filename)
    if not parser_entry:
        return error(
            f"Unsupported file type: {Path(filename).suffix}",
            status.HTTP_400_BAD_REQUEST,
        )
    _, file_type = parser_entry
    requested_entity_raw = data.get("entity_type")
    requested_entity = (
        normalize_import_entity_type(requested_entity_raw)
        if isinstance(requested_entity_raw, str) and requested_entity_raw
        else None
    )

    admission = admit_import_parse(agency_id=int(service.agency_id or 0))
    if not admission.allowed:
        return _import_parse_backpressure_response(retry_after=admission.retry_after)

    try:
        complete_presigned_upload(
            storage_id=storage_id,
            user_id=getattr(request.user, "id", None),
            role=getattr(request.user, "role", None),
            created_ip=request.META.get("REMOTE_ADDR"),
        )
    except StorageNotReadyError as exc:
        return _storage_not_ready_response(exc)
    except StorageError as exc:
        return error(safe_error_message(exc), status.HTTP_400_BAD_REQUEST)

    job = service.create_job(
        filename=filename,
        file_type=file_type,
        headers=[],
        source_path=storage_id,
    )
    if requested_entity:
        job.ui_entity_hint = requested_entity

    schema = get_active_schema()
    async_result = import_parse_task.delay(
        session_id=str(job.id),
        user_id=service.user_id,
        agency_id=service.agency_id,
        schema=schema,
        correlation_id=request_correlation_id(request),
    )

    job.task_id = async_result.id
    job.status = ImportJob.Status.PARSING
    job.save()

    register_task(
        async_result.id,
        agency_id=service.agency_id,
        user_id=getattr(request.user, "id", None),
    )
    return Response(
        {
            "session_id": str(job.id),
            "task_id": async_result.id,
            "filename": filename,
            "file_type": job.file_type,
            "status": job.status,
            "job_id": str(job.id),
            **_parse_admission_payload(admission=admission),
        },
        status=status.HTTP_202_ACCEPTED,
    )


@route("import/upload/", order=127)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser])
def import_upload(request: Request) -> Response:
    """Upload a file for import and queue parsing (proxy flow)."""
    if os.environ.get("IMMOAPP_ALLOW_PROXY_UPLOADS", "0") != "1":
        return error(
            "Direct uploads are disabled. Use the presigned upload flow instead.",
            status.HTTP_403_FORBIDDEN,
        )
    try:
        service = ImportService(request.user)
    except ImportPermissionError as e:
        return error(safe_forbidden_message(e), status.HTTP_403_FORBIDDEN)

    file = request.FILES.get("file")
    if not file:
        return error("No file provided", status.HTTP_400_BAD_REQUEST)
    max_import_bytes = get_storage_config().max_import_bytes
    file_size = getattr(file, "size", None)
    if isinstance(file_size, int) and file_size > max_import_bytes:
        return error(
            f"File exceeds max import size ({max_import_bytes} bytes)",
            status.HTTP_400_BAD_REQUEST,
        )

    filename = file.name
    parser_entry = get_parser_for_file(filename)
    if not parser_entry:
        return error(
            f"Unsupported file type: {Path(filename).suffix}",
            status.HTTP_400_BAD_REQUEST,
        )
    _, file_type = parser_entry

    admission = admit_import_parse(agency_id=int(service.agency_id or 0))
    if not admission.allowed:
        return _import_parse_backpressure_response(retry_after=admission.retry_after)

    try:
        storage_id = store_fileobj(
            fileobj=file.file,
            filename=filename,
            content_type=getattr(file, "content_type", None),
            purpose="import",
            user_id=getattr(request.user, "id", None),
            role=getattr(request.user, "role", None),
            created_ip=request.META.get("REMOTE_ADDR"),
        )
    except RuntimeError as exc:
        if _is_account_scope_error(exc):
            return _account_scope_response(request)
        raise
    except StorageError as exc:
        return error(safe_error_message(exc), status.HTTP_400_BAD_REQUEST)

    job = service.create_job(
        filename=filename,
        file_type=file_type,
        headers=[],
        source_path=str(storage_id),
    )

    schema = get_active_schema()
    async_result = import_parse_task.delay(
        session_id=str(job.id),
        user_id=service.user_id,
        agency_id=service.agency_id,
        schema=schema,
        correlation_id=request_correlation_id(request),
    )

    job.task_id = async_result.id
    job.status = ImportJob.Status.PARSING
    job.save()

    register_task(
        async_result.id,
        agency_id=service.agency_id,
        user_id=getattr(request.user, "id", None),
    )
    return Response(
        {
            "session_id": str(job.id),
            "task_id": async_result.id,
            "filename": filename,
            "file_type": job.file_type,
            "status": job.status,
            "job_id": str(job.id),
            **_parse_admission_payload(admission=admission),
        },
        status=status.HTTP_202_ACCEPTED,
    )
