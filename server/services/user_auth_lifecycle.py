"""Account activation, password reset, and invitation lifecycle services."""

from __future__ import annotations

import os
from typing import Any, cast
from uuid import UUID

from django.conf import settings as _dj_settings
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils import timezone

from server.accounts.models import UserActionToken
from server.services import auth_events
from server.services.auth_token_actions import (
    _consume_token_or_raise,
    _invite_ttl_seconds,
    _issue_token_record,
    _password_reset_ttl_seconds,
)
from server.services.errors import NotFoundError, PermissionDeniedError

from .users_helpers import (
    agency_id_of,
    ensure_manager_owns_agent,
    ensure_manager_target_role,
    ensure_role_allowed,
    get_user_model_for_service,
    is_owner,
    is_superuser,
    normalize_role,
    require_manager,
    require_same_agency,
    resolve_manager_id,
    serialize_user,
    validate_manager_assignment,
)

_PASSWORD_RESET_PURPOSE = UserActionToken.PURPOSE_PASSWORD_RESET
_INVITE_ACTIVATION_PURPOSE = UserActionToken.PURPOSE_INVITE_ACTIVATION
_DEV_TOKEN_ECHO = getattr(_dj_settings, "DEBUG", False) and os.environ.get(
    "IMMOAPP_AUTH_DEV_TOKEN_ECHO", "0"
).strip() in {"1", "true", "yes"}


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, (str, bytes, bytearray)):
        text = value.strip() if isinstance(value, str) else value
        if not text:
            return None
        return int(value)
    return None


def _resolve_identifier_user(identifier: str) -> object | None:
    User = get_user_model_for_service()
    value = identifier.strip()
    if not value:
        return None
    user = User.objects.filter(username=value).first()
    if user is not None:
        return cast(object, user)
    if "@" in value:
        return cast(object | None, User.objects.filter(email__iexact=value).first())
    return None


def _actor_user_id(actor: object | None) -> int | None:
    value = getattr(actor, "id", None) if actor is not None else None
    return int(value) if value is not None else None


def _safe_user_identifier(user: object | None) -> str | None:
    if user is None:
        return None
    username = getattr(user, "username", None)
    if isinstance(username, str) and username.strip():
        return username.strip()
    email = getattr(user, "email", None)
    if isinstance(email, str) and email.strip():
        return email.strip()
    return None


def request_password_reset(
    *,
    identifier: str,
    request_id: str | None = None,
    source_ip: str | None = None,
    user_agent: str | None = None,
) -> dict[str, object]:
    """Request a password reset without account-enumeration leakage."""
    value = identifier.strip()
    user = _resolve_identifier_user(value)
    if user is None or not getattr(user, "is_active", False):
        auth_events.log_auth_event(
            event_type="password_reset_request",
            outcome="accepted",
            identifier=value if value else None,
            reason_code="non_disclosing_accepted",
            source_ip=source_ip,
            user_agent=user_agent,
            request_id=request_id,
            fail_silently=True,
        )
        return {
            "status": "accepted",
            "message": "If the account exists, reset instructions have been generated.",
        }

    try:
        with transaction.atomic():
            UserActionToken.objects.filter(
                user=user,
                purpose=_PASSWORD_RESET_PURPOSE,
                consumed_at__isnull=True,
            ).update(
                consumed_at=timezone.now(),
                metadata={"superseded": True},
            )
            token, raw_token = _issue_token_record(
                purpose=_PASSWORD_RESET_PURPOSE,
                user=user,
                issued_by=None,
                ttl_seconds=_password_reset_ttl_seconds(),
                metadata={"flow": "password_reset"},
                agency_id_of_fn=agency_id_of,
            )
    except Exception:
        auth_events.log_auth_event(
            event_type="password_reset_request",
            outcome="failure",
            user_id=_actor_user_id(user),
            agency_id=agency_id_of(user),
            identifier=_safe_user_identifier(user),
            reason_code="issue_failed",
            source_ip=source_ip,
            user_agent=user_agent,
            request_id=request_id,
            fail_silently=True,
        )
        raise

    auth_events.log_auth_event(
        event_type="password_reset_request",
        outcome="accepted",
        user_id=_actor_user_id(user),
        agency_id=agency_id_of(user),
        identifier=_safe_user_identifier(user),
        reason_code="token_issued",
        source_ip=source_ip,
        user_agent=user_agent,
        request_id=request_id,
        details={"token_id": str(token.token_id)},
        fail_silently=True,
    )
    payload: dict[str, object] = {
        "status": "accepted",
        "message": "If the account exists, reset instructions have been generated.",
    }
    if _DEV_TOKEN_ECHO:
        payload["reset_token"] = raw_token
        payload["token_id"] = str(token.token_id)
        payload["expires_at"] = token.expires_at.isoformat()
    return payload


