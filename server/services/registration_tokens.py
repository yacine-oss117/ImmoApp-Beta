"""Mechanical registration helper functions kept separate from lifecycle orchestration."""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import string
from typing import Any
from uuid import UUID

from rest_framework_simplejwt.tokens import RefreshToken

from core.ale_utils import is_legacy_ale_mask, is_structured_ale_mask
from core.env_flags import auth_session_tracking_enabled
from core.utils.common import norm_text
from server.services import auth_sessions
from server.services.errors import PermissionDeniedError

_DEFAULT_APPROVAL_TOKEN_EXPIRY_DAYS = 7
_DEFAULT_ACTIVATION_CODE_EXPIRY_HOURS = 72
_DEFAULT_INVITE_CODE_EXPIRY_HOURS = 48
_DEFAULT_PENDING_EXPIRY_DAYS = 30
_DEFAULT_INVITE_RESEND_COOLDOWN_SECONDS = 3600


def _env_int(name: str, default: int, *, min_v: int, max_v: int) -> int:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(min_v, min(max_v, value))


def _approval_token_expiry_days() -> int:
    return _env_int(
        "IMMOAPP_APPROVAL_TOKEN_EXPIRY_DAYS",
        _DEFAULT_APPROVAL_TOKEN_EXPIRY_DAYS,
        min_v=1,
        max_v=30,
    )


def _activation_expiry_hours() -> int:
    return _env_int(
        "IMMOAPP_ACTIVATION_CODE_EXPIRY_HOURS",
        _DEFAULT_ACTIVATION_CODE_EXPIRY_HOURS,
        min_v=1,
        max_v=24 * 14,
    )


def _invite_expiry_hours(expires_seconds: int | None = None) -> int:
    if expires_seconds is None:
        return _env_int(
            "IMMOAPP_INVITE_CODE_EXPIRY_HOURS",
            _DEFAULT_INVITE_CODE_EXPIRY_HOURS,
            min_v=1,
            max_v=24 * 14,
        )
    bounded_seconds = max(900, min(7 * 24 * 3600, int(expires_seconds)))
    return max(1, int(round(bounded_seconds / 3600.0)))


def _pending_expiry_days() -> int:
    return _env_int(
        "IMMOAPP_PENDING_REGISTRATION_EXPIRY_DAYS",
        _DEFAULT_PENDING_EXPIRY_DAYS,
        min_v=1,
        max_v=365,
    )


def _invite_resend_cooldown_seconds() -> int:
    return _env_int(
        "IMMOAPP_INVITE_RESEND_COOLDOWN_SECONDS",
        _DEFAULT_INVITE_RESEND_COOLDOWN_SECONDS,
        min_v=60,
        max_v=24 * 3600,
    )


def _platform_admin_email() -> str:
    return (os.environ.get("IMMOAPP_PLATFORM_ADMIN_EMAIL") or "").strip()


def _public_base_url_with_source() -> tuple[str, str]:
    appdata_root = (os.environ.get("IMMOAPP_APPDATA_ROOT") or "").strip()
    configured = (os.environ.get("IMMOAPP_PUBLIC_BASE_URL") or "").strip().rstrip("/")
    if configured:
        configured_lower = configured.lower()
        if appdata_root == "/var/lib/immoapp" and configured_lower in {
            "http://localhost",
            "http://localhost:80",
            "http://127.0.0.1",
            "http://127.0.0.1:8000",
        }:
            return "https://localhost", "env_local_proxy_upgraded"
        return configured, "env"
    if appdata_root == "/var/lib/immoapp":
        return "https://localhost", "fallback_local_proxy"
    return "http://127.0.0.1:8000", "fallback_localhost"


def _public_base_url() -> str:
    return _public_base_url_with_source()[0]


def _code_alphabet() -> str:
    return string.ascii_uppercase + string.digits


def _generate_code(*, length: int) -> str:
    alphabet = _code_alphabet()
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _verify_code(input_code: str, stored_hash: str) -> bool:
    normalized = input_code.strip().upper()
    if not normalized or not stored_hash:
        return False
    return hmac.compare_digest(_sha256(normalized), stored_hash)


def _generate_agency_code(name: str) -> str:
    prefix = norm_text(name).replace(" ", "").upper()
    if not prefix:
        prefix = "AGENCY"
    prefix = "".join(ch for ch in prefix if ch.isalnum())[:10] or "AGENCY"
    return f"{prefix}{secrets.randbelow(9000) + 1000}"


def _parse_uuid(text: str) -> UUID:
    try:
        return UUID(str(text))
    except (TypeError, ValueError) as exc:
        raise PermissionDeniedError("Invalid or expired link.") from exc


def _resolve_ale_text(public_value: str, encrypted_value: str) -> str:
    text = str(public_value or "")
    if not text:
        return ""
    if not (is_structured_ale_mask(text) or is_legacy_ale_mask(text)):
        return text
    cipher = str(encrypted_value or "")
    if not cipher:
        return ""
    from core.encryption import get_optional_encryption_service

    enc = get_optional_encryption_service()
    if enc is None:
        return ""
    try:
        return str(enc.decrypt(cipher) or "")
    except Exception:
        return ""


def _registration_plain(record: object, field_name: str) -> str:
    return _resolve_ale_text(
        str(getattr(record, field_name, "") or ""),
        str(getattr(record, f"{field_name}_enc", "") or ""),
    )


def _invite_name_parts(name: str) -> tuple[str, str]:
    parts = [part for part in (name or "").split() if part]
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], " ".join(parts[1:])


def _issue_auth_tokens(
    *,
    user: Any,
    source_ip: str | None,
    user_agent: str | None,
) -> dict[str, str]:
    refresh = RefreshToken.for_user(user)
    if auth_session_tracking_enabled():
        session = auth_sessions.issue_session(user=user, source_ip=source_ip, user_agent=user_agent)
        refresh["sid"] = str(session.session_id)
        auth_sessions.bind_refresh_jti(
            session_id=session.session_id,
            refresh_jti=str(refresh.get("jti", "")),
        )
    return {"access": str(refresh.access_token), "refresh": str(refresh)}
