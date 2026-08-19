"""Pure helpers for importer review actions and draft payloads."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def normalize_review_action(action: str) -> str:
    normalized = str(action or "").strip().lower()
    return {
        "create": "create_new",
        "create_new": "create_new",
        "update": "update_existing",
        "update_existing": "update_existing",
        "review": "review_ambiguous",
        "review_ambiguous": "review_ambiguous",
        "skip": "skip",
    }.get(normalized, normalized)


def legacy_review_action(action: str) -> str:
    normalized = normalize_review_action(action)
    return {
        "create_new": "create",
        "update_existing": "update",
        "review_ambiguous": "review",
        "skip": "skip",
    }.get(normalized, normalized)


def allowed_entity_types_for_state(state: object) -> list[str]:
    bundle_mode = str(getattr(state, "bundle_mode", "single_entity") or "single_entity")
    topology_side = str(getattr(state, "topology_side_hint", "unknown") or "unknown")
    if bundle_mode == "same_side_bundle":
        if topology_side == "client_side":
            return ["client", "demande"]
        return ["listing", "offer"]
    detected = str(getattr(state, "detected_entity", "") or "")
    return [detected] if detected else []


def draft_to_submit_payload(
    *,
    draft: Mapping[str, Any],
    entry: Mapping[str, Any],
) -> tuple[dict[str, Any] | None, bool]:
    action = normalize_review_action(str(draft.get("action", "") or ""))
    if not action:
        return None, False
    if action == "skip":
        return None, True
    item_payload: dict[str, Any] = {"action": action}
    entity_type = str(
        draft.get("entity_type", entry.get("entity_type", "")) or entry.get("entity_type", "")
    )
    if entity_type:
        item_payload["entity_type"] = entity_type
    payload = dict(draft.get("payload", {}) or {})
    baseline = dict(entry.get("normalized_data", entry.get("data", {})) or {})
    if payload and payload != baseline:
        item_payload["corrections"] = payload
    if action == "update_existing":
        existing_id = int(draft.get("existing_id", 0) or 0)
        if existing_id <= 0:
            return None, False
        item_payload["existing_id"] = existing_id
        candidate_matches = list(entry.get("candidate_matches", []) or [])
        row_version = 0
        for candidate in candidate_matches:
            if int(candidate.get("id", 0) or 0) == existing_id:
                row_version = int(candidate.get("row_version", 0) or 0)
                break
        if row_version <= 0:
            return None, False
        item_payload["row_version"] = row_version
    return item_payload, False


__all__ = [
    "allowed_entity_types_for_state",
    "draft_to_submit_payload",
    "legacy_review_action",
    "normalize_review_action",
]
