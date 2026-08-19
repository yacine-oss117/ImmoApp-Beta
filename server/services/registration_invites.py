"""Registration-owned team invite workflow implementations."""

from __future__ import annotations

from datetime import UTC, timedelta
from typing import Any

from django.utils import timezone
from django.utils.dateparse import parse_datetime

from core.data.surface_cache_generation import (
    INVITES_ACTOR_SURFACE,
    INVITES_AGENCY_SURFACE,
    USERS_SURFACE,
    actor_scope_key,
    agency_scope_key,
)
from server.services.errors import NotFoundError, PermissionDeniedError
from server.services.surface_cache_generations import bump_generation_in_atomic


def _bump_invite_generations_in_atomic(
    *,
    agency_id: int | None,
    invited_by_id: int | None,
    manager_id: int | None,
) -> None:
    if isinstance(agency_id, int) and agency_id > 0:
        bump_generation_in_atomic(
            surface=INVITES_AGENCY_SURFACE,
            scope_key=agency_scope_key(agency_id),
            agency_id=agency_id,
        )
        actor_ids = {
            int(actor_id)
            for actor_id in (invited_by_id, manager_id)
            if isinstance(actor_id, int) and actor_id > 0
        }
        for actor_id in actor_ids:
            bump_generation_in_atomic(
                surface=INVITES_ACTOR_SURFACE,
                scope_key=actor_scope_key(actor_id),
                agency_id=agency_id,
            )


def _bump_users_generation_in_atomic(*, agency_id: int | None) -> None:
    if isinstance(agency_id, int) and agency_id > 0:
        bump_generation_in_atomic(
            surface=USERS_SURFACE,
            scope_key=agency_scope_key(agency_id),
            agency_id=agency_id,
        )


def assert_invite_role_constraints_impl(*, role: str, manager_id: int | None) -> None:
    if role == "agent" and manager_id is None:
        raise ValueError("manager_id is required for agent invites.")
    if role == "manager" and manager_id is not None:
        raise ValueError("manager_id must be null for manager invites.")
    if role not in {"agent", "manager"}:
        raise ValueError("role must be agent or manager.")


def invite_user_payload_impl(
    *,
    deps: Any,
    invite_name: str,
    invite_email: str,
    role: str,
    manager_id: int | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "invite_name": invite_name.strip(),
        "invite_email": invite_email.strip().lower(),
        "role": role,
        "manager_id": manager_id,
    }
    deps.apply_user_invite_ale(payload, changed_fields={"invite_name"})
    return payload


