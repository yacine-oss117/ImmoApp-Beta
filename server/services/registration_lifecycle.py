"""Registration and invite lifecycle compatibility facade."""

from __future__ import annotations

import logging
import sys
from typing import Callable, cast
from uuid import UUID

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.signing import BadSignature, SignatureExpired, TimestampSigner
from django.db import transaction
from django.db.models import Q

from core.data.surface_cache_generation import (
    INVITES_ACTOR_SURFACE,
    INVITES_AGENCY_SURFACE,
    actor_scope_key,
    agency_scope_key,
    read_generation,
)
from server.accounts.models import Agency, RegistrationRequest, UserInvite
from server.pg.uow import get_uow, use_security_context
from server.services import (
    auth_events,
    registration_approval,
    registration_invites,
    registration_tokens,
)
from server.services.accounts_ale import (
    apply_agency_ale,
    apply_registration_request_ale,
    apply_user_ale,
    apply_user_invite_ale,
)
from server.services.cursor_pagination import decode_cursor, encode_cursor, normalize_limit
from server.services.email_sender import send_platform_email
from server.services.email_templates import (
    build_owner_approval_email,
    build_owner_welcome_email,
    build_registration_declined_email,
    build_team_invite_email,
)
from server.services.errors import PermissionDeniedError
from server.services.users_helpers import (
    agency_id_of,
    ensure_manager_is_owner,
    get_user_model_for_service,
    is_owner,
    is_superuser,
    require_manager,
    require_same_agency,
    resolve_manager_id,
    serialize_user,
    validate_manager_assignment,
)

_APPROVAL_SIGNER = TimestampSigner(salt="registration-approval")
logger = logging.getLogger(__name__)
_PUBLIC_BASE_URL_FALLBACK_WARNED = False

# These imports intentionally remain on this module surface because tests and the extracted
# helpers still rely on `registration_lifecycle` as the compatibility seam owner.
_EXTRACTED_COMPAT_DEPS = (
    Agency,
    BadSignature,
    Q,
    RegistrationRequest,
    SignatureExpired,
    UserInvite,
    agency_id_of,
    apply_agency_ale,
    apply_registration_request_ale,
    apply_user_ale,
    apply_user_invite_ale,
    auth_events,
    build_owner_approval_email,
    build_owner_welcome_email,
    build_registration_declined_email,
    build_team_invite_email,
    decode_cursor,
    encode_cursor,
    ensure_manager_is_owner,
    get_user_model,
    get_user_model_for_service,
    is_owner,
    is_superuser,
    normalize_limit,
    require_manager,
    require_same_agency,
    resolve_manager_id,
    send_platform_email,
    serialize_user,
    transaction,
    validate_manager_assignment,
    validate_password,
)


class RegistrationUnavailableError(RuntimeError):
    """Raised when self-registration is disabled."""


class InviteResendCooldownError(RuntimeError):
    """Raised when invite resend cooldown is still active."""

    def __init__(self, *, retry_after_seconds: int) -> None:
        super().__init__("Invite resend cooldown active.")
        self.retry_after_seconds = max(1, int(retry_after_seconds))


class EmailQueueUnavailableError(RuntimeError):
    """Raised when outbound email cannot be queued."""


def _safe_record_and_notify(**kwargs: object) -> None:
    from server.api.notifications import record_and_notify

    notify = cast(Callable[..., object], record_and_notify)

    try:
        notify(**kwargs)
    except Exception:
        logger.warning("Failed to record/broadcast notification", exc_info=True)


def _env_int(name: str, default: int, *, min_v: int, max_v: int) -> int:
    return registration_tokens._env_int(name, default, min_v=min_v, max_v=max_v)


def _approval_token_expiry_days() -> int:
    return registration_tokens._approval_token_expiry_days()


def _activation_expiry_hours() -> int:
    return registration_tokens._activation_expiry_hours()


def _invite_expiry_hours(expires_seconds: int | None = None) -> int:
    return registration_tokens._invite_expiry_hours(expires_seconds)


def _pending_expiry_days() -> int:
    return registration_tokens._pending_expiry_days()


def _invite_resend_cooldown_seconds() -> int:
    return registration_tokens._invite_resend_cooldown_seconds()


def _platform_admin_email() -> str:
    return registration_tokens._platform_admin_email()


def _public_base_url_with_source() -> tuple[str, str]:
    return registration_tokens._public_base_url_with_source()


def _public_base_url() -> str:
    return registration_tokens._public_base_url()


