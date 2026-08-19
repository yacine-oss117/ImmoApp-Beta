"""DB-backed persistence and backfill for importer review state."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from typing import cast

from django.db import transaction
from django.utils import timezone

from server.imports.models import ImportJob, ImportReviewGroup, ImportReviewItem
from server.services.import_review_grouping import (
    ReviewGroupingContext,
    build_review_group_payloads,
)
from server.services.import_review_payloads import (
    extra_row_metadata,
    group_resolution_blockers,
    item_can_follow_group_resolution,
)
from server.services.import_review_queries import (
    ReviewCountSnapshot,
    compatibility_review_rows,
    review_count_snapshot,
)
from server.services.import_types import ReviewRowPayload
from server.services.json_safe import json_safe_value

_LEGACY_COMPATIBILITY_LIMIT = 25
_ACTIVE_ITEM_STATUSES = (
    ImportReviewItem.Status.PENDING,
    ImportReviewItem.Status.BLOCKED,
)
_GROUP_BULK_UPDATE_FIELDS = [
    "group_kind",
    "status",
    "issue_group",
    "issue_title",
    "issue_summary",
    "entity_type",
    "topology_side",
    "root_identity",
    "root_label",
    "root_row_ordinal",
    "item_count",
    "pending_item_count",
    "blocking_item_count",
    "suggested_group_action",
    "apply_to_all_allowed",
    "apply_to_all_count",
    "consistent_existing_id",
    "resolution_template",
    "resolved_item_count",
    "search_text",
    "metadata",
    "updated_at",
]
_ITEM_BULK_UPDATE_FIELDS = [
    "status",
    "blocking",
    "immutable_conflict",
    "suggested_action",
    "suggested_existing_id",
    "suggested_confidence",
    "recoverability_class",
    "raw_data",
    "normalized_data",
    "review_fields",
    "candidate_matches",
    "recovered_fields",
    "recovery_candidates",
    "blocking_reasons",
    "quick_fix_actions",
    "bulk_fix_groups",
    "resolution",
    "group_resolvable",
    "group_resolution_blockers",
    "resolution_source",
    "root_identity_snapshot",
    "metadata",
    "search_text",
    "issue_group",
    "issue_title",
    "issue_summary",
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


def _coerce_float(value: object, *, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return float(int(value))
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value.strip():
        try:
            return float(value)
        except ValueError:
            return default
    return default


def _as_dict(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, Mapping) else {}


def _as_list(value: object) -> list[object]:
    return list(value) if isinstance(value, list) else []


def _bundle_context(job: ImportJob) -> ReviewGroupingContext:
    inference = dict((job.inference_summary or {}).get("final_inference", {}) or {})
    bundle_mode = str(inference.get("bundle_mode", "single_entity") or "single_entity")
    topology_side = str(inference.get("topology_side_hint", "unknown") or "unknown")
    return ReviewGroupingContext(
        job_id=str(job.id),
        bundle_mode=bundle_mode,
        topology_side=topology_side,
    )


def _safe_review_rows(review_rows: Iterable[Mapping[str, object]]) -> list[dict[str, object]]:
    return [dict(row) for row in review_rows if isinstance(row, Mapping)]


def _item_status_from_row(row: Mapping[str, object]) -> str:
    status = str(row.get("status", "") or "").strip().lower()
    if status in {
        ImportReviewItem.Status.PENDING,
        ImportReviewItem.Status.RESOLVED,
        ImportReviewItem.Status.SKIPPED,
        ImportReviewItem.Status.BLOCKED,
    }:
        return status
    if bool(row.get("immutable_conflict", False)) or bool(
        _as_list(row.get("blocking_reasons", []))
    ):
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


def _search_fragments(*values: object) -> list[str]:
    fragments: list[str] = []
    for value in values:
        if isinstance(value, Mapping):
            fragments.extend(_search_fragments(*value.values()))
            continue
        if isinstance(value, list):
            fragments.extend(_search_fragments(*value))
            continue
        if value is None or value == "" or value == 0:
            continue
        text = str(value).strip().lower()
        if text:
            fragments.append(text)
    return fragments


def _dedupe_fragments(fragments: Iterable[str]) -> str:
    seen: set[str] = set()
    ordered: list[str] = []
    for fragment in fragments:
        normalized = str(fragment or "").strip().lower()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(normalized)
    return " ".join(ordered)


def _item_search_text(row: Mapping[str, object]) -> str:
    fragments: list[str] = []
    fragments.extend(
        _search_fragments(
            row.get("entity_type"),
            row.get("topology_side"),
            row.get("issue_group"),
            row.get("issue_title"),
            row.get("issue_summary"),
            row.get("suggested_action"),
            row.get("recoverability_class"),
        )
    )
    for key in ("normalized_data", "data", "raw_data", "original"):
        fragments.extend(_search_fragments(_as_dict(row.get(key, {}))))
    fragments.extend(_search_fragments(_as_list(row.get("remarks", []))))
    fragments.extend(_search_fragments(_as_list(row.get("blocking_reasons", []))))
    fragments.extend(_search_fragments(_as_list(row.get("review_fields", []))))
    fragments.extend(_search_fragments(_as_list(row.get("candidate_matches", []))))
    return _dedupe_fragments(fragments)


def _group_search_text(
    group_fields: Mapping[str, object], rows: Iterable[Mapping[str, object]]
) -> str:
    fragments: list[str] = []
    fragments.extend(
        _search_fragments(
            group_fields.get("group_key"),
            group_fields.get("group_kind"),
            group_fields.get("issue_group"),
            group_fields.get("issue_title"),
            group_fields.get("issue_summary"),
            group_fields.get("entity_type"),
            group_fields.get("topology_side"),
            group_fields.get("root_label"),
            group_fields.get("root_identity"),
        )
    )
    for row in rows:
        fragments.extend(_search_fragments(_item_search_text(row)))
    return _dedupe_fragments(fragments)


def _grouped_review_state(
    job: ImportJob,
    review_rows: Iterable[Mapping[str, object]],
) -> tuple[
    dict[str, list[dict[str, object]]], dict[str, dict[str, object]], int, dict[str, int], int
]:
    safe_rows = _safe_review_rows(review_rows)
    if not safe_rows:
        return {}, {}, 0, {}, 0

    from server.services.import_review_rescue import build_bulk_fix_groups, bulk_fix_groups_for_row

    bulk_fix_groups = build_bulk_fix_groups(cast(list[ReviewRowPayload], safe_rows))
    if bulk_fix_groups:
        for row in safe_rows:
            row["bulk_fix_groups"] = bulk_fix_groups_for_row(
                cast(ReviewRowPayload, row),
                bulk_fix_groups,
            )

    grouped_payloads = build_review_group_payloads(
        review_rows=safe_rows, context=_bundle_context(job)
    )
    groups_by_key: dict[str, list[dict[str, object]]] = defaultdict(list)
    group_meta: dict[str, dict[str, object]] = {}
    visible_review_count = 0
    issue_counts: dict[str, int] = {}
    conflict_count = 0

    for payload in grouped_payloads:
        for item in payload.items:
            item_row = dict(item)
            item_row.setdefault("status", _item_status_from_row(item_row))
            item_row.setdefault("metadata", extra_row_metadata(item_row))
            groups_by_key[payload.group_key].append(item_row)
        group_meta.setdefault(
            payload.group_key,
            {
                "group_key": payload.group_key,
                "group_kind": payload.group_kind,
                "issue_group": payload.issue_group,
                "issue_title": payload.issue_title,
                "issue_summary": payload.issue_summary,
                "entity_type": payload.entity_type,
                "topology_side": payload.topology_side,
                "root_identity": dict(payload.root_identity),
                "root_label": payload.root_label,
                "root_row_ordinal": int(payload.root_row_ordinal),
                "suggested_group_action": payload.suggested_group_action,
                "apply_to_all_allowed": bool(payload.apply_to_all_allowed),
                "apply_to_all_count": int(payload.apply_to_all_count),
                "consistent_existing_id": int(payload.consistent_existing_id),
                "resolution_template": dict(payload.resolution_template),
                "metadata": dict(payload.metadata),
            },
        )
        for item_row in groups_by_key[payload.group_key]:
            item_status = str(
                item_row.get("status", ImportReviewItem.Status.PENDING)
                or ImportReviewItem.Status.PENDING
            )
            if item_status in _ACTIVE_ITEM_STATUSES:
                visible_review_count += 1
                issue_group = str(item_row.get("issue_group", "other") or "other")
                issue_counts[issue_group] = issue_counts.get(issue_group, 0) + 1
                if bool(item_row.get("immutable_conflict", False)):
                    conflict_count += 1

    return groups_by_key, group_meta, visible_review_count, issue_counts, conflict_count


def _group_record_fields(
    *,
    grouped_rows: list[dict[str, object]],
    meta: Mapping[str, object],
) -> dict[str, object]:
    item_count = len(grouped_rows)
    pending_item_count = sum(
        1 for row in grouped_rows if str(row.get("status", "") or "") in _ACTIVE_ITEM_STATUSES
    )
    blocking_item_count = sum(
        1
        for row in grouped_rows
        if str(row.get("status", "") or "") == ImportReviewItem.Status.BLOCKED
        or bool(row.get("immutable_conflict", False))
        or bool(_as_list(row.get("blocking_reasons", [])))
    )
    resolved_item_count = sum(
        1
        for row in grouped_rows
        if str(row.get("status", "") or "")
        in {ImportReviewItem.Status.RESOLVED, ImportReviewItem.Status.SKIPPED}
    )
    return {
        "group_kind": str(
            meta.get("group_kind", ImportReviewGroup.Kind.SINGLE_ROW)
            or ImportReviewGroup.Kind.SINGLE_ROW
        ),
        "status": _group_status(
            item_count=item_count,
            pending_item_count=pending_item_count,
            blocking_item_count=blocking_item_count,
            resolved_item_count=resolved_item_count,
        ),
        "issue_group": str(meta.get("issue_group", "other") or "other"),
        "issue_title": str(meta.get("issue_title", "Needs attention") or "Needs attention"),
        "issue_summary": str(
            meta.get("issue_summary", "This group needs a quick review before we continue.")
            or "This group needs a quick review before we continue."
        ),
        "entity_type": str(meta.get("entity_type", "") or ""),
        "topology_side": str(meta.get("topology_side", "") or ""),
        "root_identity": _as_dict(meta.get("root_identity", {})),
        "root_label": str(meta.get("root_label", "") or ""),
        "root_row_ordinal": _coerce_int(meta.get("root_row_ordinal", 0)),
        "item_count": item_count,
        "pending_item_count": pending_item_count,
        "blocking_item_count": blocking_item_count,
        "suggested_group_action": str(meta.get("suggested_group_action", "") or ""),
        "apply_to_all_allowed": bool(meta.get("apply_to_all_allowed", False)),
        "apply_to_all_count": _coerce_int(meta.get("apply_to_all_count", 0)),
        "consistent_existing_id": _coerce_int(meta.get("consistent_existing_id", 0)),
        "resolution_template": cast(
            dict[str, object], json_safe_value(_as_dict(meta.get("resolution_template", {})))
        ),
        "resolved_item_count": resolved_item_count,
        "metadata": cast(dict[str, object], json_safe_value(_as_dict(meta.get("metadata", {})))),
        "search_text": _group_search_text(meta, grouped_rows),
    }


def _item_record_fields(
    *,
    row: Mapping[str, object],
    group_payload: Mapping[str, object],
) -> dict[str, object]:
    item_status = _item_status_from_row(row)
    metadata = extra_row_metadata(row)
    group_resolvable = item_can_follow_group_resolution(row, group_payload=group_payload)
    blockers = group_resolution_blockers(row, group_payload=group_payload)
    root_identity_snapshot = _as_dict(row.get("root_identity_snapshot", {}))
    return {
        "row_ordinal": _coerce_int(row.get("row", 0)),
        "entity_type": str(row.get("entity_type", "") or ""),
        "topology_side": str(row.get("topology_side", "") or ""),
        "issue_group": str(row.get("issue_group", "other") or "other"),
        "issue_title": str(row.get("issue_title", "Needs attention") or "Needs attention"),
        "issue_summary": str(
            row.get("issue_summary", "This line needs a quick review before we continue.")
            or "This line needs a quick review before we continue."
        ),
        "status": item_status,
        "blocking": bool(item_status == ImportReviewItem.Status.BLOCKED),
        "immutable_conflict": bool(row.get("immutable_conflict", False)),
        "suggested_action": str(row.get("suggested_action", "") or ""),
        "suggested_existing_id": _coerce_int(row.get("suggested_existing_id", 0)),
        "suggested_confidence": _coerce_float(row.get("suggested_confidence", 0.0)),
        "recoverability_class": str(
            row.get("recoverability_class", "review_recoverable") or "review_recoverable"
        ),
        "raw_data": cast(
            dict[str, object],
            json_safe_value(_as_dict(row.get("raw_data", row.get("original", {})))),
        ),
        "normalized_data": cast(
            dict[str, object],
            json_safe_value(_as_dict(row.get("normalized_data", row.get("data", {})))),
        ),
        "review_fields": cast(
            list[object], json_safe_value(_as_list(row.get("review_fields", [])))
        ),
        "candidate_matches": cast(
            list[object], json_safe_value(_as_list(row.get("candidate_matches", [])))
        ),
        "recovered_fields": cast(
            list[object], json_safe_value(_as_list(row.get("recovered_fields", [])))
        ),
        "recovery_candidates": cast(
            list[object], json_safe_value(_as_list(row.get("recovery_candidates", [])))
        ),
        "blocking_reasons": cast(
            list[object], json_safe_value(_as_list(row.get("blocking_reasons", [])))
        ),
        "quick_fix_actions": cast(
            list[object], json_safe_value(_as_list(row.get("quick_fix_actions", [])))
        ),
        "bulk_fix_groups": cast(
            list[object], json_safe_value(_as_list(row.get("bulk_fix_groups", [])))
        ),
        "resolution": {},
        "group_resolvable": bool(group_resolvable),
        "group_resolution_blockers": cast(list[object], json_safe_value(list(blockers))),
        "resolution_source": "",
        "root_identity_snapshot": cast(dict[str, object], json_safe_value(root_identity_snapshot)),
        "metadata": cast(dict[str, object], json_safe_value(metadata)),
        "search_text": _item_search_text(row),
    }


def _sync_group_instance(group: ImportReviewGroup, desired_fields: Mapping[str, object]) -> bool:
    changed = False
    for field_name, value in desired_fields.items():
        if getattr(group, field_name) != value:
            setattr(group, field_name, value)
            changed = True
    return changed


def _sync_item_instance(item: ImportReviewItem, desired_fields: Mapping[str, object]) -> bool:
    changed = False
    for field_name, value in desired_fields.items():
        if getattr(item, field_name) != value:
            setattr(item, field_name, value)
            changed = True
    return changed


def _active_rows_from_legacy(session: object) -> list[dict[str, object]]:
    return [
        dict(row)
        for row in list(getattr(session, "review_rows", []) or [])
        if isinstance(row, Mapping)
    ]


def clear_db_review_state(job: ImportJob) -> None:
    ImportReviewItem.objects.filter(job=job).delete()
    ImportReviewGroup.objects.filter(job=job).delete()


def persist_review_rows(
    *,
    job: ImportJob,
    review_rows: list[dict[str, object]],
) -> ReviewCountSnapshot:
    groups_by_key, group_meta, visible_review_count, issue_counts, conflict_count = (
        _grouped_review_state(job, review_rows)
    )
    if not groups_by_key:
        clear_db_review_state(job)
        return ReviewCountSnapshot(
            visible_review_count=0,
            pending_group_count=0,
            conflict_count=0,
            issue_counts={},
        )

    now = timezone.now()
    desired_group_keys = set(groups_by_key)
    existing_groups = {
        str(group.group_key): group for group in ImportReviewGroup.objects.filter(job=job)
    }
    stale_group_keys = [key for key in existing_groups if key not in desired_group_keys]
    if stale_group_keys:
        ImportReviewGroup.objects.filter(job=job, group_key__in=stale_group_keys).delete()
        for group_key in stale_group_keys:
            existing_groups.pop(group_key, None)

    groups_to_create: list[ImportReviewGroup] = []
    groups_to_update: list[ImportReviewGroup] = []
    for group_key, grouped_rows in groups_by_key.items():
        desired_fields = _group_record_fields(grouped_rows=grouped_rows, meta=group_meta[group_key])
        existing_group = existing_groups.get(group_key)
        if existing_group is None:
            groups_to_create.append(
                ImportReviewGroup(
                    job=job,
                    group_key=group_key,
                    created_at=now,
                    updated_at=now,
                    **desired_fields,
                )
            )
            continue
        if _sync_group_instance(existing_group, desired_fields):
            existing_group.updated_at = now
            groups_to_update.append(existing_group)
    if groups_to_create:
        ImportReviewGroup.objects.bulk_create(groups_to_create)
    if groups_to_update:
        ImportReviewGroup.objects.bulk_update(groups_to_update, _GROUP_BULK_UPDATE_FIELDS)

    refreshed_groups = {
        str(group.group_key): group
        for group in ImportReviewGroup.objects.filter(job=job, group_key__in=desired_group_keys)
    }
    existing_items = {
        (
            str(item.group.group_key),
            int(item.row_ordinal or 0),
            str(item.entity_type or ""),
        ): item
        for item in ImportReviewItem.objects.filter(
            job=job,
            group__group_key__in=desired_group_keys,
        ).select_related("group")
    }

    desired_item_keys: set[tuple[str, int, str]] = set()
    items_to_create: list[ImportReviewItem] = []
    items_to_update: list[ImportReviewItem] = []
    for group_key, grouped_rows in groups_by_key.items():
        group = refreshed_groups[group_key]
        group_payload = {
            "group_key": group_key,
            "entity_type": group.entity_type,
            "apply_to_all_allowed": bool(group.apply_to_all_allowed),
            "apply_to_all_count": int(group.apply_to_all_count or 0),
        }
        for row in grouped_rows:
            row_num = _coerce_int(row.get("row", 0))
            entity_type = str(row.get("entity_type", "") or "")
            item_key = (group_key, row_num, entity_type)
            desired_item_keys.add(item_key)
            desired_fields = _item_record_fields(row=row, group_payload=group_payload)
            existing_item = existing_items.get(item_key)
            if existing_item is None:
                items_to_create.append(
                    ImportReviewItem(
                        job=job,
                        group=group,
                        created_at=now,
                        updated_at=now,
                        **desired_fields,
                    )
                )
                continue
            if int(existing_item.group.id) != int(group.id):
                existing_item.group = group
                desired_fields = dict(desired_fields)
                desired_fields["group"] = group
            if _sync_item_instance(existing_item, desired_fields):
                existing_item.updated_at = now
                items_to_update.append(existing_item)
    stale_item_ids = [
        item.id for item_key, item in existing_items.items() if item_key not in desired_item_keys
    ]
    if stale_item_ids:
        ImportReviewItem.objects.filter(id__in=stale_item_ids).delete()
    if items_to_create:
        ImportReviewItem.objects.bulk_create(items_to_create)
    if items_to_update:
        ImportReviewItem.objects.bulk_update(items_to_update, _ITEM_BULK_UPDATE_FIELDS)

    return ReviewCountSnapshot(
        visible_review_count=visible_review_count,
        pending_group_count=len(groups_by_key),
        conflict_count=conflict_count,
        issue_counts=issue_counts,
    )


def persist_review_state_with_compatibility_sample(
    *,
    job: ImportJob,
    review_rows: list[dict[str, object]],
) -> ReviewCountSnapshot:
    with transaction.atomic():
        snapshot = persist_review_rows(job=job, review_rows=review_rows)
        summary = dict(job.result_summary or {})
        summary["review_storage_mode"] = "db_paged_v2"
        summary["review_pending_group_count"] = int(snapshot.pending_group_count or 0)
        job.result_summary = cast(dict[str, object], json_safe_value(summary))
        job.review_rows = compatibility_review_rows(job, limit=_LEGACY_COMPATIBILITY_LIMIT)
        job.save(update_fields=["review_rows", "result_summary", "updated_at"])
    return snapshot


def backfill_legacy_review_state(job: ImportJob) -> ReviewCountSnapshot:
    legacy_rows = _active_rows_from_legacy(job)
    if legacy_rows:
        return persist_review_state_with_compatibility_sample(job=job, review_rows=legacy_rows)
    clear_db_review_state(job)
    return ReviewCountSnapshot(
        visible_review_count=0,
        pending_group_count=0,
        conflict_count=0,
        issue_counts={},
    )


def ensure_review_state(session: object) -> ReviewCountSnapshot | None:
    if isinstance(session, ImportJob):
        if ImportReviewItem.objects.filter(job=session).exists():
            return review_count_snapshot(session)
        legacy_rows = _active_rows_from_legacy(session)
        if legacy_rows:
            return backfill_legacy_review_state(session)
        return None

    legacy_rows = _active_rows_from_legacy(session)
    if not legacy_rows:
        return None
    visible_review_count = len(legacy_rows)
    issue_counts: dict[str, int] = {}
    conflict_count = 0
    for row in legacy_rows:
        issue_group = str(row.get("issue_group", "other") or "other")
        issue_counts[issue_group] = issue_counts.get(issue_group, 0) + 1
        if bool(row.get("immutable_conflict", False)):
            conflict_count += 1
    return ReviewCountSnapshot(
        visible_review_count=visible_review_count,
        pending_group_count=visible_review_count,
        conflict_count=conflict_count,
        issue_counts=issue_counts,
    )


__all__ = [
    "backfill_legacy_review_state",
    "clear_db_review_state",
    "ensure_review_state",
    "persist_review_rows",
    "persist_review_state_with_compatibility_sample",
]