def create_user_invite_impl(
    *, deps: Any, actor: object | None, data: dict[str, object]
) -> dict[str, object]:
    deps.require_manager(actor)
    deps.ensure_manager_is_owner(actor, field="invite_create")
    if bool(data.get("is_owner")):
        raise ValueError("Invites cannot grant owner access.")
    role = str(data.get("role") or "").strip().lower()
    manager_id_raw = data.get("manager_id")
    manager_id = int(manager_id_raw) if isinstance(manager_id_raw, int) else None
    if manager_id_raw is not None and not isinstance(manager_id_raw, int):
        raise ValueError("manager_id must be an integer.")

    agency_id = deps.agency_id_of(actor)
    if agency_id is None:
        raise PermissionDeniedError("Actor agency is required.")

    if role == "agent":
        manager_id = deps.resolve_manager_id(
            actor=actor,
            desired_manager_id=manager_id,
            agency_id=agency_id,
        )
        if manager_id is None:
            raise ValueError("manager_id is required for agent invites.")
        manager_id = deps.validate_manager_assignment(manager_id, agency_id=agency_id)
    deps._assert_invite_role_constraints(role=role, manager_id=manager_id)

    invite_email = str(data.get("email") or "").strip().lower()
    if not invite_email:
        raise ValueError("email is required.")
    User = deps.get_user_model_for_service()
    if User.objects.filter(email__iexact=invite_email).exists():
        raise ValueError("A user with this email already exists.")

    invite_name = str(data.get("invite_name") or "").strip()
    if not invite_name:
        first_name = str(data.get("first_name") or "").strip()
        last_name = str(data.get("last_name") or "").strip()
        invite_name = f"{first_name} {last_name}".strip() or str(data.get("username") or "").strip()
    if not invite_name:
        raise ValueError("invite_name is required.")

    code = deps._generate_code(length=6)
    code_hash = deps._sha256(code)
    now = timezone.now()
    expires_seconds_raw = data.get("expires_seconds")
    expires_seconds = int(expires_seconds_raw) if isinstance(expires_seconds_raw, int) else None
    expires_at = now + timedelta(hours=deps._invite_expiry_hours(expires_seconds))
    invite_payload = deps._invite_user_payload(
        invite_name=invite_name,
        invite_email=invite_email,
        role=role,
        manager_id=manager_id,
    )
    with deps.transaction.atomic():
        invite = deps.UserInvite.objects.create(
            agency_id=agency_id,
            invited_by_id=getattr(actor, "id", None),
            invite_code_hash=code_hash,
            status=deps.UserInvite.STATUS_PENDING,
            expires_at=expires_at,
            last_sent_at=now,
            **invite_payload,
        )
        inviter_name = str(getattr(actor, "username", "") or "")
        agency_name = (
            deps.Agency.objects.filter(id=agency_id).values_list("display_name", flat=True).first()
            or "ImmoApp"
        )
        subject, body_text, body_html = deps.build_team_invite_email(
            agency_name=str(agency_name),
            inviter_name=inviter_name,
            invitee_name=invite_name,
            invite_code=code,
        )
        deps._queue_platform_email_or_raise(
            to=invite_email,
            subject=subject,
            body_text=body_text,
            body_html=body_html,
        )
        _bump_invite_generations_in_atomic(
            agency_id=agency_id,
            invited_by_id=getattr(actor, "id", None),
            manager_id=manager_id,
        )

    return {
        "status": "sent",
        "invite_id": str(invite.id),
        "invite_code": code,
        "invite_email": invite_email,
        "expires_at": invite.expires_at.isoformat(),
        "message": f"Invitation sent to {invite_email}.",
        "delivery_status": "queued",
        "delivery_detail": "Email queued for delivery.",
    }


def load_invite_for_actor_impl(
    *, deps: Any, actor: object | None, invite_id: str, lock: bool
) -> Any:
    deps.require_manager(actor)
    invite_uuid = deps._parse_uuid(invite_id)
    qs = deps.UserInvite.objects
    if lock:
        qs = qs.select_for_update()
    invite = qs.filter(id=invite_uuid).first()
    if invite is None:
        raise NotFoundError("Invite not found.")
    deps.require_same_agency(actor, invite)
    if not deps.is_superuser(actor) and not deps.is_owner(actor):
        manager_id = getattr(actor, "id", None)
        if invite.manager_id != manager_id and invite.invited_by_id != manager_id:
            raise PermissionDeniedError("Forbidden invite scope.")
    return invite


def list_pending_invites_page_impl(
    *,
    deps: Any,
    actor: object | None,
    limit: int | str | None = None,
    cursor: str | None = None,
) -> tuple[list[dict[str, object]], str | None, bool]:
    deps.require_manager(actor)
    agency_id = deps.agency_id_of(actor)
    if agency_id is None:
        return [], None, False
    normalized_limit = deps.normalize_limit(limit, default=50, minimum=1, maximum=200)
    now = timezone.now()
    qs = deps.UserInvite.objects.filter(
        agency_id=agency_id,
        status=deps.UserInvite.STATUS_PENDING,
        expires_at__gt=now,
    ).order_by("-created_at", "-id")
    if not deps.is_superuser(actor) and not deps.is_owner(actor):
        actor_id = getattr(actor, "id", None)
        qs = qs.filter(deps.Q(manager_id=actor_id) | deps.Q(invited_by_id=actor_id))
    cursor_data = deps.decode_cursor(cursor)
    if cursor_data:
        raw_created_at = str(cursor_data.get("created_at") or "").strip()
        raw_invite_id = str(cursor_data.get("invite_id") or "").strip()
        created_at = parse_datetime(raw_created_at)
        invite_uuid = deps._parse_uuid(raw_invite_id) if raw_invite_id else None
        if created_at is None or invite_uuid is None:
            raise ValueError("Invalid cursor.")
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)
        qs = qs.filter(
            deps.Q(created_at__lt=created_at)
            | (deps.Q(created_at=created_at) & deps.Q(id__lt=invite_uuid))
        )

    items: list[dict[str, object]] = []
    invites = list(qs[: normalized_limit + 1])
    has_more = len(invites) > normalized_limit
    page = invites[:normalized_limit]
    for invite in page:
        items.append(
            {
                "invite_id": str(invite.id),
                "invite_email": str(invite.invite_email),
                "role": str(invite.role),
                "manager_id": invite.manager_id,
                "status": str(invite.status),
                "expires_at": invite.expires_at.isoformat(),
                "created_at": invite.created_at.isoformat(),
                "last_sent_at": invite.last_sent_at.isoformat() if invite.last_sent_at else None,
                "resend_count": int(invite.resend_count or 0),
                "invite_name": deps._resolve_ale_text(invite.invite_name, invite.invite_name_enc),
            }
        )
    next_cursor = None
    if has_more and page:
        last_row = page[-1]
        next_cursor = deps.encode_cursor(
            {
                "created_at": last_row.created_at.isoformat(),
                "invite_id": str(last_row.id),
            }
        )
    return items, next_cursor, has_more


