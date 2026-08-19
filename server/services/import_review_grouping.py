"""Grouping helpers for DB-backed import review state."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from server.services.duplicate_checker import _normalize_phone_for_dedup
from server.services.import_ui_summary import issue_metadata

_ISSUE_PRIORITY = {
    "field_conflict": 0,
    "possible_duplicate": 1,
    "parent_match_needed": 2,
    "missing_information": 3,
    "unclear_location": 4,
    "unclear_property_type": 5,
    "other": 6,
}


@dataclass(frozen=True)
class ReviewGroupingContext:
    job_id: str
    bundle_mode: str
    topology_side: str


@dataclass(frozen=True)
class ReviewGroupItemPayload:
    group_key: str
    group_kind: str
    issue_group: str
    issue_title: str
    issue_summary: str
    entity_type: str
    topology_side: str
    root_identity: dict[str, str | None]
    root_label: str
    root_row_ordinal: int
    suggested_group_action: str
    status: str
    metadata: dict[str, Any]
    apply_to_all_allowed: bool
    apply_to_all_count: int
    consistent_existing_id: int
    resolution_template: dict[str, Any]
    resolved_item_count: int
    item: dict[str, Any]


@dataclass(frozen=True)
class ReviewGroupPayload:
    group_key: str
    group_kind: str
    issue_group: str
    issue_title: str
    issue_summary: str
    entity_type: str
    topology_side: str
    root_identity: dict[str, str | None]
    root_label: str
    root_row_ordinal: int
    suggested_group_action: str
    status: str
    metadata: dict[str, Any]
    apply_to_all_allowed: bool
    apply_to_all_count: int
    consistent_existing_id: int
    resolution_template: dict[str, Any]
    resolved_item_count: int
    items: list[dict[str, Any]]


def _candidate_text(row: Mapping[str, Any], *keys: str) -> str:
    for payload_key in ("normalized_data", "data", "raw_data", "original"):
        payload = row.get(payload_key)
        if not isinstance(payload, Mapping):
            continue
        for key in keys:
            value = str(payload.get(key, "") or "").strip()
            if value:
                return value
    return ""


def _root_identity(row: Mapping[str, Any]) -> dict[str, str | None]:
    snapshot = row.get("root_identity_snapshot")
    if isinstance(snapshot, Mapping):
        phone = _normalize_phone_for_dedup(str(snapshot.get("phone", "") or ""))
        family_name = str(snapshot.get("family_name", "") or "").strip()
        email = str(snapshot.get("email", "") or "").strip().casefold()
        if phone or family_name or email:
            return {
                "phone": phone or None,
                "family_name": family_name or None,
                "email": email or None,
            }
    family_name = _candidate_text(row, "family_name", "name")
    email = _candidate_text(row, "email")
    phone = _normalize_phone_for_dedup(_candidate_text(row, "phone"))
    return {
        "phone": phone or None,
        "family_name": family_name or None,
        "email": email.casefold() or None if email else None,
    }


def _group_prefix(entity_type: str, topology_side: str) -> str:
    if topology_side == "listing_side" or entity_type in {"listing", "offer"}:
        return "listing"
    return "client"


def root_group_key(
    *,
    review_row: Mapping[str, Any],
    context: ReviewGroupingContext,
) -> str:
    entity_type = str(review_row.get("entity_type", "") or "").strip().lower()
    topology_side = str(
        review_row.get("topology_side", context.topology_side) or context.topology_side
    )
    prefix = _group_prefix(entity_type, topology_side)
    identity = _root_identity(review_row)
    if context.bundle_mode == "same_side_bundle":
        if identity["phone"]:
            return f"{prefix}:phone:{identity['phone']}"
        if identity["email"]:
            return f"{prefix}:email:{identity['email']}"
        if identity["family_name"]:
            return f"{prefix}:name:{str(identity['family_name']).strip().casefold()}"
        row_num = int(review_row.get("row", 0) or 0)
        return f"singleton:{context.job_id}:{row_num}:{entity_type or prefix}"
    row_num = int(review_row.get("row", 0) or 0)
    return f"singleton:{context.job_id}:{row_num}:{entity_type or prefix}"


def _group_kind(
    *,
    group_key: str,
    items: list[dict[str, Any]],
    context: ReviewGroupingContext,
) -> str:
    if len(items) <= 1:
        item = items[0]
        if bool(item.get("immutable_conflict", False)):
            return "field_conflict"
        return "single_row"

    names = {
        str(identity.get("family_name", "") or "").strip().casefold()
        for identity in (_root_identity(item) for item in items)
        if str(identity.get("family_name", "") or "").strip()
    }
    emails = {
        str(identity.get("email", "") or "").strip().casefold()
        for identity in (_root_identity(item) for item in items)
        if str(identity.get("email", "") or "").strip()
    }
    suggested_existing = {
        int(item.get("suggested_existing_id", 0) or 0)
        for item in items
        if int(item.get("suggested_existing_id", 0) or 0) > 0
    }
    if bool(names and len(names) > 1) or bool(emails and len(emails) > 1):
        return "duplicate_conflict"
    if len(suggested_existing) > 1:
        return "duplicate_conflict"
    if any(bool(item.get("immutable_conflict", False)) for item in items):
        return "duplicate_conflict"
    if context.bundle_mode == "same_side_bundle" and not group_key.startswith("singleton:"):
        return "bundle_root"
    return "single_row"


def _dominant_issue(items: list[dict[str, Any]]) -> tuple[str, str, str]:
    ranked = sorted(
        items,
        key=lambda row: (
            _ISSUE_PRIORITY.get(str(row.get("issue_group", "other") or "other"), 999),
            int(row.get("row", 0) or 0),
        ),
    )
    chosen = ranked[0]
    return (
        str(chosen.get("issue_group", "other") or "other"),
        str(chosen.get("issue_title", "Needs attention") or "Needs attention"),
        str(
            chosen.get("issue_summary", "This line needs a quick review before we continue.")
            or "This line needs a quick review before we continue."
        ),
    )


def _root_label(items: list[dict[str, Any]]) -> str:
    root_item = min(items, key=lambda row: int(row.get("row", 0) or 0))
    identity = _root_identity(root_item)
    if identity["family_name"]:
        return str(identity["family_name"])
    if identity["phone"]:
        return str(identity["phone"])
    if identity["email"]:
        return str(identity["email"])
    return f"Line {int(root_item.get('row', 0) or 0)}"


def _group_representative_item(
    items: list[dict[str, Any]],
    *,
    context: ReviewGroupingContext,
) -> dict[str, Any]:
    if not items:
        return {}
    root_entity_type = _root_entity_type(items, context=context)
    root_items = [
        item
        for item in items
        if str(item.get("entity_type", "") or "").strip().lower() == root_entity_type
    ]
    candidates = root_items or items
    return min(candidates, key=lambda row: int(row.get("row", 0) or 0))


def _suggested_group_action(items: list[dict[str, Any]], group_kind: str) -> str:
    if group_kind in {"duplicate_conflict", "field_conflict"}:
        return "review_ambiguous"
    actions = {
        str(item.get("suggested_action", "") or "").strip().lower()
        for item in items
        if str(item.get("suggested_action", "") or "").strip()
    }
    if not actions:
        return ""
    if len(actions) == 1:
        return next(iter(actions))
    return "review_ambiguous"


def _blocking_status(items: list[dict[str, Any]]) -> str:
    if items and all(
        bool(list(item.get("blocking_reasons", []) or []))
        or bool(item.get("immutable_conflict", False))
        for item in items
    ):
        return "blocked"
    return "pending"


def _group_metadata(items: list[dict[str, Any]]) -> dict[str, Any]:
    candidate_ids = sorted(
        {
            int(item.get("suggested_existing_id", 0) or 0)
            for item in items
            if int(item.get("suggested_existing_id", 0) or 0) > 0
        }
    )
    return {
        "sample_rows": sorted(int(item.get("row", 0) or 0) for item in items)[:5],
        "candidate_existing_ids": candidate_ids,
    }


def _normalize_resolution_action(value: object) -> str:
    normalized = str(value or "").strip().lower()
    return {
        "create": "create_new",
        "create_new": "create_new",
        "update": "update_existing",
        "update_existing": "update_existing",
        "review": "review_ambiguous",
        "review_ambiguous": "review_ambiguous",
        "skip": "skip",
    }.get(normalized, normalized)


def _root_entity_type(
    items: list[dict[str, Any]],
    *,
    context: ReviewGroupingContext,
) -> str:
    for item in items:
        entity_type = str(item.get("entity_type", "") or "").strip().lower()
        if entity_type in {"client", "listing"}:
            return entity_type
    if context.bundle_mode == "same_side_bundle":
        if context.topology_side == "listing_side":
            return "listing"
        return "client"
    return str(items[0].get("entity_type", "") or "").strip().lower() if items else ""


def _item_has_local_child_review(item: dict[str, Any]) -> bool:
    if bool(list(item.get("candidate_matches", []) or [])):
        return True
    if bool(list(item.get("blocking_reasons", []) or [])):
        return True
    if bool(item.get("immutable_conflict", False)):
        return True
    issue_group = str(item.get("issue_group", "") or "").strip().lower()
    if issue_group and issue_group != "parent_match_needed":
        return True
    return False


def _group_resolution_details(
    items: list[dict[str, Any]],
    *,
    group_kind: str,
    context: ReviewGroupingContext,
) -> tuple[bool, int, int, dict[str, Any]]:
    if not items:
        return False, 0, 0, {}
    root_entity_type = _root_entity_type(items, context=context)
    compatible_items = [
        item
        for item in items
        if not bool(list(item.get("blocking_reasons", []) or []))
        and not bool(item.get("immutable_conflict", False))
    ]
    if not compatible_items or group_kind in {"duplicate_conflict", "field_conflict"}:
        return False, 0, 0, {}
    topology_sides = {str(item.get("topology_side", "") or "").strip() for item in compatible_items}
    if len({value for value in topology_sides if value}) > 1:
        return False, 0, 0, {}
    root_items = [
        item
        for item in compatible_items
        if str(item.get("entity_type", "") or "").strip().lower() == root_entity_type
    ]
    resolution_items = root_items or compatible_items
    entity_types = {
        str(item.get("entity_type", "") or "").strip().lower() for item in resolution_items
    }
    existing_ids = {
        int(item.get("suggested_existing_id", 0) or 0)
        for item in resolution_items
        if int(item.get("suggested_existing_id", 0) or 0) > 0
    }
    suggested_actions = {
        _normalize_resolution_action(item.get("suggested_action", ""))
        for item in resolution_items
        if _normalize_resolution_action(item.get("suggested_action", ""))
    }
    if len(entity_types) > 1 or len(suggested_actions) > 1 or len(existing_ids) > 1:
        return False, len(compatible_items), 0, {}
    consistent_existing_id = next(iter(existing_ids)) if len(existing_ids) == 1 else 0
    suggested_action = next(iter(suggested_actions)) if suggested_actions else ""
    if not suggested_action:
        return False, len(compatible_items), consistent_existing_id, {}
    resolution_template: dict[str, Any] = {
        "action": suggested_action,
        "entity_type": root_entity_type,
    }
    if consistent_existing_id > 0:
        resolution_template["existing_id"] = consistent_existing_id
    apply_to_all_count = len(root_items or resolution_items)
    if context.bundle_mode == "same_side_bundle" and root_items:
        apply_to_all_count += sum(
            1
            for item in compatible_items
            if str(item.get("entity_type", "") or "").strip().lower() != root_entity_type
            and not _item_has_local_child_review(item)
        )
    return True, apply_to_all_count, consistent_existing_id, resolution_template


def build_review_group_payloads(
    *,
    review_rows: Iterable[Mapping[str, Any]],
    context: ReviewGroupingContext,
) -> list[ReviewGroupPayload]:
    normalized_rows: list[dict[str, Any]] = []
    grouped_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for raw_row in review_rows:
        row = dict(raw_row)
        row.setdefault("raw_data", dict(row.get("original", {}) or {}))
        row.setdefault("normalized_data", dict(row.get("data", {}) or {}))
        row.setdefault("inline_editable", True)
        row.setdefault("immutable_conflict", False)
        row.setdefault("review_fields", list(row.get("review_fields", []) or []))
        row.setdefault("candidate_matches", list(row.get("candidate_matches", []) or []))
        row.setdefault("recovered_fields", list(row.get("recovered_fields", []) or []))
        row.setdefault("recovery_candidates", list(row.get("recovery_candidates", []) or []))
        row.setdefault("blocking_reasons", list(row.get("blocking_reasons", []) or []))
        row.setdefault("quick_fix_actions", list(row.get("quick_fix_actions", []) or []))
        row.setdefault("bulk_fix_groups", list(row.get("bulk_fix_groups", []) or []))
        row.setdefault(
            "recoverability_class", str(row.get("recoverability_class", "") or "review_recoverable")
        )
        row.setdefault(
            "suggested_action", str(row.get("suggested_action", "") or "review_ambiguous")
        )
        row.setdefault("suggested_existing_id", int(row.get("suggested_existing_id", 0) or 0))
        row.setdefault("suggested_confidence", float(row.get("suggested_confidence", 0.0) or 0.0))
        row.setdefault("remarks", list(row.get("remarks", []) or []))
        row.setdefault("learning_signal_eligible", bool(row.get("learning_signal_eligible", True)))
        row.update(issue_metadata(row))
        normalized_rows.append(row)
        grouped_rows[root_group_key(review_row=row, context=context)].append(row)

    payloads: list[ReviewGroupPayload] = []
    for group_key, items in grouped_rows.items():
        sorted_items = sorted(items, key=lambda row: int(row.get("row", 0) or 0))
        representative = _group_representative_item(sorted_items, context=context)
        issue_group, issue_title, issue_summary = _dominant_issue(sorted_items)
        group_kind = _group_kind(group_key=group_key, items=sorted_items, context=context)
        topology_side = str(
            representative.get("topology_side", context.topology_side) or context.topology_side
        )
        entity_type = _root_entity_type(sorted_items, context=context)
        metadata = _group_metadata(sorted_items)
        (
            apply_to_all_allowed,
            apply_to_all_count,
            consistent_existing_id,
            resolution_template,
        ) = _group_resolution_details(
            sorted_items,
            group_kind=group_kind,
            context=context,
        )
        resolved_item_count = sum(
            1
            for item in sorted_items
            if str(item.get("status", "") or "") in {"resolved", "skipped"}
        )
        payloads.append(
            ReviewGroupPayload(
                group_key=group_key,
                group_kind=group_kind,
                issue_group=issue_group,
                issue_title=issue_title,
                issue_summary=issue_summary,
                entity_type=entity_type,
                topology_side=topology_side,
                root_identity=_root_identity(representative),
                root_label=_root_label([representative]),
                root_row_ordinal=int(representative.get("row", 0) or 0),
                suggested_group_action=_suggested_group_action(sorted_items, group_kind),
                status=_blocking_status(sorted_items),
                metadata=metadata,
                apply_to_all_allowed=apply_to_all_allowed,
                apply_to_all_count=apply_to_all_count,
                consistent_existing_id=consistent_existing_id,
                resolution_template=resolution_template,
                resolved_item_count=resolved_item_count,
                items=[dict(item) for item in sorted_items],
            )
        )
    return payloads


def build_grouped_review_payloads(
    *,
    review_rows: Iterable[Mapping[str, Any]],
    context: ReviewGroupingContext,
) -> list[ReviewGroupItemPayload]:
    payloads: list[ReviewGroupItemPayload] = []
    for group in build_review_group_payloads(review_rows=review_rows, context=context):
        for item in group.items:
            payloads.append(
                ReviewGroupItemPayload(
                    group_key=group.group_key,
                    group_kind=group.group_kind,
                    issue_group=group.issue_group,
                    issue_title=group.issue_title,
                    issue_summary=group.issue_summary,
                    entity_type=group.entity_type,
                    topology_side=group.topology_side,
                    root_identity=dict(group.root_identity),
                    root_label=group.root_label,
                    root_row_ordinal=group.root_row_ordinal,
                    suggested_group_action=group.suggested_group_action,
                    status=group.status,
                    metadata=dict(group.metadata),
                    apply_to_all_allowed=group.apply_to_all_allowed,
                    apply_to_all_count=group.apply_to_all_count,
                    consistent_existing_id=group.consistent_existing_id,
                    resolution_template=dict(group.resolution_template),
                    resolved_item_count=group.resolved_item_count,
                    item=dict(item),
                )
            )
    return payloads


__all__ = [
    "ReviewGroupingContext",
    "ReviewGroupPayload",
    "ReviewGroupItemPayload",
    "build_grouped_review_payloads",
    "build_review_group_payloads",
    "root_group_key",
]
