"""ALE helpers for Django account models."""

from __future__ import annotations

from collections.abc import Collection, Sequence
from functools import lru_cache
from typing import Any

from core.ale_utils import is_legacy_ale_mask, is_structured_ale_mask
from core.encryption import get_optional_encryption_service

from .ale_helper import normalize_ale_fields
from .ale_policy import (
    AGENCY_ALE_POLICIES,
    REGISTRATION_REQUEST_ALE_POLICIES,
    USER_ALE_POLICIES,
    USER_INVITE_ALE_POLICIES,
    AleFieldPolicy,
)


@lru_cache(maxsize=8192)
def _decrypt_cached(ciphertext: str) -> str:
    enc = get_optional_encryption_service()
    if enc is None:
        return ""
    try:
        return str(enc.decrypt(ciphertext) or "")
    except Exception:
        return ""


def _apply(
    payload: dict[str, Any],
    *,
    policies: Sequence[AleFieldPolicy],
    changed_fields: Collection[str] | None = None,
    allowed_search_src: set[str] | None = None,
    agency_id: int | None = None,
) -> dict[str, Any]:
    selected_policies = []
    for policy in policies:
        if policy.name in payload:
            selected_policies.append(policy)
            continue
        if changed_fields is not None and policy.name in changed_fields:
            selected_policies.append(policy)
    if not selected_policies:
        return payload

    working: dict[str, Any] = {}
    for policy in selected_policies:
        if policy.name in payload:
            working[policy.name] = payload[policy.name]
        if policy.name + "_enc" in payload:
            working[policy.name + "_enc"] = payload[policy.name + "_enc"]
        if policy.name + "_search_src" in payload:
            working[policy.name + "_search_src"] = payload[policy.name + "_search_src"]

    normalize_ale_fields(
        working,
        selected_policies,
        changed_fields=changed_fields,
        agency_id=agency_id,
    )
    payload.update(working)
    if allowed_search_src is None:
        allowed_search_src = set()
    for key in list(payload.keys()):
        if key.endswith("_search_src") and key not in allowed_search_src:
            payload.pop(key, None)
    return payload


def apply_registration_request_ale(
    payload: dict[str, Any],
    *,
    changed_fields: Collection[str] | None = None,
    agency_id: int | None = None,
) -> dict[str, Any]:
    return _apply(
        payload,
        policies=REGISTRATION_REQUEST_ALE_POLICIES,
        changed_fields=changed_fields,
        agency_id=agency_id,
    )


def apply_user_invite_ale(
    payload: dict[str, Any],
    *,
    changed_fields: Collection[str] | None = None,
    agency_id: int | None = None,
) -> dict[str, Any]:
    return _apply(
        payload,
        policies=USER_INVITE_ALE_POLICIES,
        changed_fields=changed_fields,
        agency_id=agency_id,
    )


def apply_user_ale(
    payload: dict[str, Any],
    *,
    changed_fields: Collection[str] | None = None,
    agency_id: int | None = None,
) -> dict[str, Any]:
    return _apply(
        payload,
        policies=USER_ALE_POLICIES,
        changed_fields=changed_fields,
        allowed_search_src={"first_name_search_src", "last_name_search_src"},
        agency_id=agency_id,
    )


def apply_agency_ale(
    payload: dict[str, Any],
    *,
    changed_fields: Collection[str] | None = None,
    agency_id: int | None = None,
) -> dict[str, Any]:
    return _apply(
        payload,
        policies=AGENCY_ALE_POLICIES,
        changed_fields=changed_fields,
        agency_id=agency_id,
    )


def _resolve_masked_value(masked_value: object, encrypted_value: object) -> str:
    raw = str(masked_value or "")
    if not raw:
        return ""
    if not (is_structured_ale_mask(raw) or is_legacy_ale_mask(raw)):
        return raw
    cipher = str(encrypted_value or "")
    if not cipher:
        return ""
    return _decrypt_cached(cipher)


def resolve_user_name(user: object, field_name: str) -> str:
    masked = getattr(user, field_name, "")
    encrypted = getattr(user, field_name + "_enc", "")
    return _resolve_masked_value(masked, encrypted)


def resolve_user_mfa_secret(user: object) -> str:
    masked = getattr(user, "mfa_totp_secret", "")
    encrypted = getattr(user, "mfa_totp_secret_enc", "")
    return _resolve_masked_value(masked, encrypted)


__all__ = [
    "apply_agency_ale",
    "apply_registration_request_ale",
    "apply_user_ale",
    "apply_user_invite_ale",
    "resolve_user_mfa_secret",
    "resolve_user_name",
]
