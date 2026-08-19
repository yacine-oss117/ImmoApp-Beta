"""Registration approval and owner-activation implementations."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.utils import timezone

from server.pg.tenant_context import use_tenant_context
from server.services.errors import NotFoundError, PermissionDeniedError


def submit_registration_impl(
    *,
    deps: Any,
    data: dict[str, object],
    source_ip: str | None,
    user_agent: str | None,
    request_id: str | None,
) -> dict[str, object]:
    deps._require_registration_enabled()
    owner_email = str(data.get("owner_email") or "").strip().lower()
    deps._ensure_not_existing_owner_email(owner_email)
    base_url, base_url_source = deps._public_base_url_with_source()
    if base_url_source == "fallback_localhost" and not deps._PUBLIC_BASE_URL_FALLBACK_WARNED:
        deps._PUBLIC_BASE_URL_FALLBACK_WARNED = True
        deps.logger.warning(
            "IMMOAPP_PUBLIC_BASE_URL not set; registration links are using localhost fallback."
        )
        deps.auth_events.log_auth_event(
            event_type="registration_base_url_fallback",
            outcome="warning",
            agency_id=None,
            user_id=None,
            identifier=owner_email,
            reason_code="fallback_localhost",
            source_ip=source_ip,
            user_agent=user_agent,
            request_id=request_id,
            details={"public_base_url_source": base_url_source, "base_url": base_url},
            fail_silently=True,
        )

    now = timezone.now()
    expires_at = now + timedelta(days=deps._pending_expiry_days())
    payload = {
        "agency_name": str(data.get("agency_name") or "").strip(),
        "legal_name": str(data.get("legal_name") or "").strip(),
        "registry_number": str(data.get("registry_number") or "").strip(),
        "agency_address": str(data.get("agency_address") or "").strip(),
        "agency_city": str(data.get("agency_city") or "").strip(),
        "agency_postal_code": str(data.get("agency_postal_code") or "").strip(),
        "owner_first_name": str(data.get("owner_first_name") or "").strip(),
        "owner_last_name": str(data.get("owner_last_name") or "").strip(),
        "owner_email": owner_email,
        "owner_phone": str(data.get("owner_phone") or "").strip(),
        "terms_accepted": bool(data.get("terms_accepted", False)),
        "status": deps.RegistrationRequest.STATUS_PENDING,
        "expires_at": expires_at,
    }
    deps.apply_registration_request_ale(payload, changed_fields=set(payload.keys()))

    record = None
    with deps.transaction.atomic():
        record = deps.RegistrationRequest.objects.create(**payload)
        token = deps._APPROVAL_SIGNER.sign(str(record.id))
        record.approval_token_hash = deps._sha256(token)
        record.save(update_fields=["approval_token_hash"])

        approve_url = f"{base_url}/api/v1/auth/register/approve/{token}/"
        blacklist_url = f"{base_url}/api/v1/auth/register/blacklist/{token}/"
        subject, body_text, body_html = deps.build_owner_approval_email(
            request=record,
            approve_url=approve_url,
            blacklist_url=blacklist_url,
        )
        deps._queue_platform_email_or_raise(
            to=deps._platform_admin_email(),
            subject=subject,
            body_text=body_text,
            body_html=body_html,
        )

    if record is None:
        raise RuntimeError("registration create failed")

    deps.auth_events.log_auth_event(
        event_type="registration_submitted",
        outcome="success",
        agency_id=None,
        user_id=None,
        identifier=owner_email,
        reason_code="pending_review",
        source_ip=source_ip,
        user_agent=user_agent,
        request_id=request_id,
        details={
            "registration_id": str(record.id),
            "public_base_url_source": base_url_source,
        },
        fail_silently=True,
    )
    return {
        "status": "pending",
        "message": "Your request has been submitted. We'll review it within 24 hours.",
        "delivery_status": "queued",
        "delivery_detail": "Email queued for delivery.",
        "public_base_url_source": base_url_source,
    }


def load_registration_for_signed_token_impl(
    *,
    deps: Any,
    signed_token: str,
    for_update: bool = True,
) -> Any:
    try:
        unsigned = deps._APPROVAL_SIGNER.unsign(
            str(signed_token),
            max_age=deps._approval_token_expiry_days() * 86400,
        )
    except deps.SignatureExpired as exc:
        raise PermissionDeniedError("Invalid or expired link.") from exc
    except deps.BadSignature as exc:
        raise PermissionDeniedError("Invalid or expired link.") from exc

    request_id = deps._parse_uuid(unsigned)
    qs = deps.RegistrationRequest.objects
    if for_update:
        qs = qs.select_for_update()
    record = qs.filter(id=request_id).first()
    if record is None:
        raise NotFoundError("Registration request not found.")
    if record.approval_token_hash and record.approval_token_hash != deps._sha256(str(signed_token)):
        raise PermissionDeniedError("Invalid or expired link.")
    return record


def load_registration_for_review_impl(*, deps: Any, signed_token: str) -> Any:
    record = deps._load_registration_for_signed_token(signed_token=signed_token, for_update=False)
    if record.status != deps.RegistrationRequest.STATUS_PENDING:
        raise ValueError("Registration request is no longer pending.")
    if record.expires_at and record.expires_at <= timezone.now():
        raise PermissionDeniedError("Invalid or expired link.")
    return record


def registration_review_details_impl(*, deps: Any, record: Any) -> dict[str, str]:
    return {
        "agency_name": deps._registration_plain(record, "agency_name"),
        "legal_name": deps._registration_plain(record, "legal_name"),
        "registry_number": deps._registration_plain(record, "registry_number"),
        "address": deps._registration_plain(record, "agency_address"),
        "city": deps._registration_plain(record, "agency_city"),
        "postal_code": deps._registration_plain(record, "agency_postal_code"),
        "owner_name": (
            f"{deps._registration_plain(record, 'owner_first_name')} "
            f"{deps._registration_plain(record, 'owner_last_name')}"
        ).strip(),
        "owner_email": str(record.owner_email or ""),
        "owner_phone": deps._registration_plain(record, "owner_phone"),
        "submitted_at": record.created_at.strftime("%Y-%m-%d %H:%M") if record.created_at else "",
    }


def finalize_agency_ale_fields_impl(*, deps: Any, agency: Any, payload: dict[str, Any]) -> Any:
    finalized = dict(payload)
    with use_tenant_context(
        agency_id=int(agency.id),
        source="platform_bootstrap",
        bootstrap_mode="platform_root_create",
    ):
        deps.apply_agency_ale(
            finalized,
            changed_fields=set(finalized.keys()),
            agency_id=int(agency.id),
        )
    for key, value in finalized.items():
        setattr(agency, key, value)
    agency.save(update_fields=list(finalized.keys()))
    return agency


def approve_registration_by_token_impl(*, deps: Any, signed_token: str) -> dict[str, object]:
    with deps.transaction.atomic():
        record = deps._load_registration_for_signed_token(signed_token=signed_token)
        if record.status != deps.RegistrationRequest.STATUS_PENDING:
            raise ValueError("Registration request is no longer pending.")
        if record.expires_at and record.expires_at <= timezone.now():
            record.status = deps.RegistrationRequest.STATUS_EXPIRED
            record.reviewed_at = timezone.now()
            record.save(update_fields=["status", "reviewed_at"])
            raise PermissionDeniedError("Invalid or expired link.")

        agency_name = deps._registration_plain(record, "agency_name")
        legal_name = deps._registration_plain(record, "legal_name")
        registry_number = deps._registration_plain(record, "registry_number")
        address = deps._registration_plain(record, "agency_address")
        city = deps._registration_plain(record, "agency_city")
        postal_code = deps._registration_plain(record, "agency_postal_code")
        owner_first = deps._registration_plain(record, "owner_first_name")
        owner_last = deps._registration_plain(record, "owner_last_name")
        owner_phone = deps._registration_plain(record, "owner_phone")
        owner_email = str(record.owner_email or "").strip().lower()

        agency_payload: dict[str, Any] = {
            "legal_name": legal_name or agency_name,
            "display_name": agency_name or legal_name,
            "agency_code": deps._generate_agency_code(agency_name or legal_name),
            "kbis_number": registry_number,
            "phone_number": owner_phone,
            "email": owner_email,
            "address_line1": address,
            "address_line2": "",
            "city": city,
            "postal_code": postal_code,
            "country": "Algeria",
        }
        agency = deps.Agency.objects.create(**agency_payload)
        agency = deps._finalize_agency_ale_fields(agency=agency, payload=agency_payload)

        user_payload: dict[str, Any] = {
            "username": owner_email,
            "email": owner_email,
            "role": "manager",
            "is_owner": True,
            "is_active": False,
            "agency": agency,
            "manager": None,
            "first_name": owner_first,
            "last_name": owner_last,
            "mfa_totp_secret": "",
        }
        deps.apply_user_ale(
            user_payload, changed_fields={"first_name", "last_name", "mfa_totp_secret"}
        )
        User = deps.get_user_model()
        owner = User(**user_payload)
        owner.set_unusable_password()
        owner.full_clean()
        owner.save()

        activation_code = deps._generate_code(length=8)
        record.status = deps.RegistrationRequest.STATUS_APPROVED
        record.reviewed_at = timezone.now()
        record.activation_code_hash = deps._sha256(activation_code)
        record.activation_code_expires_at = timezone.now() + timedelta(
            hours=deps._activation_expiry_hours()
        )
        record.save(
            update_fields=[
                "status",
                "reviewed_at",
                "activation_code_hash",
                "activation_code_expires_at",
            ]
        )
        subject, body_text, body_html = deps.build_owner_welcome_email(
            agency_name=agency.display_name,
            owner_name=f"{owner_first} {owner_last}".strip() or owner_email,
            activation_code=activation_code,
            login_email=owner_email,
        )
        deps._queue_platform_email_or_raise(
            to=owner_email,
            subject=subject,
            body_text=body_text,
            body_html=body_html,
        )

    owner_id = int(owner.id)
    agency_id = int(agency.id)
    owner_display_name = f"{owner_first} {owner_last}".strip() or owner_email
    try:
        with use_tenant_context(
            agency_id=agency_id,
            is_superuser=False,
            source="platform_bootstrap",
        ):
            deps._safe_record_and_notify(
                scope="user",
                user_id=owner_id,
                event_type="registration.approved",
                title="Your account is approved",
                body="Your account was approved. You can finish setup and sign in.",
                data={"user_id": owner_id},
            )
            User = deps.get_user_model_for_service()
            has_other_active_users = (
                User.objects.filter(agency_id=agency_id, is_active=True)
                .exclude(id=owner_id)
                .exists()
            )
            if has_other_active_users:
                deps._safe_record_and_notify(
                    scope="agency",
                    event_type="registration.approved",
                    title="New team member approved",
                    body=f"{owner_display_name} has been approved and can now sign in.",
                    data={"user_id": owner_id},
                )
    except Exception:
        deps.logger.warning("Failed to emit registration approval notifications", exc_info=True)
    return {
        "status": "approved",
        "owner_email": owner_email,
        "delivery_status": "queued",
        "delivery_detail": "Email queued for delivery.",
    }


def blacklist_registration_by_token_impl(*, deps: Any, signed_token: str) -> dict[str, object]:
    with deps.transaction.atomic():
        record = deps._load_registration_for_signed_token(signed_token=signed_token)
        if record.status != deps.RegistrationRequest.STATUS_PENDING:
            raise ValueError("Registration request is no longer pending.")
        owner_name = (
            f"{deps._registration_plain(record, 'owner_first_name')} "
            f"{deps._registration_plain(record, 'owner_last_name')}"
        ).strip()
        owner_email = str(record.owner_email or "").strip().lower()
        record.status = deps.RegistrationRequest.STATUS_BLACKLISTED
        record.reviewed_at = timezone.now()
        record.save(update_fields=["status", "reviewed_at"])
        subject, body_text, body_html = deps.build_registration_declined_email(
            owner_name=owner_name or owner_email
        )
        deps._queue_platform_email_or_raise(
            to=owner_email,
            subject=subject,
            body_text=body_text,
            body_html=body_html,
        )
    return {
        "status": "blacklisted",
        "owner_email": owner_email,
        "delivery_status": "queued",
        "delivery_detail": "Email queued for delivery.",
    }


def activate_owner_impl(
    *,
    deps: Any,
    email: str,
    activation_code: str,
    password: str,
    source_ip: str | None,
    user_agent: str | None,
    request_id: str | None,
) -> dict[str, object]:
    normalized_email = str(email or "").strip().lower()
    now = timezone.now()
    with deps.transaction.atomic():
        record = (
            deps.RegistrationRequest.objects.select_for_update()
            .filter(
                owner_email__iexact=normalized_email,
                status=deps.RegistrationRequest.STATUS_APPROVED,
            )
            .first()
        )
        if record is None:
            raise PermissionDeniedError("Invalid activation code.")
        if not record.activation_code_hash or not deps._verify_code(
            activation_code, record.activation_code_hash
        ):
            raise PermissionDeniedError("Invalid activation code.")
        if record.activation_code_expires_at is None or record.activation_code_expires_at <= now:
            raise PermissionDeniedError("Activation code expired.")

        User = deps.get_user_model_for_service()
        user = User.objects.select_for_update().filter(email__iexact=normalized_email).first()
        if user is None:
            raise NotFoundError("Owner account not found.")
        deps.validate_password(password, user=user)
        user.set_password(password)
        user.is_active = True
        user.full_clean()
        user.save(update_fields=["password", "is_active"])

        record.activation_code_hash = ""
        record.activation_code_expires_at = None
        record.save(update_fields=["activation_code_hash", "activation_code_expires_at"])

    tokens = deps._issue_auth_tokens(user=user, source_ip=source_ip, user_agent=user_agent)
    deps.auth_events.log_auth_event(
        event_type="registration_activation",
        outcome="success",
        agency_id=deps.agency_id_of(user),
        user_id=int(user.id),
        identifier=normalized_email,
        reason_code="activated",
        source_ip=source_ip,
        user_agent=user_agent,
        request_id=request_id,
        fail_silently=True,
    )
    agency_id = deps.agency_id_of(user)
    if agency_id is not None:
        display_name = (
            f"{str(user.first_name or '').strip()} {str(user.last_name or '').strip()}".strip()
        )
        if not display_name:
            display_name = normalized_email
        try:
            with use_tenant_context(
                agency_id=int(agency_id),
                is_superuser=False,
                source="explicit",
            ):
                deps._safe_record_and_notify(
                    scope="agency",
                    event_type="team.member_joined",
                    title="Team member joined",
                    body=f"{display_name} has joined your team.",
                    data={"user_id": int(user.id)},
                )
        except Exception:
            deps.logger.warning("Failed to emit activation notification", exc_info=True)
    return {"status": "activated", "tokens": tokens, "user": deps.serialize_user(user)}


def expire_pending_registrations_impl(*, deps: Any, older_than_days: int | None = None) -> int:
    days = older_than_days or deps._pending_expiry_days()
    now = timezone.now()
    cutoff = now - timedelta(days=max(1, int(days)))
    changed = (
        deps.RegistrationRequest.objects.filter(status=deps.RegistrationRequest.STATUS_PENDING)
        .filter(
            deps.Q(expires_at__isnull=False, expires_at__lte=now)
            | deps.Q(expires_at__isnull=True, created_at__lte=cutoff)
        )
        .update(status=deps.RegistrationRequest.STATUS_EXPIRED, reviewed_at=now)
    )
    return int(changed)