def _code_alphabet() -> str:
    return registration_tokens._code_alphabet()


def _generate_code(*, length: int) -> str:
    return registration_tokens._generate_code(length=length)


def _sha256(text: str) -> str:
    return registration_tokens._sha256(text)


def _verify_code(input_code: str, stored_hash: str) -> bool:
    return registration_tokens._verify_code(input_code, stored_hash)


def _generate_agency_code(name: str) -> str:
    return registration_tokens._generate_agency_code(name)


def _parse_uuid(text: str) -> UUID:
    return registration_tokens._parse_uuid(text)


def _resolve_ale_text(public_value: str, encrypted_value: str) -> str:
    return registration_tokens._resolve_ale_text(public_value, encrypted_value)


def _registration_plain(record: RegistrationRequest, field_name: str) -> str:
    return registration_tokens._registration_plain(record, field_name)


def _invite_name_parts(name: str) -> tuple[str, str]:
    return registration_tokens._invite_name_parts(name)


def _issue_auth_tokens(
    *,
    user: object,
    source_ip: str | None,
    user_agent: str | None,
) -> dict[str, str]:
    return registration_tokens._issue_auth_tokens(
        user=user,
        source_ip=source_ip,
        user_agent=user_agent,
    )


def _require_registration_enabled() -> None:
    if not _platform_admin_email():
        raise RegistrationUnavailableError("Registration is not available at this time.")


def _queue_platform_email_or_raise(
    *, to: str, subject: str, body_text: str, body_html: str
) -> None:
    queued = send_platform_email(
        to=to,
        subject=subject,
        body_text=body_text,
        body_html=body_html,
    )
    if not queued:
        raise EmailQueueUnavailableError("Email queue is unavailable.")


def _ensure_not_existing_owner_email(owner_email: str) -> None:
    User = get_user_model_for_service()
    if User.objects.filter(email__iexact=owner_email).exists():
        raise ValueError("An account with this email already exists.")
    if (
        RegistrationRequest.objects.filter(owner_email__iexact=owner_email)
        .exclude(status=RegistrationRequest.STATUS_EXPIRED)
        .exists()
    ):
        raise ValueError("A registration request for this email already exists.")


def submit_registration(
    *,
    data: dict[str, object],
    source_ip: str | None,
    user_agent: str | None,
    request_id: str | None,
) -> dict[str, object]:
    return registration_approval.submit_registration_impl(
        deps=sys.modules[__name__],
        data=data,
        source_ip=source_ip,
        user_agent=user_agent,
        request_id=request_id,
    )


def _load_registration_for_signed_token(
    *,
    signed_token: str,
    for_update: bool = True,
) -> RegistrationRequest:
    return cast(
        RegistrationRequest,
        registration_approval.load_registration_for_signed_token_impl(
            deps=sys.modules[__name__],
            signed_token=signed_token,
            for_update=for_update,
        ),
    )


def load_registration_for_review(*, signed_token: str) -> RegistrationRequest:
    return cast(
        RegistrationRequest,
        registration_approval.load_registration_for_review_impl(
            deps=sys.modules[__name__],
            signed_token=signed_token,
        ),
    )


def registration_review_details(record: RegistrationRequest) -> dict[str, str]:
    return registration_approval.registration_review_details_impl(
        deps=sys.modules[__name__],
        record=record,
    )


def _finalize_agency_ale_fields(*, agency: Agency, payload: dict[str, object]) -> Agency:
    return cast(
        Agency,
        registration_approval.finalize_agency_ale_fields_impl(
            deps=sys.modules[__name__],
            agency=agency,
            payload=payload,
        ),
    )


def approve_registration_by_token(*, signed_token: str) -> dict[str, object]:
    return registration_approval.approve_registration_by_token_impl(
        deps=sys.modules[__name__],
        signed_token=signed_token,
    )


def blacklist_registration_by_token(*, signed_token: str) -> dict[str, object]:
    return registration_approval.blacklist_registration_by_token_impl(
        deps=sys.modules[__name__],
        signed_token=signed_token,
    )


def activate_owner(
    *,
    email: str,
    activation_code: str,
    password: str,
    source_ip: str | None,
    user_agent: str | None,
    request_id: str | None,
) -> dict[str, object]:
    return registration_approval.activate_owner_impl(
        deps=sys.modules[__name__],
        email=email,
        activation_code=activation_code,
        password=password,
        source_ip=source_ip,
        user_agent=user_agent,
        request_id=request_id,
    )


