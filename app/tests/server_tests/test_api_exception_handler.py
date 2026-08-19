from __future__ import annotations

# ruff: noqa: E402
from app.tests.server_tests._integration_auth_helpers import ensure_django

ensure_django()

from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIRequestFactory
from rest_framework.views import APIView

from server.api.exception_handler import global_exception_handler
from server.logging_config import set_correlation_id


def _context() -> dict[str, object]:
    factory = APIRequestFactory()
    request = factory.get("/api/v1/clients/")
    return {"request": request, "view": APIView()}


def test_validation_error_payload_is_structured() -> None:
    response = global_exception_handler(
        ValidationError({"phone": ["This field is required."]}),
        _context(),
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    payload = response.data
    assert payload["detail"] == "Validation failed"
    assert payload["code"] == "invalid"
    assert payload["errors"]["phone"] == ["This field is required."]


def test_unhandled_error_payload_is_internal_and_includes_correlation_id() -> None:
    set_correlation_id("test-cid-123")
    try:
        response = global_exception_handler(RuntimeError("boom"), _context())
    finally:
        set_correlation_id(None)

    assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    payload = response.data
    assert payload["detail"] == "Internal server error"
    assert payload["code"] == "internal_error"
    assert payload["correlation_id"] == "test-cid-123"
