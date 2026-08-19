"""Replay payload policy for idempotent responses."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Literal

ReplayMode = Literal["NONE", "FULL_SAFE", "REFERENCE_ONLY"]

REPLAY_DENYLIST_KEYS: frozenset[str] = frozenset(
    {
        "password",
        "token",
        "refresh",
        "access",
        "authorization",
        "phone",
        "email",
        "family_name",
        "first_name",
        "last_name",
        "address",
        "national_id",
        "ssn",
        "secret",
    }
)

FULL_SAFE_FIELD_ALLOWLIST: dict[str, frozenset[str]] = {
    "*": frozenset(
        {
            "id",
            "ids",
            "status",
            "code",
            "detail",
            "message",
            "errors",
            "error",
            "items",
            "total",
            "count",
            "counts",
            "count_meta",
            "task_id",
            "created",
            "updated",
            "deleted",
            "valid",
            "action",
            "resource_url",
            "current_row_version",
            "current_record",
            "policy_version",
            "semantic_header_registry_hash",
            "retry_after_seconds",
            "retryable",
        }
    ),
}

REFERENCE_ONLY_POLICIES: frozenset[str] = frozenset(
    {
        "route.clients",
        "route.clients_int_client_id",
        "route.listings",
        "route.listings_int_listing_id",
        "route.offers_int_offer_id",
        "route.demandes_int_demande_id",
        "route.users",
        "route.users_int_user_id",
        "route.crm_visits",
        "route.crm_contracts",
    }
)


def _is_blocked_key(key: str) -> bool:
    lowered = key.strip().lower()
    if lowered in REPLAY_DENYLIST_KEYS:
        return True
    return any(term in lowered for term in REPLAY_DENYLIST_KEYS)


def _reference_only_payload(payload: Any) -> dict[str, Any]:
    if isinstance(payload, Mapping):
        ref: dict[str, Any] = {}
        for key in ("id", "ids", "resource_id", "resource_url", "task_id", "code", "detail"):
            if key in payload:
                ref[key] = payload[key]
        if ref:
            return ref
    return {"detail": "reference_only_replay"}


def _sanitize_mapping(payload: Mapping[str, Any], allowlist: frozenset[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in payload.items():
        text_key = str(key)
        if _is_blocked_key(text_key):
            continue
        if text_key not in allowlist:
            continue
        out[text_key] = sanitize_replay_payload(
            value,
            policy_id="*",
            replay_mode="FULL_SAFE",
        )
    return out


def sanitize_replay_payload(
    payload: Any,
    *,
    policy_id: str,
    replay_mode: ReplayMode,
) -> Any:
    if replay_mode == "REFERENCE_ONLY" or policy_id in REFERENCE_ONLY_POLICIES:
        return _reference_only_payload(payload)
    if replay_mode != "FULL_SAFE":
        return {"detail": "replay_disabled_for_policy"}

    allowlist = FULL_SAFE_FIELD_ALLOWLIST.get(policy_id) or FULL_SAFE_FIELD_ALLOWLIST["*"]
    if isinstance(payload, Mapping):
        return _sanitize_mapping(payload, allowlist)
    if isinstance(payload, Sequence) and not isinstance(payload, (str, bytes, bytearray)):
        return [
            sanitize_replay_payload(item, policy_id=policy_id, replay_mode="FULL_SAFE")
            for item in payload
        ]
    if isinstance(payload, (str, int, float, bool)) or payload is None:
        return payload
    return str(payload)


__all__ = [
    "FULL_SAFE_FIELD_ALLOWLIST",
    "REFERENCE_ONLY_POLICIES",
    "REPLAY_DENYLIST_KEYS",
    "sanitize_replay_payload",
]