def _assert_invite_role_constraints(*, role: str, manager_id: int | None) -> None:
    registration_invites.assert_invite_role_constraints_impl(role=role, manager_id=manager_id)


def _invite_user_payload(
    *, invite_name: str, invite_email: str, role: str, manager_id: int | None
) -> dict[str, object]:
    return registration_invites.invite_user_payload_impl(
        deps=sys.modules[__name__],
        invite_name=invite_name,
        invite_email=invite_email,
        role=role,
        manager_id=manager_id,
    )


def create_user_invite(*, actor: object | None, data: dict[str, object]) -> dict[str, object]:
    return registration_invites.create_user_invite_impl(
        deps=sys.modules[__name__],
        actor=actor,
        data=data,
    )


def _load_invite_for_actor(*, actor: object | None, invite_id: str, lock: bool) -> UserInvite:
    return cast(
        UserInvite,
        registration_invites.load_invite_for_actor_impl(
            deps=sys.modules[__name__],
            actor=actor,
            invite_id=invite_id,
            lock=lock,
        ),
    )


def list_pending_invites_page(
    *,
    actor: object | None,
    limit: int | str | None = None,
    cursor: str | None = None,
) -> tuple[list[dict[str, object]], str | None, bool]:
    return registration_invites.list_pending_invites_page_impl(
        deps=sys.modules[__name__],
        actor=actor,
        limit=limit,
        cursor=cursor,
    )


def list_pending_invites(*, actor: object | None) -> list[dict[str, object]]:
    return registration_invites.list_pending_invites_impl(
        deps=sys.modules[__name__],
        actor=actor,
    )


def get_pending_invites_surface_generation(*, actor: object | None) -> int:
    agency_id = agency_id_of(actor)
    if not isinstance(agency_id, int) or agency_id <= 0:
        raise PermissionDeniedError("Agency is required.")
    with use_security_context(agency_id=agency_id, is_superuser=bool(is_superuser(actor))):
        with get_uow().session(is_superuser=bool(getattr(actor, "is_superuser", False))) as session:
            if is_superuser(actor) or is_owner(actor):
                return int(
                    read_generation(
                        session,
                        surface=INVITES_AGENCY_SURFACE,
                        scope_key=agency_scope_key(agency_id),
                        agency_id=agency_id,
                    )
                )
            actor_id = getattr(actor, "id", None)
            if not isinstance(actor_id, int) or actor_id <= 0:
                raise PermissionDeniedError("Actor id is required.")
            return int(
                read_generation(
                    session,
                    surface=INVITES_ACTOR_SURFACE,
                    scope_key=actor_scope_key(actor_id),
                    agency_id=agency_id,
                )
            )


def resend_invite(
    *,
    actor: object | None,
    invite_id: str,
    expires_seconds: int | None = None,
) -> dict[str, object]:
    return registration_invites.resend_invite_impl(
        deps=sys.modules[__name__],
        actor=actor,
        invite_id=invite_id,
        expires_seconds=expires_seconds,
    )


def revoke_invite(*, actor: object | None, invite_id: str) -> dict[str, object]:
    return registration_invites.revoke_invite_impl(
        deps=sys.modules[__name__],
        actor=actor,
        invite_id=invite_id,
    )


def accept_invite(
    *,
    invite_code: str,
    email: str,
    password: str,
    source_ip: str | None,
    user_agent: str | None,
    request_id: str | None,
) -> dict[str, object]:
    return registration_invites.accept_invite_impl(
        deps=sys.modules[__name__],
        invite_code=invite_code,
        email=email,
        password=password,
        source_ip=source_ip,
        user_agent=user_agent,
        request_id=request_id,
    )


def expire_pending_registrations(*, older_than_days: int | None = None) -> int:
    return registration_approval.expire_pending_registrations_impl(
        deps=sys.modules[__name__],
        older_than_days=older_than_days,
    )


def expire_pending_invites() -> int:
    return registration_invites.expire_pending_invites_impl(deps=sys.modules[__name__])


__all__ = [
    "EmailQueueUnavailableError",
    "InviteResendCooldownError",
    "RegistrationUnavailableError",
    "accept_invite",
    "activate_owner",
    "approve_registration_by_token",
    "blacklist_registration_by_token",
    "create_user_invite",
    "expire_pending_invites",
    "get_pending_invites_surface_generation",
    "expire_pending_registrations",
    "list_pending_invites",
    "list_pending_invites_page",
    "load_registration_for_review",
    "registration_review_details",
    "resend_invite",
    "revoke_invite",
    "submit_registration",
]
