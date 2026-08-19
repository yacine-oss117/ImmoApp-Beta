"""Hub DB owner state and one-use Hub Manager authorization grants."""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db.models import Q
from django.utils import timezone

from core.contracts.hub_manager_authorization import authorization_scope
from server.accounts.models import RegistrationRequest

OWNER_ACCOUNT_MISSING = "owner_account_missing"
OWNER_ACTIVATION_PENDING = "owner_activation_pending"
OWNER_ACTIVE = "owner_active"

_GRANT_TTL_SECONDS = 300
_GRANT_KEY_PREFIX = "hub-manager-authorization:grant:"
_CONSUMED_KEY_PREFIX = "hub-manager-authorization:consumed:"


@dataclass(frozen=True)
class HubManagerAccessError(Exception):
    reason_code: str

    def __str__(self) -> str:
        return self.reason_code


def resolve_owner_state() -> dict[str, Any]:
    """Return non-secret first-owner state from the authoritative Hub DB."""

    User = get_user_model()
    platform_admin_configured = bool(
        str(getattr(settings, "IMMOAPP_PLATFORM_ADMIN_EMAIL", "") or "").strip()
    )
    active_owner_admin_count = (
        User.objects.filter(is_active=True)
        .filter(
            Q(is_superuser=True)
            | Q(role=User.ROLE_MANAGER, is_owner=True)
            | Q(role=User.ROLE_MANAGER, can_hard_delete=True)
        )
        .count()
    )
    pending_registration_count = RegistrationRequest.objects.filter(
        status=RegistrationRequest.STATUS_PENDING
    ).count()
    approved_registrations = RegistrationRequest.objects.filter(
        status=RegistrationRequest.STATUS_APPROVED
    )
    approved_registration_count = approved_registrations.count()
    activatable_owner_emails = approved_registrations.filter(
        activation_code_hash__gt="",
        activation_code_expires_at__gt=timezone.now(),
    ).values_list("owner_email", flat=True)
    inactive_owner_count = User.objects.filter(
        is_active=False,
        role=User.ROLE_MANAGER,
        is_owner=True,
        email__in=activatable_owner_emails,
    ).count()
    return _owner_state_from_counts(
        platform_admin_configured=platform_admin_configured,
        active_owner_admin_count=active_owner_admin_count,
        pending_registration_count=pending_registration_count,
        approved_registration_count=approved_registration_count,
        inactive_owner_count=inactive_owner_count,
    )


def _owner_state_from_counts(
    *,
    platform_admin_configured: bool,
    active_owner_admin_count: int,
    pending_registration_count: int,
    approved_registration_count: int,
    inactive_owner_count: int,
) -> dict[str, Any]:
    if active_owner_admin_count:
        return _owner_state_payload(
            state=OWNER_ACTIVE,
            setup_available=platform_admin_configured,
            activation_available=False,
            reason_code="active_owner_admin_exists",
            active_owner_admin_count=active_owner_admin_count,
        )
    if approved_registration_count or inactive_owner_count:
        return _owner_state_payload(
            state=OWNER_ACTIVATION_PENDING,
            setup_available=platform_admin_configured,
            activation_available=inactive_owner_count > 0,
            reason_code=(
                "approved_inactive_owner_exists"
                if inactive_owner_count
                else "registration_approved_without_inactive_owner"
            ),
            pending_registration_count=pending_registration_count,
            approved_registration_count=approved_registration_count,
            inactive_owner_count=inactive_owner_count,
        )
    if pending_registration_count:
        return _owner_state_payload(
            state=OWNER_ACTIVATION_PENDING,
            setup_available=platform_admin_configured,
            activation_available=False,
            reason_code="registration_pending_platform_approval",
            pending_registration_count=pending_registration_count,
        )
    return _owner_state_payload(
        state=OWNER_ACCOUNT_MISSING,
        setup_available=platform_admin_configured,
        activation_available=False,
        reason_code=(
            "owner_account_missing" if platform_admin_configured else "platform_admin_email_missing"
        ),
    )


