"""Email template builders for registration and invite lifecycle."""

from __future__ import annotations

from html import escape
from typing import Any

from core.ale_utils import is_legacy_ale_mask, is_structured_ale_mask


def _resolve_ale_text(value: object, encrypted: object) -> str:
    text = str(value or "")
    if not text:
        return ""
    if not (is_structured_ale_mask(text) or is_legacy_ale_mask(text)):
        return text
    cipher = str(encrypted or "")
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


def build_owner_approval_email(
    request: Any,
    *,
    approve_url: str,
    blacklist_url: str,
) -> tuple[str, str, str]:
    agency_name = _resolve_ale_text(
        request.agency_name,
        getattr(request, "agency_name_enc", ""),
    )
    legal_name = _resolve_ale_text(request.legal_name, getattr(request, "legal_name_enc", ""))
    registry_number = _resolve_ale_text(
        request.registry_number,
        getattr(request, "registry_number_enc", ""),
    )
    agency_address = _resolve_ale_text(
        request.agency_address,
        getattr(request, "agency_address_enc", ""),
    )
    agency_city = _resolve_ale_text(request.agency_city, getattr(request, "agency_city_enc", ""))
    agency_postal_code = _resolve_ale_text(
        request.agency_postal_code,
        getattr(request, "agency_postal_code_enc", ""),
    )
    owner_first_name = _resolve_ale_text(
        request.owner_first_name,
        getattr(request, "owner_first_name_enc", ""),
    )
    owner_last_name = _resolve_ale_text(
        request.owner_last_name,
        getattr(request, "owner_last_name_enc", ""),
    )
    owner_phone = _resolve_ale_text(request.owner_phone, getattr(request, "owner_phone_enc", ""))

    subject = f"ImmoApp registration review: {agency_name}"
    lines = [
        "A new agency registration request is awaiting review.",
        "",
        f"Agency: {agency_name}",
        f"Legal name: {legal_name}",
        f"Registry number: {registry_number}",
        f"Address: {agency_address}, {agency_city}, {agency_postal_code}",
        f"Owner: {owner_first_name} {owner_last_name}",
        f"Owner email: {request.owner_email}",
        f"Owner phone: {owner_phone}",
        "",
        f"Approve: {approve_url}",
        f"Blacklist: {blacklist_url}",
    ]
    text = "\n".join(lines)
    html = (
        "<p>A new agency registration request is awaiting review.</p>"
        f"<p><strong>Agency:</strong> {escape(str(agency_name))}<br>"
        f"<strong>Legal name:</strong> {escape(str(legal_name))}<br>"
        f"<strong>Registry number:</strong> {escape(str(registry_number))}<br>"
        f"<strong>Address:</strong> {escape(str(agency_address))}, "
        f"{escape(str(agency_city))}, {escape(str(agency_postal_code))}<br>"
        f"<strong>Owner:</strong> {escape(str(owner_first_name))} "
        f"{escape(str(owner_last_name))}<br>"
        f"<strong>Owner email:</strong> {escape(str(request.owner_email))}<br>"
        f"<strong>Owner phone:</strong> {escape(str(owner_phone))}</p>"
        f'<p><a href="{escape(approve_url)}">Approve</a> | '
        f'<a href="{escape(blacklist_url)}">Blacklist</a></p>'
    )
    return subject, text, html


def build_owner_welcome_email(
    *,
    agency_name: str,
    owner_name: str,
    activation_code: str,
    login_email: str,
) -> tuple[str, str, str]:
    subject = f"Welcome to ImmoApp, {agency_name}"
    text = (
        f"Hello {owner_name},\n\n"
        "Thank you for choosing ImmoApp.\n"
        "Your agency registration has been approved.\n\n"
        f"Login email: {login_email}\n"
        f"Activation code: {activation_code}\n\n"
        "Open the desktop app and use Activate account to set your password.\n"
    )
    html = (
        f"<p>Hello {escape(owner_name)},</p>"
        "<p>Thank you for choosing ImmoApp. Your agency registration has been approved.</p>"
        f"<p><strong>Login email:</strong> {escape(login_email)}<br>"
        f"<strong>Activation code:</strong> {escape(activation_code)}</p>"
        "<p>Open the desktop app and use <em>Activate account</em> to set your password.</p>"
    )
    return subject, text, html


def build_team_invite_email(
    *,
    agency_name: str,
    inviter_name: str,
    invitee_name: str,
    invite_code: str,
) -> tuple[str, str, str]:
    subject = f"Invitation to join {agency_name} on ImmoApp"
    text = (
        f"Hello {invitee_name},\n\n"
        f"{inviter_name} invited you to join {agency_name} on ImmoApp.\n\n"
        f"Invite code: {invite_code}\n\n"
        "Open the desktop app and choose Join your team.\n"
    )
    html = (
        f"<p>Hello {escape(invitee_name)},</p>"
        f"<p>{escape(inviter_name)} invited you to join {escape(agency_name)} on ImmoApp.</p>"
        f"<p><strong>Invite code:</strong> {escape(invite_code)}</p>"
        "<p>Open the desktop app and choose <em>Join your team</em>.</p>"
    )
    return subject, text, html


def build_registration_declined_email(*, owner_name: str) -> tuple[str, str, str]:
    subject = "ImmoApp registration update"
    text = (
        f"Hello {owner_name},\n\n"
        "We're unable to activate your account at this time.\n"
        "If you believe this is an error, please contact support.\n"
    )
    html = (
        f"<p>Hello {escape(owner_name)},</p>"
        "<p>We're unable to activate your account at this time.</p>"
        "<p>If you believe this is an error, please contact support.</p>"
    )
    return subject, text, html


__all__ = [
    "build_owner_approval_email",
    "build_owner_welcome_email",
    "build_registration_declined_email",
    "build_team_invite_email",
]
