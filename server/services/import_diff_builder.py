"""Field-level diff helpers for import review and audit flows."""

from __future__ import annotations

from typing import Any

from server.services.import_review_policy import decision_policy_for_entity


def _plain_value(value: Any) -> Any:
    if isinstance(value, bool):
        return int(value)
    if value in ("", [], {}):
        return None
    return value


def snapshot_payload(entity_type: str, payload: dict[str, Any] | None) -> dict[str, Any]:
    policy = decision_policy_for_entity(entity_type)
    ordered_fields = list(policy.mutable_fields) + list(policy.immutable_fields)
    source = dict(payload or {})
    return {field: _plain_value(source.get(field)) for field in ordered_fields if field in source}


def build_field_diff(
    *,
    entity_type: str,
    incoming: dict[str, Any] | None,
    existing: dict[str, Any] | None,
) -> dict[str, list[dict[str, Any]]]:
    policy = decision_policy_for_entity(entity_type)
    ordered_fields = list(policy.mutable_fields) + list(policy.immutable_fields)
    incoming_payload = snapshot_payload(entity_type, incoming)
    existing_payload = snapshot_payload(entity_type, existing)
    changed_mutable: list[dict[str, Any]] = []
    changed_immutable: list[dict[str, Any]] = []
    unchanged: list[dict[str, Any]] = []

    for field in ordered_fields:
        incoming_value = _plain_value(incoming_payload.get(field))
        existing_value = _plain_value(existing_payload.get(field))
        diff = {
            "field": field,
            "incoming": incoming_value,
            "existing": existing_value,
        }
        if incoming_value == existing_value:
            unchanged.append(diff)
        elif field in policy.immutable_fields:
            changed_immutable.append(diff)
        else:
            changed_mutable.append(diff)

    return {
        "changed_mutable": changed_mutable,
        "changed_immutable": changed_immutable,
        "unchanged": unchanged,
    }


def flatten_field_diffs(field_diff: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    return list(field_diff.get("changed_mutable", [])) + list(
        field_diff.get("changed_immutable", [])
    )


def has_immutable_conflict(field_diff: dict[str, list[dict[str, Any]]]) -> bool:
    return bool(field_diff.get("changed_immutable"))


__all__ = [
    "build_field_diff",
    "flatten_field_diffs",
    "has_immutable_conflict",
    "snapshot_payload",
]