def reset_password_with_token(
    *,
    token: str,
    new_password: str,
    request_id: str | None = None,
    source_ip: str | None = None,
    user_agent: str | None = None,
) -> dict[str, object]:
    with transaction.atomic():
        record = _consume_token_or_raise(
            token=token,
            purpose=_PASSWORD_RESET_PURPOSE,
            reason_prefix="password_reset_complete",
            request_id=request_id,
            source_ip=source_ip,
            user_agent=user_agent,
            auth_events_module=auth_events,
            safe_user_identifier_fn=_safe_user_identifier,
        )
        user = record.user
        try:
            validate_password(new_password, user=user)
        except DjangoValidationError as exc:
            raise ValueError("; ".join(exc.messages)) from exc
        user.set_password(new_password)
        user.save(update_fields=["password"])
        record.consumed_at = timezone.now()
        record.save(update_fields=["consumed_at"])
    auth_events.log_auth_event(
        event_type="password_reset_complete",
        outcome="success",
        user_id=int(user.id),
        agency_id=agency_id_of(user),
        identifier=_safe_user_identifier(user),
        reason_code="password_updated",
        source_ip=source_ip,
        user_agent=user_agent,
        request_id=request_id,
        details={"token_id": str(record.token_id)},
        fail_silently=True,
    )
    return {"status": "password_reset"}


def activate_account_with_token(
    *,
    token: str,
    password: str,
    request_id: str | None = None,
    source_ip: str | None = None,
    user_agent: str | None = None,
) -> dict[str, object]:
    with transaction.atomic():
        record = _consume_token_or_raise(
            token=token,
            purpose=_INVITE_ACTIVATION_PURPOSE,
            reason_prefix="account_activation",
            request_id=request_id,
            source_ip=source_ip,
            user_agent=user_agent,
            auth_events_module=auth_events,
            safe_user_identifier_fn=_safe_user_identifier,
        )
        user = record.user
        try:
            validate_password(password, user=user)
        except DjangoValidationError as exc:
            raise ValueError("; ".join(exc.messages)) from exc
        user.set_password(password)
        user.is_active = True
        user.full_clean()
        user.save(update_fields=["password", "is_active"])
        record.consumed_at = timezone.now()
        record.save(update_fields=["consumed_at"])
    auth_events.log_auth_event(
        event_type="account_activation",
        outcome="success",
        user_id=int(user.id),
        agency_id=agency_id_of(user),
        identifier=_safe_user_identifier(user),
        reason_code="account_activated",
        source_ip=source_ip,
        user_agent=user_agent,
        request_id=request_id,
        details={"token_id": str(record.token_id)},
        fail_silently=True,
    )
    return {"status": "account_activated"}


def create_user_invite(
    *,
    actor: object | None,
    data: dict[str, object],
) -> dict[str, object]:
    require_manager(actor)
    User = get_user_model_for_service()
    role = normalize_role(str(data.get("role") or ""))
    ensure_role_allowed(actor, role)

    actor_agency_id = agency_id_of(actor)
    agency_id = _optional_int(data.get("agency_id"))
    if not is_superuser(actor):
        agency_id = actor_agency_id
    if agency_id is None:
        raise PermissionDeniedError("Agency is required.")

    manager_id = _optional_int(data.get("manager_id"))
    if role == "manager":
        manager_id = None
    else:
        manager_id = resolve_manager_id(
            actor=actor,
            desired_manager_id=manager_id,
            agency_id=agency_id,
        )
        if manager_id is None:
            raise PermissionDeniedError("Agent must have a manager.")
        manager_id = validate_manager_assignment(manager_id, agency_id=agency_id)

    payload: dict[str, Any] = {
        "username": str(data.get("username") or ""),
        "email": str(data.get("email") or ""),
        "first_name": str(data.get("first_name") or ""),
        "last_name": str(data.get("last_name") or ""),
        "role": role,
        "is_owner": bool(data.get("is_owner", False)),
        "is_active": False,
        "can_import": bool(data.get("can_import", False)),
        "can_hard_delete": bool(data.get("can_hard_delete", False)),
        "agency_id": agency_id,
        "manager_id": manager_id,
    }

    expires_seconds = _optional_int(data.get("expires_seconds"))

    with transaction.atomic():
        user = User(**payload)
        user.set_unusable_password()
        if user.role == "agent" and user.can_import:
            user.import_granted_by = actor if actor else None
        if user.role == "manager":
            user.import_granted_by = None
        user.full_clean()
        user.save()
        token, raw_token = _issue_token_record(
            purpose=_INVITE_ACTIVATION_PURPOSE,
            user=user,
            issued_by=actor,
            ttl_seconds=_invite_ttl_seconds(expires_seconds),
            metadata={"flow": "invite_activation"},
            agency_id_of_fn=agency_id_of,
        )

    auth_events.log_auth_event(
        event_type="user_invite_created",
        outcome="success",
        user_id=_actor_user_id(actor),
        agency_id=agency_id_of(actor),
        identifier=_safe_user_identifier(actor),
        reason_code="invite_created",
        details={"invite_id": str(token.token_id), "target_user_id": int(user.id)},
        fail_silently=True,
    )

    invite_payload: dict[str, object] = {
        "invite_id": str(token.token_id),
        "expires_at": token.expires_at.isoformat(),
        "user": serialize_user(user),
    }
    if _DEV_TOKEN_ECHO:
        invite_payload["activation_token"] = raw_token
    return invite_payload


