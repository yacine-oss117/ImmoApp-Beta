"""
Shared helpers for API view modules.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal

from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response

from server.logging_config import get_correlation_id

_INT_RE = re.compile(r"^[+-]?\d+$")


def parse_int(value: str | None, default: int | None = None) -> int | None:
    """Parse an integer query param safely."""
    if value is None:
        return default
    value = value.strip()
    if value == "":
        return default
    try:
        if not _INT_RE.match(value):
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def parse_bool(value: str | None, default: bool = False) -> bool:
    """Parse a boolean query param safely."""
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    return default


def parse_timestamp(value: str | None) -> str | None:
    """Parse an ISO-8601 timestamp or epoch seconds into an ISO string."""
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    if text.isdigit():
        try:
            dt = datetime.fromtimestamp(int(text), tz=UTC)
            return dt.isoformat()
        except (ValueError, OSError, OverflowError):
            return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.isoformat()


def error(message: str, code: int, errors: Mapping[str, object] | None = None) -> Response:
    """Return a consistent error payload."""
    payload: dict[str, object] = {"detail": message}
    if errors:
        payload["errors"] = errors
    return Response(payload, status=code)


def conflict_error(
    message: str,
    field: str = "row_version",
    current_version: int | None = None,
    current_record: Mapping[str, object] | None = None,
    resource_url: str | None = None,
) -> Response:
    """Return a standard optimistic-concurrency conflict payload."""
    payload_errors: dict[str, object] = {field: ["stale"]}
    if current_version is not None:
        payload_errors["current_row_version"] = current_version
    payload_errors["action"] = "REFETCH_AND_RETRY"
    if resource_url:
        payload_errors["resource_url"] = resource_url
    if current_record is not None:
        payload_errors["current_record"] = _sanitize_conflict_record(current_record)
    return error(message, status.HTTP_409_CONFLICT, errors=payload_errors)


def _sanitize_conflict_record(record: Mapping[str, object]) -> dict[str, object]:
    """Return a JSON-safe conflict snapshot without encrypted internals."""
    redacted_suffixes = ("_enc", "_search_idx")
    result: dict[str, object] = {}
    for key, value in record.items():
        if any(key.endswith(suffix) for suffix in redacted_suffixes):
            continue
        result[key] = _json_safe(value)
    return result


def _json_safe(value: object) -> object:
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, bytes):
        return "<bytes>"
    if isinstance(value, Mapping):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    return str(value)


def safe_error_message(_exc: Exception) -> str:
    """Return a generic error message for user-facing responses."""
    return "Invalid request"


def safe_forbidden_message(_exc: Exception | None = None) -> str:
    """Return a generic forbidden message for user-facing responses."""
    return "Forbidden"


def safe_not_found_message(_exc: Exception | None = None) -> str:
    """Return a generic not-found message for user-facing responses."""
    return "Resource not found"


def list_response(items: object, total: int | None = None) -> Response:
    """Return a consistent list payload with an item count."""
    resolved_total = total
    if resolved_total is None:
        if items is None:
            resolved_total = 0
        else:
            try:
                resolved_total = len(items)  # type: ignore[arg-type]
            except Exception:
                resolved_total = 0
    return Response({"items": items, "total": resolved_total})


def require_confirmation(request: Request, expected: str) -> Response | None:
    """Validate a confirmation token for destructive actions."""
    token = request.headers.get("X-Confirm-Token") or request.query_params.get("confirm")
    if token != expected:
        return error("Confirmation token required", 400)
    return None


def actor(request: Request) -> str | None:
    """Return the audit actor based on the authenticated user."""
    user = getattr(request, "user", None)
    if user and getattr(user, "is_authenticated", False):
        return str(getattr(user, "username", ""))
    return None


def request_correlation_id(_request: Request) -> str | None:
    """Return the current request correlation id for task propagation."""
    return get_correlation_id()


def is_superuser(request: Request) -> bool:
    """Return True when the authenticated user is a superuser."""
    user = getattr(request, "user", None)
    if user and getattr(user, "is_authenticated", False):
        return bool(getattr(user, "is_superuser", False))
    return False


def agency_id(request: Request) -> int | None:
    """Return the tenant agency ID from the authenticated user."""
    user = getattr(request, "user", None)
    if user and getattr(user, "is_authenticated", False):
        direct_id = getattr(user, "agency_id", None)
        if direct_id is not None:
            resolved = int(direct_id)
            return resolved if resolved > 0 else None
        agency = getattr(user, "agency", None)
        if agency:
            resolved = int(agency.id)
            return resolved if resolved > 0 else None
    return None


def with_cache(response: Response, max_age: int = 3600) -> Response:
    """Apply cache-control headers to a response."""
    bounded_max_age = max(0, int(max_age))
    if bounded_max_age == 0:
        response["Cache-Control"] = "private, no-store"
        return response
    response["Cache-Control"] = f"max-age={bounded_max_age}, private"
    return response