def list_pending_invites_impl(*, deps: Any, actor: object | None) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    cursor: str | None = None
    while True:
        page, next_cursor, has_more = deps.list_pending_invites_page(
            actor=actor,
            limit=200,
            cursor=cursor,
        )
        items.extend(page)
        if not has_more or not next_cursor:
            break
        cursor = next_cursor
    return items


def resend_invite_impl(
    *,
    deps: Any,
    actor: object | None,
    invite_id: str,
    expires_seconds: int | None = None,
) -> dict[str, object]:
    cooldown_seconds = deps._invite_resend_cooldown_seconds()
    now = timezone.now()
    inviter_name = str(getattr(actor, "username", "") or "")
    with deps.transaction.atomic():
        invite = deps._load_invite_for_actor(actor=actor, invite_id=invite_id, lock=True)
        if invite.status != deps.UserInvite.STATUS_PENDING:
            raise ValueError("Invite is not pending.")
        if invite.expires_at <= now:
            invite.status = deps.UserInvite.STATUS_EXPIRED
            invite.save(update_fields=["status"])
            raise ValueError("Invite has expired.")
        if invite.last_sent_at:
            next_allowed = invite.last_sent_at + timedelta(seconds=cooldown_seconds)
            if now < next_allowed:
                retry_after = int((next_allowed - now).total_seconds())
                raise deps.InviteResendCooldownError(retry_after_seconds=retry_after)
        code = deps._generate_code(length=6)
        invite.invite_code_hash = deps._sha256(code)
        invite.expires_at = now + timedelta(hours=deps._invite_expiry_hours(expires_seconds))
        invite.last_sent_at = now
        invite.resend_count = int(invite.resend_count or 0) + 1
        invite.save(
            update_fields=[
                "invite_code_hash",
                "expires_at",
                "last_sent_at",
                "resend_count",
            ]
        )
        agency_name = str(getattr(invite.agency, "display_name", "") or "ImmoApp")
        invite_name = (
            deps._resolve_ale_text(invite.invite_name, invite.invite_name_enc)
            or invite.invite_email
        )
        subject, body_text, body_html = deps.build_team_invite_email(
            agency_name=agency_name,
            inviter_name=inviter_name,
            invitee_name=invite_name,
            invite_code=code,
        )
        deps._queue_platform_email_or_raise(
            to=str(invite.invite_email),
            subject=subject,
            body_text=body_text,
            body_html=body_html,
        )
        _bump_invite_generations_in_atomic(
            agency_id=invite.agency_id,
            invited_by_id=invite.invited_by_id,
            manager_id=invite.manager_id,
        )
    return {
        "status": "sent",
        "invite_id": str(invite.id),
        "invite_code": code,
        "invite_email": str(invite.invite_email),
        "expires_at": invite.expires_at.isoformat(),
        "message": f"Invitation sent to {invite.invite_email}.",
        "delivery_status": "queued",
        "delivery_detail": "Email queued for delivery.",
    }


def revoke_invite_impl(*, deps: Any, actor: object | None, invite_id: str) -> dict[str, object]:
    with deps.transaction.atomic():
        invite = deps._load_invite_for_actor(actor=actor, invite_id=invite_id, lock=True)
        if invite.status == deps.UserInvite.STATUS_PENDING:
            invite.status = deps.UserInvite.STATUS_REVOKED
            invite.save(update_fields=["status"])
            _bump_invite_generations_in_atomic(
                agency_id=invite.agency_id,
                invited_by_id=invite.invited_by_id,
                manager_id=invite.manager_id,
            )
    return {"status": "revoked", "invite_id": str(invite.id)}


