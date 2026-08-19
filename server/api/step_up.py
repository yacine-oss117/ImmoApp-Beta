"""Step-up authentication helper for sensitive write endpoints."""

from __future__ import annotations

import os
import time
import uuid
from datetime import UTC, datetime
from typing import cast

from django.core import signing
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response

_STEP_UP_HEADER = "X-Immoapp-Step-Up"
_STEP_UP_SALT = "immoapp-step-up-v1"
_STEP_UP_REQUIRED_CODE = "STEP_UP_REQUIRED"
_STEP_UP_INVALID_CODE = "STEP_UP_INVALID"
_STEP_UP_EXPIRED_CODE = "STEP_UP_EXPIRED"


def step_up_max_age_seconds() -> int:
    raw = os.environ.get("IMMOAPP_STEP_UP_MAX_AGE_SECONDS", "600").strip()
    try:
        value = int(raw)
    except ValueError:
        value = 600
    return max(60, min(3600, value))


def _step_up_required() -> bool:
    raw = os.environ.get("IMMOAPP_REQUIRE_STEP_UP_SENSITIVE", "1").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def step_up_clock_skew_seconds() -> int:
    raw = os.environ.get("IMMOAPP_STEP_UP_CLOCK_SKEW_SECONDS", "30").strip()
    try:
        value = int(raw)
    except ValueError:
        value = 30
    return max(0, min(300, value))


def issue_step_up_token(*, user_id: int) -> str:
    payload = {
        "uid": int(user_id),
        "nonce": uuid.uuid4().hex,
        # iat is explicit proof-of-authentication time for audit consumers.
        "iat": int(time.time()),
    }
    return cast(str, signing.dumps(payload, salt=_STEP_UP_SALT, compress=True))


def step_up_iat_to_datetime(claims: dict[str, object]) -> datetime:
    iat_raw = claims.get("iat")
    if not isinstance(iat_raw, int):
        raise ValueError("Invalid step-up iat claim.")
    return datetime.fromtimestamp(iat_raw, tz=UTC)


def parse_step_up_claims(request: Request) -> tuple[dict[str, object] | None, Response | None]:
    if not _step_up_required():
        expected_user_id = getattr(request.user, "id", None)
        return (
            {
                "uid": int(expected_user_id) if expected_user_id is not None else None,
                "iat": int(time.time()),
                "nonce": "policy-disabled",
            },
            None,
        )
    token = str(request.headers.get(_STEP_UP_HEADER, "") or "").strip()
    if not token:
        return (
            None,
            Response(
                {
                    "code": _STEP_UP_REQUIRED_CODE,
                    "detail": "Step-up authentication is required for this action.",
                },
                status=status.HTTP_403_FORBIDDEN,
            ),
        )
    try:
        payload = signing.loads(
            token,
            salt=_STEP_UP_SALT,
            max_age=step_up_max_age_seconds(),
        )
    except signing.SignatureExpired:
        return (
            None,
            Response(
                {
                    "code": _STEP_UP_EXPIRED_CODE,
                    "detail": "Step-up authentication has expired. Re-authenticate and retry.",
                },
                status=status.HTTP_403_FORBIDDEN,
            ),
        )
    except signing.BadSignature:
        return (
            None,
            Response(
                {
                    "code": _STEP_UP_INVALID_CODE,
                    "detail": "Invalid step-up authentication token.",
                },
                status=status.HTTP_403_FORBIDDEN,
            ),
        )
    expected_user_id = getattr(request.user, "id", None)
    if not isinstance(payload, dict):
        return (
            None,
            Response(
                {
                    "code": _STEP_UP_INVALID_CODE,
                    "detail": "Invalid step-up authentication token.",
                },
                status=status.HTTP_403_FORBIDDEN,
            ),
        )
    token_user_id = payload.get("uid")
    if expected_user_id is None or token_user_id != int(expected_user_id):
        return (
            None,
            Response(
                {
                    "code": _STEP_UP_INVALID_CODE,
                    "detail": "Step-up token does not match the authenticated user.",
                },
                status=status.HTTP_403_FORBIDDEN,
            ),
        )
    iat_raw = payload.get("iat")
    if not isinstance(iat_raw, int):
        return (
            None,
            Response(
                {
                    "code": _STEP_UP_INVALID_CODE,
                    "detail": "Invalid step-up authentication token.",
                },
                status=status.HTTP_403_FORBIDDEN,
            ),
        )
    now = int(time.time())
    skew = step_up_clock_skew_seconds()
    if iat_raw > (now + skew):
        return (
            None,
            Response(
                {
                    "code": _STEP_UP_INVALID_CODE,
                    "detail": "Invalid step-up authentication token.",
                },
                status=status.HTTP_403_FORBIDDEN,
            ),
        )
    if (now - iat_raw) > step_up_max_age_seconds():
        return (
            None,
            Response(
                {
                    "code": _STEP_UP_EXPIRED_CODE,
                    "detail": "Step-up authentication has expired. Re-authenticate and retry.",
                },
                status=status.HTTP_403_FORBIDDEN,
            ),
        )
    return payload, None


def require_step_up(request: Request) -> Response | None:
    _claims, error = parse_step_up_claims(request)
    return error


__all__ = [
    "issue_step_up_token",
    "parse_step_up_claims",
    "require_step_up",
    "step_up_clock_skew_seconds",
    "step_up_iat_to_datetime",
    "step_up_max_age_seconds",
]