def _parse_invite_id(invite_id: str) -> UUID:
    try:
        return UUID(str(invite_id))
    except (TypeError, ValueError) as exc:
        raise ValueError("invite_id must be a valid UUID.") from exc


def _assert_can_manage_invite_target(*, actor: object | None, target_user: object) -> None:
    require_same_agency(actor, target_user)
    if is_superuser(actor) or is_owner(actor):
        return
    ensure_manager_target_role(actor, target_user)
    ensure_manager_owns_agent(actor, target_user)


def list_pending_invites(*, actor: object | None) -> list[dict[str, object]]:
    require_manager(actor)
    now = timezone.now()
    qs = (
        UserActionToken.objects.select_related("user")
        .filter(
            purpose=_INVITE_ACTIVATION_PURPOSE,
            consumed_at__isnull=True,
            expires_at__gt=now,
            user__is_active=False,
        )
        .order_by("expires_at", "id")
    )
    if not is_superuser(actor):
        actor_agency = agency_id_of(actor)
        qs = qs.filter(agency_id=actor_agency)
        if not is_owner(actor):
            actor_id = _actor_user_id(actor)
            qs = qs.filter(user__manager_id=actor_id)

    items: list[dict[str, object]] = []
    for row in qs[:500]:
        user = row.user
        items.append(
            {
                "invite_id": str(row.token_id),
                "expires_at": row.expires_at.isoformat(),
                "created_at": row.created_at.isoformat(),
                "user": serialize_user(user),
            }
        )
    return items


def resend_invite(
    *,
    actor: object | None,
    invite_id: str,
    expires_seconds: int | None = None,
) -> dict[str, object]:
    require_manager(actor)
    token_uuid = _parse_invite_id(invite_id)
    with transaction.atomic():
        record = (
            UserActionToken.objects.select_for_update()
            .select_related("user")
            .filter(token_id=token_uuid, purpose=_INVITE_ACTIVATION_PURPOSE)
            .first()
        )
        if record is None:
            raise NotFoundError("Invite not found.")
        _assert_can_manage_invite_target(actor=actor, target_user=record.user)
        if record.user.is_active:
            raise ValueError("User is already active.")
        if record.consumed_at is None:
            record.consumed_at = timezone.now()
            record.metadata = {"superseded": True}
            record.save(update_fields=["consumed_at", "metadata"])
        new_token, raw_token = _issue_token_record(
            purpose=_INVITE_ACTIVATION_PURPOSE,
            user=record.user,
            issued_by=actor,
            ttl_seconds=_invite_ttl_seconds(expires_seconds),
            metadata={"flow": "invite_activation", "resend": True},
            agency_id_of_fn=agency_id_of,
        )

    auth_events.log_auth_event(
        event_type="user_invite_resent",
        outcome="success",
        user_id=_actor_user_id(actor),
        agency_id=agency_id_of(actor),
        identifier=_safe_user_identifier(actor),
        reason_code="invite_resent",
        details={"invite_id": str(new_token.token_id), "target_user_id": int(record.user.id)},
        fail_silently=True,
    )
    payload: dict[str, object] = {
        "invite_id": str(new_token.token_id),
        "expires_at": new_token.expires_at.isoformat(),
        "user": serialize_user(record.user),
    }
    if _DEV_TOKEN_ECHO:
        payload["activation_token"] = raw_token
    return payload


def revoke_invite(*, actor: object | None, invite_id: str) -> dict[str, object]:
    require_manager(actor)
    token_uuid = _parse_invite_id(invite_id)
    with transaction.atomic():
        record = (
            UserActionToken.objects.select_for_update()
            .select_related("user")
            .filter(token_id=token_uuid, purpose=_INVITE_ACTIVATION_PURPOSE)
            .first()
        )
        if record is None:
            raise NotFoundError("Invite not found.")
        _assert_can_manage_invite_target(actor=actor, target_user=record.user)
        if record.consumed_at is None:
            record.consumed_at = timezone.now()
            record.metadata = {"revoked": True}
            record.save(update_fields=["consumed_at", "metadata"])

    auth_events.log_auth_event(
        event_type="user_invite_revoked",
        outcome="success",
        user_id=_actor_user_id(actor),
        agency_id=agency_id_of(actor),
        identifier=_safe_user_identifier(actor),
        reason_code="invite_revoked",
        details={"invite_id": str(record.token_id), "target_user_id": int(record.user.id)},
        fail_silently=True,
    )
    return {"status": "revoked", "invite_id": str(record.token_id)}


__all__ = [
    "activate_account_with_token",
    "create_user_invite",
    "list_pending_invites",
    "request_password_reset",
    "resend_invite",
    "reset_password_with_token",
    "revoke_invite",
]
