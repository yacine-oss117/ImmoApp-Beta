"""Global DRF exception handler with stable error payloads."""

from __future__ import annotations

import logging
from http import HTTPStatus
from typing import Any

from rest_framework import status
from rest_framework.exceptions import APIException, ValidationError
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

from server.logging_config import get_correlation_id

logger = logging.getLogger(__name__)

_STATUS_CODE_MAP: dict[int, str] = {
    status.HTTP_400_BAD_REQUEST: "bad_request",
    status.HTTP_401_UNAUTHORIZED: "unauthorized",
    status.HTTP_403_FORBIDDEN: "forbidden",
    status.HTTP_404_NOT_FOUND: "not_found",
    status.HTTP_405_METHOD_NOT_ALLOWED: "method_not_allowed",
    status.HTTP_409_CONFLICT: "conflict",
    status.HTTP_415_UNSUPPORTED_MEDIA_TYPE: "unsupported_media_type",
    status.HTTP_429_TOO_MANY_REQUESTS: "rate_limited",
    status.HTTP_500_INTERNAL_SERVER_ERROR: "internal_error",
    status.HTTP_503_SERVICE_UNAVAILABLE: "service_unavailable",
}


def global_exception_handler(exc: Exception, context: dict[str, Any]) -> Response:
    """Normalize all API exceptions into a stable JSON error shape."""
    response = drf_exception_handler(exc, context)
    if response is None:
        logger.exception("Unhandled API exception", exc_info=exc)
        return _build_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
            code="internal_error",
        )

    payload = _normalize_payload(exc=exc, response=response)
    response.data = payload
    return response


def _normalize_payload(*, exc: Exception, response: Response) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    data = response.data

    if isinstance(data, dict):
        payload.update(data)
    elif data is not None:
        payload["detail"] = str(data)

    if "detail" not in payload:
        if isinstance(exc, ValidationError):
            payload["detail"] = "Validation failed"
        else:
            payload["detail"] = _default_status_text(response.status_code)

    if isinstance(data, dict):
        field_errors = {k: v for k, v in data.items() if k != "detail"}
        if field_errors and "errors" not in payload:
            payload["errors"] = field_errors

    payload.setdefault("code", _error_code(exc=exc, status_code=response.status_code))

    correlation_id = get_correlation_id()
    if correlation_id:
        payload["correlation_id"] = correlation_id

    return payload


def _error_code(*, exc: Exception, status_code: int) -> str:
    if isinstance(exc, APIException):
        drf_code = getattr(exc, "default_code", "") or ""
        if drf_code:
            return str(drf_code)
    return _STATUS_CODE_MAP.get(status_code, "error")


def _default_status_text(status_code: int) -> str:
    try:
        return HTTPStatus(status_code).phrase
    except ValueError:
        return "Request failed"


def _build_response(*, status_code: int, detail: str, code: str) -> Response:
    payload: dict[str, Any] = {
        "detail": detail,
        "code": code,
    }
    correlation_id = get_correlation_id()
    if correlation_id:
        payload["correlation_id"] = correlation_id
    return Response(payload, status=status_code)


__all__ = ["global_exception_handler"]
