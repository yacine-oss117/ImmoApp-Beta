"""Resolution-state mutations for DB-backed importer review items and groups."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import cast

from django.utils import timezone

from server.imports.models import ImportJob, ImportReviewGroup, ImportReviewItem
from server.services.import_parsers import normalize_import_entity_type
from server.services.import_review_payloads import (
    effective_resolution_payload,
    normalize_resolution_action,
)
from server.services.import_review_shapes import review_row_key
from server.services.import_types import ReviewResolutionPayload
from server.services.json_safe import json_safe_value

_ACTIVE_ITEM_STATUSES = (
    ImportReviewItem.Status.PENDING,
    ImportReviewItem.Status.BLOCKED,
)
_ITEM_RESOLUTION_UPDATE_FIELDS = [
    "resolution",
    "resolution_source",
    "status",
    "blocking",
    "resolved_at",
    "updated_at",
]


def _coerce_int(value: object, *, default: int = 0) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str) and value.strip():
        try:
            return int(value)
        except ValueError:
            return default
    return default


def _as_dict(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, Mapping) else {}


def _item_status_from_row(row: Mapping[str, object]) -> str:
    status = str(row.get("status", "") or "").strip().lower()
    if status in {
        ImportReviewItem.Status.PENDING,
        ImportReviewItem.Status.RESOLVED,
        ImportReviewItem.Status.SKIPPED,
        ImportReviewItem.Status.BLOCKED,
    }:
        return status
    if bool(row.get("immutable_conflict", False)) or bool(row.get("blocking_reasons", [])):
        return ImportReviewItem.Status.BLOCKED
    return ImportReviewItem.Status.PENDING


def _group_status(
    *,
    item_count: int,
    pending_item_count: int,
    blocking_item_count: int,
    resolved_item_count: int,
) -> str:
    if item_count <= 0 or pending_item_count <= 0:
        return ImportReviewGroup.Status.RESOLVED
    if resolved_item_count > 0:
        return ImportReviewGroup.Status.PARTIALLY_RESOLVED
    if blocking_item_count >= pending_item_count:
        return ImportReviewGroup.Status.BLOCKED
    return ImportReviewGroup.Status.PENDING


def apply_group_resolution_templates(
    *,
    job: ImportJob,
    group_decisions: Mapping[str, Mapping[str, object]],
) -> None:
    if not group_decisions:
        return

    now = timezone.now()
    groups_to_update: list[ImportReviewGroup] = []
    for group in ImportReviewGroup.objects.filter(
        job=job, group_key__in=list(group_decisions.keys())
    ):
        raw_decision = _as_dict(group_decisions.get(str(group.group_key), {}))
        action = normalize_resolution_action(raw_decision.get("action", ""))
        entity_type = normalize_import_entity_type(
            str(raw_decision.get("entity_type", group.entity_type) or group.entity_type)
        ) or str(group.entity_type or "")
        scope = str(
            raw_decision.get("scope", "apply_to_all_pending_items") or "apply_to_all_pending_items"
        ).strip()

        resolution_template: ReviewResolutionPayload = {}
        if action:
            resolution_template["action"] = action
            resolution_template["entity_type"] = entity_type
        existing_id = _coerce_int(raw_decision.get("existing_id", 0))
        if existing_id > 0:
            resolution_template["existing_id"] = existing_id

        metadata = dict(group.metadata or {})
        metadata["resolution_scope"] = scope
        if group.metadata != metadata or dict(group.resolution_template or {}) != dict(
            resolution_template
        ):
            group.metadata = cast(dict[str, object], json_safe_value(metadata))
            group.resolution_template = cast(
                dict[str, object], json_safe_value(dict(resolution_template))
            )
            group.updated_at = now
            groups_to_update.append(group)
    if groups_to_update:
        ImportReviewGroup.objects.bulk_update(
            groups_to_update,
            ["metadata", "resolution_template", "updated_at"],
        )


def _recompute_group_state(*, group_ids: Iterable[int]) -> None:
    resolved_group_ids = sorted({int(group_id) for group_id in group_ids if int(group_id) > 0})
    if not resolved_group_ids:
        return

    groups = {
        int(group.id): group
        for group in ImportReviewGroup.objects.filter(id__in=resolved_group_ids)
    }
    if not groups:
        return

    items_by_group: dict[int, list[ImportReviewItem]] = {}
    for item in ImportReviewItem.objects.filter(group_id__in=resolved_group_ids).select_related(
        "group"
    ):
        items_by_group.setdefault(int(item.group.id), []).append(item)

    now = timezone.now()
    groups_to_update: list[ImportReviewGroup] = []
    for group_id, group in groups.items():
        items = items_by_group.get(group_id, [])
        item_count = len(items)
        pending_item_count = sum(
            1 for item in items if str(item.status or "") in _ACTIVE_ITEM_STATUSES
        )
        blocking_item_count = sum(
            1
            for item in items
            if str(item.status or "") == ImportReviewItem.Status.BLOCKED
            or bool(item.immutable_conflict)
            or bool(item.blocking)
        )
        resolved_item_count = sum(
            1
            for item in items
            if str(item.status or "")
            in {ImportReviewItem.Status.RESOLVED, ImportReviewItem.Status.SKIPPED}
        )
        desired_status = _group_status(
            item_count=item_count,
            pending_item_count=pending_item_count,
            blocking_item_count=blocking_item_count,
            resolved_item_count=resolved_item_count,
        )
        changed = False
        for field_name, value in {
            "item_count": item_count,
            "pending_item_count": pending_item_count,
            "blocking_item_count": blocking_item_count,
            "resolved_item_count": resolved_item_count,
            "status": desired_status,
        }.items():
            if getattr(group, field_name) != value:
                setattr(group, field_name, value)
                changed = True
        if changed:
            group.updated_at = now
            groups_to_update.append(group)
    if groups_to_update:
        ImportReviewGroup.objects.bulk_update(
            groups_to_update,
            [
                "item_count",
                "pending_item_count",
                "blocking_item_count",
                "resolved_item_count",
                "status",
                "updated_at",
            ],
        )


def apply_item_resolutions(
    *,
    job: ImportJob,
    item_decisions: Mapping[str, Mapping[str, object]],
    skip_item_ids: list[int] | None = None,
) -> None:
    raw_item_ids = {_coerce_int(item_id) for item_id in item_decisions.keys()}
    skip_ids = {_coerce_int(item_id) for item_id in (skip_item_ids or [])}
    target_ids = sorted({item_id for item_id in [*raw_item_ids, *skip_ids] if item_id > 0})
    if not target_ids:
        return

    now = timezone.now()
    items = list(
        ImportReviewItem.objects.filter(job=job, id__in=target_ids).select_related("group")
    )
    if not items:
        return

    items_to_update: list[ImportReviewItem] = []
    affected_group_ids: set[int] = set()
    for item in items:
        decision = _as_dict(item_decisions.get(str(item.id), {}))
        action = normalize_resolution_action(decision.get("action", ""))
        entity_type = normalize_import_entity_type(
            str(decision.get("entity_type", item.entity_type) or item.entity_type)
        ) or str(item.entity_type or "")
        if int(item.id) in skip_ids and not action:
            action = "skip"
        if not action:
            continue

        resolution: ReviewResolutionPayload = {"action": action, "entity_type": entity_type}
        existing_id = _coerce_int(decision.get("existing_id", 0))
        row_version = _coerce_int(decision.get("row_version", 0))
        if existing_id > 0:
            resolution["existing_id"] = existing_id
        if row_version > 0:
            resolution["row_version"] = row_version

        if action == "skip":
            next_status = str(ImportReviewItem.Status.SKIPPED)
            resolved_at = now
        elif action in {"create_new", "update_existing"}:
            next_status = str(ImportReviewItem.Status.RESOLVED)
            resolved_at = now
        else:
            next_status = _item_status_from_row(
                {
                    "immutable_conflict": item.immutable_conflict,
                    "blocking_reasons": list(item.blocking_reasons or []),
                }
            )
            resolved_at = None

        if (
            dict(item.resolution or {}) != dict(resolution)
            or str(item.resolution_source or "") != "item"
            or str(item.status or "") != next_status
            or bool(item.blocking) != bool(next_status == ImportReviewItem.Status.BLOCKED)
            or item.resolved_at != resolved_at
        ):
            item.resolution = cast(dict[str, object], json_safe_value(dict(resolution)))
            item.resolution_source = "item"
            item.status = next_status
            item.blocking = bool(next_status == ImportReviewItem.Status.BLOCKED)
            item.resolved_at = resolved_at
            item.updated_at = now
            items_to_update.append(item)
            affected_group_ids.add(int(item.group.id))
    if items_to_update:
        ImportReviewItem.objects.bulk_update(items_to_update, _ITEM_RESOLUTION_UPDATE_FIELDS)
        _recompute_group_state(group_ids=affected_group_ids)


def build_effective_submit_payload(
    job: ImportJob,
    *,
    active_items: list[ImportReviewItem] | None = None,
) -> tuple[dict[str, dict[str, object]], dict[str, ReviewResolutionPayload], list[str]]:
    corrections: dict[str, dict[str, object]] = {}
    decisions: dict[str, ReviewResolutionPayload] = {}
    skip_rows: list[str] = []
    resolved_items = (
        list(active_items)
        if active_items is not None
        else list(
            ImportReviewItem.objects.filter(
                job=job, status__in=_ACTIVE_ITEM_STATUSES
            ).select_related("group")
        )
    )
    for item in resolved_items:
        payload = effective_resolution_payload(item)
        if not payload:
            payload = {
                "action": "review_ambiguous",
                "entity_type": str(item.entity_type or ""),
            }
        action = normalize_resolution_action(payload.get("action", ""))
        normalized_payload = cast(ReviewResolutionPayload, dict(payload))
        normalized_payload["action"] = action
        normalized_payload.setdefault("entity_type", str(item.entity_type or ""))
        row_token = review_row_key(
            row_num=int(item.row_ordinal or 0),
            entity_type=str(item.entity_type or ""),
        )
        if action == "skip":
            skip_rows.append(row_token)
        decisions[row_token] = normalized_payload
    return corrections, decisions, sorted(set(skip_rows))


__all__ = [
    "apply_group_resolution_templates",
    "apply_item_resolutions",
    "build_effective_submit_payload",
]