def accept_invite_impl(
    *,
    deps: Any,
    invite_code: str,
    email: str,
    password: str,
    source_ip: str | None,
    user_agent: str | None,
    request_id: str | None,
) -> dict[str, object]:
    normalized_email = str(email or "").strip().lower()
    code = str(invite_code or "").strip().upper()
    code_hash = deps._sha256(code)
    now = timezone.now()
    with deps.transaction.atomic():
        invite_qs = (
            deps.UserInvite.objects.select_for_update()
            .select_related("agency")
            .filter(
                invite_email__iexact=normalized_email,
                invite_code_hash=code_hash,
                status=deps.UserInvite.STATUS_PENDING,
            )
            .order_by("-created_at", "-id")
        )
        invite = invite_qs.filter(expires_at__gt=now).first()
        if invite is None:
            invite = invite_qs.first()
        if invite is None:
            raise PermissionDeniedError("Invalid invite code.")
        if invite.expires_at <= now:
            invite.status = deps.UserInvite.STATUS_EXPIRED
            invite.save(update_fields=["status"])
            raise PermissionDeniedError("Invite code expired.")

        role = str(invite.role or "")
        manager_id = invite.manager_id
        deps._assert_invite_role_constraints(role=role, manager_id=manager_id)

        User = deps.get_user_model()
        if User.objects.filter(email__iexact=normalized_email).exists():
            raise ValueError("A user with this email already exists.")
        invite_name = deps._resolve_ale_text(invite.invite_name, invite.invite_name_enc)
        first_name, last_name = deps._invite_name_parts(invite_name)
        payload: dict[str, Any] = {
            "username": normalized_email,
            "email": normalized_email,
            "role": role,
            "agency_id": invite.agency_id,
            "manager_id": manager_id,
            "is_owner": False,
            "is_active": True,
            "first_name": first_name,
            "last_name": last_name,
            "mfa_totp_secret": "",
        }
        deps.apply_user_ale(payload, changed_fields={"first_name", "last_name", "mfa_totp_secret"})

        user = User(**payload)
        deps.validate_password(password, user=user)
        user.set_password(password)
        user.full_clean()
        user.save()

        invite.status = deps.UserInvite.STATUS_ACCEPTED
        invite.accepted_at = now
        invite.accepted_user = user
        invite.invite_code_hash = ""
        invite.save(update_fields=["status", "accepted_at", "accepted_user", "invite_code_hash"])
        _bump_invite_generations_in_atomic(
            agency_id=getattr(invite, "agency_id", None),
            invited_by_id=getattr(invite, "invited_by_id", None),
            manager_id=getattr(invite, "manager_id", None),
        )
        _bump_users_generation_in_atomic(agency_id=invite.agency_id)

    tokens = deps._issue_auth_tokens(user=user, source_ip=source_ip, user_agent=user_agent)
    deps.auth_events.log_auth_event(
        event_type="invite_accepted",
        outcome="success",
        agency_id=deps.agency_id_of(user),
        user_id=int(user.id),
        identifier=normalized_email,
        reason_code="invite_joined",
        source_ip=source_ip,
        user_agent=user_agent,
        request_id=request_id,
        fail_silently=True,
    )
    return {
        "status": "accepted",
        "agency_name": str(getattr(invite.agency, "display_name", "") or ""),
        "tokens": tokens,
        "user": deps.serialize_user(user),
    }


def expire_pending_invites_impl(*, deps: Any) -> int:
    now = timezone.now()
    pending_qs = deps.UserInvite.objects.filter(
        status=deps.UserInvite.STATUS_PENDING,
        expires_at__lte=now,
    )
    touched_rows = list(pending_qs.values_list("agency_id", "invited_by_id", "manager_id"))
    changed = pending_qs.update(status=deps.UserInvite.STATUS_EXPIRED)
    if changed:
        for agency_id, invited_by_id, manager_id in touched_rows:
            _bump_invite_generations_in_atomic(
                agency_id=int(agency_id) if isinstance(agency_id, int) else None,
                invited_by_id=(int(invited_by_id) if isinstance(invited_by_id, int) else None),
                manager_id=int(manager_id) if isinstance(manager_id, int) else None,
            )
    return int(changed)
