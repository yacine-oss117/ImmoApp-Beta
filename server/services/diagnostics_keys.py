"""Diagnostics signing key enrollment and lifecycle service."""

from __future__ import annotations

import base64
import hashlib
import secrets
from datetime import timedelta
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519
from django.utils import timezone

from core.contracts.diagnostics_contract import (
    DIAGNOSTICS_PAYLOAD_VERSION,
    DIAGNOSTICS_SIGNATURE_ALGORITHM,
    DIAGNOSTICS_SIGNATURE_ALGORITHM_CNG_P256,
    DIAGNOSTICS_SIGNATURE_ALGORITHM_ED25519,
    DIAGNOSTICS_SUPPORTED_SIGNATURE_ALGORITHMS,
)
from core.contracts.idempotency_canonical_json import canonical_json_dumps
from server.accounts.models import DiagnosticsEnrollmentToken, DiagnosticsSigningKey
from server.services import auth_events
from server.services.errors import NotFoundError, PermissionDeniedError

_TOKEN_MIN_SECONDS = 60
_TOKEN_MAX_SECONDS = 24 * 60 * 60
_TOKEN_DEFAULT_SECONDS = 15 * 60


def _diagnostics_algorithm_for_public_key(public_key: object) -> str | None:
    if isinstance(public_key, ed25519.Ed25519PublicKey):
        return DIAGNOSTICS_SIGNATURE_ALGORITHM_ED25519
    if isinstance(public_key, ec.EllipticCurvePublicKey):
        if isinstance(public_key.curve, ec.SECP256R1):
            return DIAGNOSTICS_SIGNATURE_ALGORITHM_CNG_P256
        return None
    return None


def _is_authenticated(actor: object | None) -> bool:
    return bool(actor and getattr(actor, "is_authenticated", False))


def _actor_agency_id(actor: object | None) -> int | None:
    if actor is None:
        return None
    raw = getattr(actor, "agency_id", None)
    if isinstance(raw, int) and raw > 0:
        return raw
    return None


def _is_tenant_admin(actor: object | None) -> bool:
    if actor is None:
        return False
    if bool(getattr(actor, "is_superuser", False)):
        return True
    return bool(getattr(actor, "role", "") == "manager" and getattr(actor, "is_owner", False))


def _event_identity(actor: object | None) -> tuple[int | None, int | None, str | None]:
    if actor is None:
        return None, None, None
    user_id = getattr(actor, "id", None)
    username = getattr(actor, "username", None)
    return (
        int(user_id) if isinstance(user_id, int) else None,
        _actor_agency_id(actor),
        str(username) if isinstance(username, str) and username else None,
    )


