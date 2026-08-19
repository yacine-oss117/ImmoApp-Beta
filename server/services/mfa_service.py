"""MFA enrollment and lifecycle service helpers."""

from __future__ import annotations

import os
from typing import Any

from django.utils import timezone

from server.services import auth_events, mfa_totp
from server.services.accounts_ale import apply_user_ale, resolve_user_mfa_secret
from server.services.errors import PermissionDeniedError


def _issuer_name() -> str:
    return os.environ.get("IMMOAPP_TOTP_ISSUER", "ImmoApp").strip() or "ImmoApp"


def get_status(*, actor: object | None) -> dict[str, object]:
    enrolled_at = getattr(actor, "mfa_totp_enrolled_at", None)
    return {
        "totp_enabled": bool(getattr(actor, "mfa_totp_enabled", False)),
        "totp_enrolled_at": (
            enrolled_at.isoformat()
            if isinstance(enrolled_at, object) and hasattr(enrolled_at, "isoformat")
            else None
        ),
        "supported_factors": ["totp"],
    }


def start_totp_enrollment(
    *, actor: Any, source_ip: str | None, user_agent: str | None
) -> dict[str, object]:
    username = str(getattr(actor, "username", "") or "")
    secret = mfa_totp.generate_secret()
    ale_payload = {"mfa_totp_secret": secret}
    apply_user_ale(ale_payload, changed_fields={"mfa_totp_secret"})
    actor.mfa_totp_secret = str(ale_payload.get("mfa_totp_secret") or "")
    actor.mfa_totp_secret_enc = str(ale_payload.get("mfa_totp_secret_enc") or "")
    actor.mfa_totp_enabled = False
    actor.mfa_totp_enrolled_at = None
    actor.save(
        update_fields=[
            "mfa_totp_secret",
            "mfa_totp_secret_enc",
            "mfa_totp_enabled",
            "mfa_totp_enrolled_at",
        ]
    )
    uri = mfa_totp.provisioning_uri(username=username, secret=secret, issuer=_issuer_name())
    auth_events.log_auth_event(
        event_type="mfa_totp_enroll_start",
        outcome="success",
        agency_id=getattr(actor, "agency_id", None),
        user_id=getattr(actor, "id", None),
        identifier=username,
        reason_code="pending_secret_issued",
        source_ip=source_ip,
        user_agent=user_agent,
        fail_silently=True,
    )
    return {"secret": secret, "otpauth_uri": uri}


def confirm_totp_enrollment(
    *, actor: Any, code: str, source_ip: str | None, user_agent: str | None
) -> dict[str, object]:
    secret = resolve_user_mfa_secret(actor)
    if not secret:
        raise PermissionDeniedError("No pending TOTP enrollment. Start enrollment first.")
    if not mfa_totp.verify_code(secret=secret, code=code):
        auth_events.log_auth_event(
            event_type="mfa_totp_enroll_confirm",
            outcome="failure",
            agency_id=getattr(actor, "agency_id", None),
            user_id=getattr(actor, "id", None),
            identifier=str(getattr(actor, "username", "") or ""),
            reason_code="invalid_code",
            source_ip=source_ip,
            user_agent=user_agent,
            fail_silently=True,
        )
        raise PermissionDeniedError("Invalid TOTP code.")
    actor.mfa_totp_enabled = True
    actor.mfa_totp_enrolled_at = timezone.now()
    actor.save(update_fields=["mfa_totp_enabled", "mfa_totp_enrolled_at"])
    auth_events.log_auth_event(
        event_type="mfa_totp_enroll_confirm",
        outcome="success",
        agency_id=getattr(actor, "agency_id", None),
        user_id=getattr(actor, "id", None),
        identifier=str(getattr(actor, "username", "") or ""),
        reason_code="totp_enabled",
        source_ip=source_ip,
        user_agent=user_agent,
        fail_silently=True,
    )
    return {"status": "enabled"}


def disable_totp(
    *, actor: Any, code: str, source_ip: str | None, user_agent: str | None
) -> dict[str, object]:
    secret = resolve_user_mfa_secret(actor)
    if not getattr(actor, "mfa_totp_enabled", False):
        raise PermissionDeniedError("TOTP is not enabled.")
    if not mfa_totp.verify_code(secret=secret, code=code):
        auth_events.log_auth_event(
            event_type="mfa_totp_disable",
            outcome="failure",
            agency_id=getattr(actor, "agency_id", None),
            user_id=getattr(actor, "id", None),
            identifier=str(getattr(actor, "username", "") or ""),
            reason_code="invalid_code",
            source_ip=source_ip,
            user_agent=user_agent,
            fail_silently=True,
        )
        raise PermissionDeniedError("Invalid TOTP code.")
    actor.mfa_totp_enabled = False
    ale_payload = {"mfa_totp_secret": ""}
    apply_user_ale(ale_payload, changed_fields={"mfa_totp_secret"})
    actor.mfa_totp_secret = str(ale_payload.get("mfa_totp_secret") or "")
    actor.mfa_totp_secret_enc = str(ale_payload.get("mfa_totp_secret_enc") or "")
    actor.mfa_totp_enrolled_at = None
    actor.save(
        update_fields=[
            "mfa_totp_enabled",
            "mfa_totp_secret",
            "mfa_totp_secret_enc",
            "mfa_totp_enrolled_at",
        ]
    )
    auth_events.log_auth_event(
        event_type="mfa_totp_disable",
        outcome="success",
        agency_id=getattr(actor, "agency_id", None),
        user_id=getattr(actor, "id", None),
        identifier=str(getattr(actor, "username", "") or ""),
        reason_code="totp_disabled",
        source_ip=source_ip,
        user_agent=user_agent,
        fail_silently=True,
    )
    return {"status": "disabled"}


__all__ = [
    "confirm_totp_enrollment",
    "disable_totp",
    "get_status",
    "start_totp_enrollment",
]