def issue_authorization(
    *,
    actor: Any,
    action: str,
    hub_binding: dict[str, str],
) -> dict[str, Any]:
    """Issue a short-lived grant after normal Hub JWT authentication."""

    scope = authorization_scope(action)
    authorized_role = _authorized_role(actor)
    now = datetime.now(UTC).replace(microsecond=0)
    expires = now + timedelta(seconds=_GRANT_TTL_SECONDS)
    nonce = secrets.token_urlsafe(32)
    payload: dict[str, Any] = {
        "kind": "immoapp_hub_owner_authorization_evidence",
        "schema_version": 3,
        "created_at_utc": now.isoformat(),
        "expires_at_utc": expires.isoformat(),
        "proof_result": "GO",
        "owner_authorization_status": "GO",
        "reason_code": "hub_owner_authorization_verified",
        "action": action,
        "authorization_scope": scope,
        "source": "hub_db",
        "evidence_nonce": nonce,
        "actor_user_id": int(actor.pk),
        "actor_role": str(getattr(actor, "role", "") or ""),
        "actor_is_owner": bool(getattr(actor, "is_owner", False)),
        "actor_can_hard_delete": bool(getattr(actor, "can_hard_delete", False)),
        "actor_is_superuser": bool(getattr(actor, "is_superuser", False)),
        "authorized_role": authorized_role,
        "agency_id": int(actor.agency_id) if getattr(actor, "agency_id", None) else None,
        "hub_id": hub_binding["hub_id"],
        "hub_display_name": hub_binding["hub_display_name"],
        "hub_identity_sha256": hub_binding["hub_identity_sha256"],
        "hub_state_manifest_sha256": hub_binding["hub_state_manifest_sha256"],
        "hub_state_install_lineage": hub_binding["hub_state_install_lineage"],
        "plaintext_password_written": False,
        "session_token_written": False,
        "agency_install_status": "NO_GO",
        "public_beta_status": "NO_GO",
    }
    try:
        stored = cache.add(_grant_key(nonce), payload, timeout=_GRANT_TTL_SECONDS)
    except Exception as exc:
        raise HubManagerAccessError("hub_owner_authorization_store_unavailable") from exc
    if not stored:
        raise HubManagerAccessError("hub_owner_authorization_store_collision")
    return payload


def consume_authorization(*, nonce: str, action: str, hub_id: str) -> dict[str, Any]:
    """Atomically consume a grant and re-check active owner/admin DB truth."""

    grant_key = _grant_key(nonce)
    try:
        payload = cache.get(grant_key)
    except Exception as exc:
        raise HubManagerAccessError("hub_owner_authorization_store_unavailable") from exc
    if not isinstance(payload, dict):
        raise HubManagerAccessError("hub_owner_authorization_missing_or_expired")
    if payload.get("action") != action:
        raise HubManagerAccessError("hub_owner_authorization_action_invalid")
    if payload.get("hub_id") != hub_id:
        raise HubManagerAccessError("hub_owner_authorization_hub_mismatch")
    if payload.get("authorization_scope") != authorization_scope(action):
        raise HubManagerAccessError("hub_owner_authorization_scope_invalid")

    User = get_user_model()
    actor = User.objects.filter(pk=payload.get("actor_user_id")).first()
    authorized_role = _authorized_role(actor)
    if authorized_role != payload.get("authorized_role"):
        raise HubManagerAccessError("hub_owner_authorization_role_changed")

    consumed_key = _consumed_key(nonce)
    try:
        first_consumer = cache.add(consumed_key, True, timeout=_GRANT_TTL_SECONDS)
        if not first_consumer:
            raise HubManagerAccessError("hub_owner_authorization_already_consumed")
        cache.delete(grant_key)
    except HubManagerAccessError:
        raise
    except Exception as exc:
        raise HubManagerAccessError("hub_owner_authorization_store_unavailable") from exc

    return {
        key: payload[key]
        for key in (
            "kind",
            "schema_version",
            "created_at_utc",
            "expires_at_utc",
            "proof_result",
            "owner_authorization_status",
            "reason_code",
            "action",
            "authorization_scope",
            "source",
            "actor_user_id",
            "actor_role",
            "actor_is_owner",
            "actor_can_hard_delete",
            "actor_is_superuser",
            "authorized_role",
            "agency_id",
            "hub_id",
            "hub_display_name",
            "hub_identity_sha256",
            "hub_state_manifest_sha256",
            "hub_state_install_lineage",
        )
    }


def _authorized_role(user: Any) -> str:
    if user is None or not bool(getattr(user, "is_active", False)):
        raise HubManagerAccessError("hub_owner_authorization_user_inactive")
    role = str(getattr(user, "role", "") or "")
    if role == "manager" and bool(getattr(user, "is_owner", False)):
        return "agency_owner"
    if bool(getattr(user, "is_superuser", False)) or (
        role == "manager" and bool(getattr(user, "can_hard_delete", False))
    ):
        return "agency_admin"
    raise HubManagerAccessError("hub_owner_authorization_role_not_allowed")


def _grant_key(nonce: str) -> str:
    return _GRANT_KEY_PREFIX + hashlib.sha256(nonce.encode("utf-8")).hexdigest()


def _consumed_key(nonce: str) -> str:
    return _CONSUMED_KEY_PREFIX + hashlib.sha256(nonce.encode("utf-8")).hexdigest()


def _owner_state_payload(
    *,
    state: str,
    setup_available: bool,
    activation_available: bool,
    reason_code: str,
    active_owner_admin_count: int = 0,
    pending_registration_count: int = 0,
    approved_registration_count: int = 0,
    inactive_owner_count: int = 0,
) -> dict[str, Any]:
    return {
        "kind": "immoapp_hub_manager_owner_state",
        "schema_version": 1,
        "state": state,
        "setup_available": setup_available,
        "activation_available": activation_available,
        "reason_code": reason_code,
        "active_owner_admin_count": active_owner_admin_count,
        "pending_registration_count": pending_registration_count,
        "approved_registration_count": approved_registration_count,
        "inactive_owner_count": inactive_owner_count,
        "source": "hub_db",
    }


__all__ = [
    "HubManagerAccessError",
    "consume_authorization",
    "issue_authorization",
    "resolve_owner_state",
]