def _log_event(
    *,
    actor: object | None,
    event_type: str,
    outcome: str,
    reason_code: str,
    request_id: str | None = None,
    source_ip: str | None = None,
    user_agent: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    user_id, agency_id, identifier = _event_identity(actor)
    auth_events.log_auth_event(
        event_type=event_type,
        outcome=outcome,
        agency_id=agency_id,
        user_id=user_id,
        identifier=identifier,
        reason_code=reason_code,
        source_ip=source_ip,
        user_agent=user_agent,
        request_id=request_id,
        details=details or {},
        fail_silently=True,
    )


def _require_authenticated_tenant_actor(actor: object | None) -> int:
    if not _is_authenticated(actor):
        raise PermissionDeniedError("Authentication required.")
    agency_id = _actor_agency_id(actor)
    if agency_id is None:
        raise PermissionDeniedError("Tenant context required.")
    return agency_id


def _normalize_token_ttl(expires_seconds: int | None) -> int:
    if expires_seconds is None:
        return _TOKEN_DEFAULT_SECONDS
    value = int(expires_seconds)
    return max(_TOKEN_MIN_SECONDS, min(_TOKEN_MAX_SECONDS, value))


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def issue_enrollment_token(
    *,
    actor: object | None,
    device_id: str | None = None,
    expires_seconds: int | None = None,
    request_id: str | None = None,
    source_ip: str | None = None,
    user_agent: str | None = None,
) -> dict[str, object]:
    agency_id = _require_authenticated_tenant_actor(actor)
    if not _is_tenant_admin(actor):
        _log_event(
            actor=actor,
            event_type="diagnostics_enrollment_token_issued",
            outcome="denied",
            reason_code="tenant_admin_required",
            request_id=request_id,
            source_ip=source_ip,
            user_agent=user_agent,
            details={"device_id": str(device_id or "")},
        )
        raise PermissionDeniedError("Tenant admin approval required.")

    ttl_seconds = _normalize_token_ttl(expires_seconds)
    raw_token = secrets.token_urlsafe(24)
    now = timezone.now()
    token = DiagnosticsEnrollmentToken.objects.create(
        agency_id=agency_id,
        token_hash=_token_hash(raw_token),
        device_id=str(device_id or "").strip(),
        issued_by=actor if hasattr(actor, "pk") else None,
        expires_at=now + timedelta(seconds=ttl_seconds),
    )
    _log_event(
        actor=actor,
        event_type="diagnostics_enrollment_token_issued",
        outcome="success",
        reason_code="token_issued",
        request_id=request_id,
        source_ip=source_ip,
        user_agent=user_agent,
        details={
            "token_id": str(token.token_id),
            "device_id": token.device_id,
            "expires_seconds": ttl_seconds,
        },
    )
    return {
        "token": raw_token,
        "token_id": str(token.token_id),
        "expires_at": token.expires_at.isoformat(),
        "device_id": token.device_id,
    }


def _consume_enrollment_token(
    *,
    actor: object | None,
    agency_id: int,
    enrollment_token: str,
    device_id: str,
    request_id: str | None = None,
    source_ip: str | None = None,
    user_agent: str | None = None,
) -> DiagnosticsEnrollmentToken:
    token_value = enrollment_token.strip()
    if not token_value:
        _log_event(
            actor=actor,
            event_type="diagnostics_key_enroll_denied",
            outcome="denied",
            reason_code="token_required",
            request_id=request_id,
            source_ip=source_ip,
            user_agent=user_agent,
            details={"device_id": device_id},
        )
        raise PermissionDeniedError("Enrollment token is required.")

    token = (
        DiagnosticsEnrollmentToken.objects.select_for_update()
        .filter(
            agency_id=agency_id,
            token_hash=_token_hash(token_value),
        )
        .first()
    )
    if token is None:
        _log_event(
            actor=actor,
            event_type="diagnostics_key_enroll_denied",
            outcome="denied",
            reason_code="invalid_token",
            request_id=request_id,
            source_ip=source_ip,
            user_agent=user_agent,
            details={"device_id": device_id},
        )
        raise PermissionDeniedError("Invalid enrollment token.")

    now = timezone.now()
    if token.consumed_at is not None:
        _log_event(
            actor=actor,
            event_type="diagnostics_key_enroll_denied",
            outcome="denied",
            reason_code="token_already_consumed",
            request_id=request_id,
            source_ip=source_ip,
            user_agent=user_agent,
            details={"token_id": str(token.token_id), "device_id": device_id},
        )
        raise PermissionDeniedError("Enrollment token already used.")

    if token.expires_at <= now:
        _log_event(
            actor=actor,
            event_type="diagnostics_key_enroll_denied",
            outcome="denied",
            reason_code="token_expired",
            request_id=request_id,
            source_ip=source_ip,
            user_agent=user_agent,
            details={"token_id": str(token.token_id), "device_id": device_id},
        )
        raise PermissionDeniedError("Enrollment token expired.")

    if token.device_id and token.device_id != device_id:
        _log_event(
            actor=actor,
            event_type="diagnostics_key_enroll_denied",
            outcome="denied",
            reason_code="token_device_mismatch",
            request_id=request_id,
            source_ip=source_ip,
            user_agent=user_agent,
            details={
                "token_id": str(token.token_id),
                "token_device_id": token.device_id,
                "requested_device_id": device_id,
            },
        )
        raise PermissionDeniedError("Enrollment token does not match device.")

    token.consumed_at = now
    token.consumed_by = actor if hasattr(actor, "pk") else None
    token.save(update_fields=["consumed_at", "consumed_by"])
    _log_event(
        actor=actor,
        event_type="diagnostics_enrollment_token_consumed",
        outcome="success",
        reason_code="token_consumed",
        request_id=request_id,
        source_ip=source_ip,
        user_agent=user_agent,
        details={"token_id": str(token.token_id), "device_id": device_id},
    )
    return token


def register_signing_key(
    *,
    actor: object | None,
    device_id: str,
    signature_key_id: str,
    public_key: str,
    enrollment_token: str | None = None,
    admin_approved: bool = False,
    request_id: str | None = None,
    source_ip: str | None = None,
    user_agent: str | None = None,
) -> dict[str, object]:
    agency_id = _require_authenticated_tenant_actor(actor)
    normalized_device_id = str(device_id).strip()
    normalized_sig_key_id = str(signature_key_id).strip()
    normalized_public_key = str(public_key).strip()
    if not normalized_device_id:
        raise ValueError("device_id is required")
    if not normalized_sig_key_id:
        raise ValueError("signature_key_id is required")
    if not normalized_public_key:
        raise ValueError("public_key is required")

    _log_event(
        actor=actor,
        event_type="diagnostics_key_enroll_requested",
        outcome="attempt",
        reason_code="requested",
        request_id=request_id,
        source_ip=source_ip,
        user_agent=user_agent,
        details={"device_id": normalized_device_id, "signature_key_id": normalized_sig_key_id},
    )

    approved_by = None
    reason_code = "token_approved"
    if admin_approved:
        if not _is_tenant_admin(actor):
            _log_event(
                actor=actor,
                event_type="diagnostics_key_enroll_denied",
                outcome="denied",
                reason_code="tenant_admin_required",
                request_id=request_id,
                source_ip=source_ip,
                user_agent=user_agent,
                details={
                    "device_id": normalized_device_id,
                    "signature_key_id": normalized_sig_key_id,
                },
            )
            raise PermissionDeniedError("Tenant admin approval required.")
        approved_by = actor if hasattr(actor, "pk") else None
        reason_code = "tenant_admin_approved"
    else:
        _consume_enrollment_token(
            actor=actor,
            agency_id=agency_id,
            enrollment_token=str(enrollment_token or ""),
            device_id=normalized_device_id,
            request_id=request_id,
            source_ip=source_ip,
            user_agent=user_agent,
        )

    _log_event(
        actor=actor,
        event_type="diagnostics_key_enroll_approved",
        outcome="success",
        reason_code=reason_code,
        request_id=request_id,
        source_ip=source_ip,
        user_agent=user_agent,
        details={"device_id": normalized_device_id, "signature_key_id": normalized_sig_key_id},
    )

    now = timezone.now()
    key, created = DiagnosticsSigningKey.objects.update_or_create(
        agency_id=agency_id,
        device_id=normalized_device_id,
        signature_key_id=normalized_sig_key_id,
        defaults={
            "public_key": normalized_public_key,
            "is_active": True,
            "enrolled_by": actor if hasattr(actor, "pk") else None,
            "approved_by": approved_by,
            "revoked_at": None,
            "updated_at": now,
        },
    )
    _log_event(
        actor=actor,
        event_type="diagnostics_key_registered",
        outcome="success",
        reason_code="created" if created else "updated",
        request_id=request_id,
        source_ip=source_ip,
        user_agent=user_agent,
        details={"device_id": key.device_id, "signature_key_id": key.signature_key_id},
    )
    return {
        "id": int(key.id),
        "agency_id": int(key.agency_id),
        "device_id": key.device_id,
        "signature_key_id": key.signature_key_id,
        "is_active": bool(key.is_active),
        "created": bool(created),
    }


def rotate_signing_key(
    *,
    actor: object | None,
    device_id: str,
    signature_key_id: str,
    public_key: str,
    request_id: str | None = None,
    source_ip: str | None = None,
    user_agent: str | None = None,
) -> dict[str, object]:
    agency_id = _require_authenticated_tenant_actor(actor)
    if not _is_tenant_admin(actor):
        _log_event(
            actor=actor,
            event_type="diagnostics_key_rotated",
            outcome="denied",
            reason_code="tenant_admin_required",
            request_id=request_id,
            source_ip=source_ip,
            user_agent=user_agent,
            details={"device_id": str(device_id)},
        )
        raise PermissionDeniedError("Tenant admin approval required.")
    normalized_device_id = str(device_id).strip()
    normalized_sig_key_id = str(signature_key_id).strip()
    normalized_public_key = str(public_key).strip()
    if not normalized_device_id or not normalized_sig_key_id or not normalized_public_key:
        raise ValueError("device_id, signature_key_id, and public_key are required")

    now = timezone.now()
    revoked_count = (
        DiagnosticsSigningKey.objects.filter(
            agency_id=agency_id,
            device_id=normalized_device_id,
            is_active=True,
        )
        .exclude(signature_key_id=normalized_sig_key_id)
        .update(is_active=False, revoked_at=now)
    )
    key, _created = DiagnosticsSigningKey.objects.update_or_create(
        agency_id=agency_id,
        device_id=normalized_device_id,
        signature_key_id=normalized_sig_key_id,
        defaults={
            "public_key": normalized_public_key,
            "is_active": True,
            "enrolled_by": actor if hasattr(actor, "pk") else None,
            "approved_by": actor if hasattr(actor, "pk") else None,
            "revoked_at": None,
        },
    )
    _log_event(
        actor=actor,
        event_type="diagnostics_key_rotated",
        outcome="success",
        reason_code="rotation_complete",
        request_id=request_id,
        source_ip=source_ip,
        user_agent=user_agent,
        details={
            "device_id": normalized_device_id,
            "signature_key_id": normalized_sig_key_id,
            "revoked_count": int(revoked_count),
        },
    )
    return {
        "id": int(key.id),
        "device_id": key.device_id,
        "signature_key_id": key.signature_key_id,
        "revoked_count": int(revoked_count),
    }


def revoke_signing_key(
    *,
    actor: object | None,
    device_id: str,
    signature_key_id: str | None = None,
    request_id: str | None = None,
    source_ip: str | None = None,
    user_agent: str | None = None,
) -> dict[str, object]:
    agency_id = _require_authenticated_tenant_actor(actor)
    if not _is_tenant_admin(actor):
        _log_event(
            actor=actor,
            event_type="diagnostics_key_revoked",
            outcome="denied",
            reason_code="tenant_admin_required",
            request_id=request_id,
            source_ip=source_ip,
            user_agent=user_agent,
            details={"device_id": str(device_id)},
        )
        raise PermissionDeniedError("Tenant admin approval required.")
    normalized_device_id = str(device_id).strip()
    normalized_sig_key_id = str(signature_key_id or "").strip()
    if not normalized_device_id:
        raise ValueError("device_id is required")

    now = timezone.now()
    queryset = DiagnosticsSigningKey.objects.filter(
        agency_id=agency_id,
        device_id=normalized_device_id,
        is_active=True,
    )
    if normalized_sig_key_id:
        queryset = queryset.filter(signature_key_id=normalized_sig_key_id)
    revoked_count = int(queryset.update(is_active=False, revoked_at=now))
    if revoked_count <= 0:
        raise NotFoundError("No active diagnostics keys found.")
    _log_event(
        actor=actor,
        event_type="diagnostics_key_revoked",
        outcome="success",
        reason_code="revoked",
        request_id=request_id,
        source_ip=source_ip,
        user_agent=user_agent,
        details={
            "device_id": normalized_device_id,
            "signature_key_id": normalized_sig_key_id or None,
            "revoked_count": revoked_count,
        },
    )
    return {
        "device_id": normalized_device_id,
        "signature_key_id": normalized_sig_key_id or None,
        "revoked_count": revoked_count,
    }


def verify_diagnostics_signature(
    *,
    actor: object | None,
    device_id: str,
    signature_key_id: str,
    payload: object,
    signature: str,
    payload_version: str | None = None,
    algorithm: str | None = None,
    request_id: str | None = None,
    source_ip: str | None = None,
    user_agent: str | None = None,
) -> dict[str, object]:
    agency_id = _require_authenticated_tenant_actor(actor)
    normalized_device_id = str(device_id).strip()
    normalized_sig_key_id = str(signature_key_id).strip()
    normalized_signature = str(signature).strip()
    effective_version = (payload_version or DIAGNOSTICS_PAYLOAD_VERSION).strip()
    effective_algorithm = (algorithm or DIAGNOSTICS_SIGNATURE_ALGORITHM).strip().lower()
    if not normalized_device_id or not normalized_sig_key_id or not normalized_signature:
        raise ValueError("device_id, signature_key_id, and signature are required")
    if effective_algorithm not in DIAGNOSTICS_SUPPORTED_SIGNATURE_ALGORITHMS:
        _log_event(
            actor=actor,
            event_type="diagnostics_signature_verified",
            outcome="denied",
            reason_code="unsupported_algorithm",
            request_id=request_id,
            source_ip=source_ip,
            user_agent=user_agent,
            details={
                "device_id": normalized_device_id,
                "signature_key_id": normalized_sig_key_id,
                "algorithm": effective_algorithm,
            },
        )
        return {
            "valid": False,
            "code": "UNSUPPORTED_ALGORITHM",
            "detail": "Unsupported diagnostics signature algorithm",
            "algorithm": effective_algorithm,
        }
    if effective_version != DIAGNOSTICS_PAYLOAD_VERSION:
        _log_event(
            actor=actor,
            event_type="diagnostics_signature_verified",
            outcome="denied",
            reason_code="unsupported_payload_version",
            request_id=request_id,
            source_ip=source_ip,
            user_agent=user_agent,
            details={
                "device_id": normalized_device_id,
                "signature_key_id": normalized_sig_key_id,
                "payload_version": effective_version,
            },
        )
        return {
            "valid": False,
            "code": "UNSUPPORTED_PAYLOAD_VERSION",
            "detail": "Unsupported diagnostics payload version",
            "payload_version": effective_version,
        }

    key = DiagnosticsSigningKey.objects.filter(
        agency_id=agency_id,
        device_id=normalized_device_id,
        signature_key_id=normalized_sig_key_id,
        is_active=True,
    ).first()
    if key is None:
        _log_event(
            actor=actor,
            event_type="diagnostics_signature_verified",
            outcome="denied",
            reason_code="active_key_not_found",
            request_id=request_id,
            source_ip=source_ip,
            user_agent=user_agent,
            details={"device_id": normalized_device_id, "signature_key_id": normalized_sig_key_id},
        )
        return {
            "valid": False,
            "code": "SIGNING_KEY_NOT_FOUND",
            "detail": "Active diagnostics signing key not found",
        }

    try:
        signature_bytes = base64.b64decode(normalized_signature, validate=True)
    except Exception:
        return {
            "valid": False,
            "code": "INVALID_SIGNATURE_ENCODING",
            "detail": "Signature must be base64 encoded",
        }

    canonical_message = canonical_json_dumps(
        {
            "payload_version": effective_version,
            "payload": payload,
        }
    ).encode("utf-8")

    try:
        public_key = serialization.load_pem_public_key(key.public_key.encode("utf-8"))
    except Exception:
        return {
            "valid": False,
            "code": "INVALID_PUBLIC_KEY",
            "detail": "Stored public key is invalid",
        }

    key_algorithm = _diagnostics_algorithm_for_public_key(public_key)
    if key_algorithm is None:
        return {
            "valid": False,
            "code": "UNSUPPORTED_KEY_TYPE",
            "detail": "Unsupported diagnostics signing key type",
        }
    if key_algorithm != effective_algorithm:
        _log_event(
            actor=actor,
            event_type="diagnostics_signature_verified",
            outcome="denied",
            reason_code="algorithm_mismatch",
            request_id=request_id,
            source_ip=source_ip,
            user_agent=user_agent,
            details={
                "device_id": normalized_device_id,
                "signature_key_id": normalized_sig_key_id,
                "algorithm": effective_algorithm,
                "key_algorithm": key_algorithm,
            },
        )
        return {
            "valid": False,
            "code": "ALGORITHM_MISMATCH",
            "detail": "Declared diagnostics signature algorithm does not match key type",
            "algorithm": effective_algorithm,
            "key_algorithm": key_algorithm,
        }

    try:
        if key_algorithm == DIAGNOSTICS_SIGNATURE_ALGORITHM_ED25519:
            public_key.verify(signature_bytes, canonical_message)
        elif key_algorithm == DIAGNOSTICS_SIGNATURE_ALGORITHM_CNG_P256:
            public_key.verify(signature_bytes, canonical_message, ec.ECDSA(hashes.SHA256()))
        else:
            return {
                "valid": False,
                "code": "UNSUPPORTED_KEY_TYPE",
                "detail": "Unsupported diagnostics signing key type",
            }
    except InvalidSignature:
        _log_event(
            actor=actor,
            event_type="diagnostics_signature_verified",
            outcome="denied",
            reason_code="invalid_signature",
            request_id=request_id,
            source_ip=source_ip,
            user_agent=user_agent,
            details={"device_id": normalized_device_id, "signature_key_id": normalized_sig_key_id},
        )
        return {
            "valid": False,
            "code": "INVALID_SIGNATURE",
            "detail": "Diagnostics signature verification failed",
        }

    _log_event(
        actor=actor,
        event_type="diagnostics_signature_verified",
        outcome="success",
        reason_code="signature_valid",
        request_id=request_id,
        source_ip=source_ip,
        user_agent=user_agent,
        details={
            "device_id": normalized_device_id,
            "signature_key_id": normalized_sig_key_id,
            "algorithm": effective_algorithm,
        },
    )
    return {
        "valid": True,
        "code": "SIGNATURE_VALID",
        "detail": "Diagnostics signature verified",
        "device_id": normalized_device_id,
        "signature_key_id": normalized_sig_key_id,
        "payload_version": effective_version,
        "algorithm": effective_algorithm,
    }


__all__ = [
    "issue_enrollment_token",
    "register_signing_key",
    "revoke_signing_key",
    "rotate_signing_key",
    "verify_diagnostics_signature",
]
