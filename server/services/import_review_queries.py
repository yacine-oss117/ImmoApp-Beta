"""Read-side helpers for importer review state."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

from django.core.paginator import EmptyPage, Paginator
from django.db.models import Case, Count, IntegerField, Q, QuerySet, Value, When

from server.imports.models import ImportJob, ImportReviewGroup, ImportReviewItem
from server.services.import_review_compatibility import build_compatibility_review_row
from server.services.import_review_metadata_safety import project_review_metadata
from server.services.import_review_payloads import effective_resolution_payload
from server.services.import_review_shapes import review_row_lookup_keys
from server.services.import_types import ReviewGroupPayload, ReviewPagePayload, ReviewRowPayload
from server.services.import_ui_summary import issue_metadata

_LEGACY_COMPATIBILITY_LIMIT = 25
_ACTIVE_ITEM_STATUSES = (
    ImportReviewItem.Status.PENDING,
    ImportReviewItem.Status.BLOCKED,
)
_ACTIVE_GROUP_STATUSES = (
    ImportReviewGroup.Status.PENDING,
    ImportReviewGroup.Status.BLOCKED,
    ImportReviewGroup.Status.PARTIALLY_RESOLVED,
)


@dataclass(frozen=True)
class ReviewCountSnapshot:
    visible_review_count: int
    pending_group_count: int
    conflict_count: int
    issue_counts: dict[str, int]


def review_group_queryset(job: ImportJob) -> QuerySet[ImportReviewGroup]:
    return ImportReviewGroup.objects.filter(job=job)


def review_item_queryset(job: ImportJob) -> QuerySet[ImportReviewItem]:
    return ImportReviewItem.objects.filter(job=job).select_related("group")


def has_db_review_state(job: ImportJob) -> bool:
    return bool(review_item_queryset(job).exists())


def review_count_snapshot(job: ImportJob) -> ReviewCountSnapshot:
    active_items = review_item_queryset(job).filter(status__in=_ACTIVE_ITEM_STATUSES)
    active_groups = review_group_queryset(job).filter(status__in=_ACTIVE_GROUP_STATUSES)
    issue_counts = {
        str(row["issue_group"]): int(row["count"])
        for row in active_items.values("issue_group").annotate(count=Count("id"))
    }
    return ReviewCountSnapshot(
        visible_review_count=int(active_items.count()),
        pending_group_count=int(active_groups.count()),
        conflict_count=int(active_items.filter(immutable_conflict=True).count()),
        issue_counts=issue_counts,
    )


def active_review_items(
    job: ImportJob,
    *,
    group_key: str | None = None,
    include_item_resolutions: bool = False,
) -> list[ImportReviewItem]:
    queryset = review_item_queryset(job)
    if include_item_resolutions:
        queryset = queryset.filter(
            Q(status__in=_ACTIVE_ITEM_STATUSES) | Q(resolution_source="item")
        )
        if group_key:
            queryset = queryset.filter(group__group_key=str(group_key))
        queryset = queryset.order_by("group__root_row_ordinal", "row_ordinal", "id")
    else:
        queryset = apply_review_item_filters(
            queryset,
            group_key=group_key,
            issue_group=None,
            search="",
            pending_only=True,
        )
    return list(queryset)


def compatibility_review_rows(
    job: ImportJob, *, limit: int = _LEGACY_COMPATIBILITY_LIMIT
) -> list[ReviewRowPayload]:
    items = list(
        review_item_queryset(job)
        .filter(status__in=_ACTIVE_ITEM_STATUSES)
        .order_by("row_ordinal", "id")[: max(1, int(limit))]
    )
    if items:
        return [build_compatibility_review_row(item) for item in items]
    return [
        cast(ReviewRowPayload, dict(row))
        for row in list(job.review_rows or [])[: max(1, int(limit))]
        if isinstance(row, Mapping)
    ]


def apply_review_group_filters(
    queryset: QuerySet[ImportReviewGroup],
    *,
    issue_group: str | None,
    search: str,
    pending_only: bool,
) -> QuerySet[ImportReviewGroup]:
    filtered = queryset
    if pending_only:
        filtered = filtered.filter(status__in=_ACTIVE_GROUP_STATUSES)
    if issue_group and issue_group != "all":
        filtered = filtered.filter(issue_group=str(issue_group))
    search_text = str(search or "").strip()
    if search_text:
        filtered = filtered.filter(search_text__icontains=search_text)
    return filtered.annotate(
        duplicate_priority=Case(
            When(group_kind=ImportReviewGroup.Kind.DUPLICATE_CONFLICT, then=Value(1)),
            default=Value(0),
            output_field=IntegerField(),
        )
    ).order_by(
        "-blocking_item_count",
        "-duplicate_priority",
        "-pending_item_count",
        "root_row_ordinal",
        "group_key",
    )


def apply_review_item_filters(
    queryset: QuerySet[ImportReviewItem],
    *,
    group_key: str | None,
    issue_group: str | None,
    search: str,
    pending_only: bool,
) -> QuerySet[ImportReviewItem]:
    filtered = queryset
    if pending_only:
        filtered = filtered.filter(status__in=_ACTIVE_ITEM_STATUSES)
    if group_key:
        filtered = filtered.filter(group__group_key=str(group_key))
    if issue_group and issue_group != "all":
        filtered = filtered.filter(issue_group=str(issue_group))
    search_text = str(search or "").strip()
    if search_text:
        filtered = filtered.filter(
            Q(search_text__icontains=search_text) | Q(group__search_text__icontains=search_text)
        )
    return filtered.order_by("group__root_row_ordinal", "row_ordinal", "id")


def paged_review_groups(
    *,
    job: ImportJob,
    page: int,
    page_size: int,
    issue_group: str | None,
    search: str,
    pending_only: bool,
) -> tuple[list[ReviewGroupPayload], ReviewPagePayload]:
    queryset = apply_review_group_filters(
        review_group_queryset(job),
        issue_group=issue_group,
        search=search,
        pending_only=pending_only,
    )
    paginator = Paginator(queryset, max(1, min(int(page_size or 50), 200)))
    if paginator.count <= 0:
        return [], {
            "page": 1,
            "page_size": int(paginator.per_page),
            "total_items": 0,
            "total_pages": 1,
            "has_next": False,
            "has_prev": False,
        }
    try:
        page_obj = paginator.page(max(1, int(page or 1)))
    except EmptyPage:
        page_obj = paginator.page(max(1, paginator.num_pages))
    groups: list[ReviewGroupPayload] = [
        {
            "group_key": str(group.group_key),
            "group_kind": str(group.group_kind),
            "issue_group": str(group.issue_group or "other"),
            "issue_title": str(group.issue_title or "Needs attention"),
            "issue_summary": str(
                group.issue_summary or "This group needs a quick review before we continue."
            ),
            "entity_type": str(group.entity_type or ""),
            "topology_side": str(group.topology_side or ""),
            "root_label": str(group.root_label or ""),
            "root_identity": dict(group.root_identity or {}),
            "item_count": int(group.item_count or 0),
            "pending_item_count": int(group.pending_item_count or 0),
            "blocking_item_count": int(group.blocking_item_count or 0),
            "suggested_group_action": str(group.suggested_group_action or ""),
            "status": str(group.status or ImportReviewGroup.Status.PENDING),
            "sample_rows": list((group.metadata or {}).get("sample_rows", []) or []),
            "apply_to_all_allowed": bool(group.apply_to_all_allowed),
            "apply_to_all_count": int(group.apply_to_all_count or 0),
            "consistent_existing_id": (int(group.consistent_existing_id or 0) or None),
            "resolution_template": dict(group.resolution_template or {}),
            "resolved_item_count": int(group.resolved_item_count or 0),
            "metadata": dict(group.metadata or {}),
        }
        for group in list(page_obj.object_list)
    ]
    return groups, {
        "page": int(page_obj.number),
        "page_size": int(page_obj.paginator.per_page),
        "total_items": int(page_obj.paginator.count),
        "total_pages": int(page_obj.paginator.num_pages),
        "has_next": bool(page_obj.has_next()),
        "has_prev": bool(page_obj.has_previous()),
    }


def paged_review_items(
    *,
    job: ImportJob,
    page: int,
    page_size: int,
    group_key: str | None,
    issue_group: str | None,
    search: str,
    pending_only: bool,
) -> tuple[list[ReviewRowPayload], ReviewPagePayload]:
    queryset = apply_review_item_filters(
        review_item_queryset(job),
        group_key=group_key,
        issue_group=issue_group,
        search=search,
        pending_only=pending_only,
    )
    paginator = Paginator(queryset, max(1, min(int(page_size or 50), 200)))
    if paginator.count <= 0:
        return [], {
            "page": 1,
            "page_size": int(paginator.per_page),
            "total_items": 0,
            "total_pages": 1,
            "has_next": False,
            "has_prev": False,
        }
    try:
        page_obj = paginator.page(max(1, int(page or 1)))
    except EmptyPage:
        page_obj = paginator.page(max(1, paginator.num_pages))
    items: list[ReviewRowPayload] = [
        {
            "item_id": int(item.id),
            "group_key": str(item.group.group_key),
            "row": int(item.row_ordinal or 0),
            "entity_type": str(item.entity_type or ""),
            "topology_side": str(item.topology_side or ""),
            "issue_group": str(item.issue_group or "other"),
            "issue_title": str(item.issue_title or "Needs attention"),
            "issue_summary": str(
                item.issue_summary or "This line needs a quick review before we continue."
            ),
            "raw_data": dict(item.raw_data or {}),
            "normalized_data": dict(item.normalized_data or {}),
            "candidate_matches": list(item.candidate_matches or []),
            "review_fields": list(item.review_fields or []),
            "recovered_fields": list(item.recovered_fields or []),
            "recovery_candidates": list(item.recovery_candidates or []),
            "blocking_reasons": list(item.blocking_reasons or []),
            "suggested_action": str(item.suggested_action or ""),
            "suggested_existing_id": int(item.suggested_existing_id or 0),
            "suggested_confidence": float(item.suggested_confidence or 0.0),
            "quick_fix_actions": list(item.quick_fix_actions or []),
            "bulk_fix_groups": list(item.bulk_fix_groups or []),
            "inline_editable": True,
            "immutable_conflict": bool(item.immutable_conflict),
            "recoverability_class": str(item.recoverability_class or "review_recoverable"),
            "status": str(item.status or ImportReviewItem.Status.PENDING),
            "group_resolvable": bool(item.group_resolvable),
            "group_resolution_blockers": list(item.group_resolution_blockers or []),
            "resolution_source": str(item.resolution_source or ""),
            "effective_action": (
                str(effective_resolution_payload(item).get("action", "") or "") or None
            ),
            "metadata": dict(item.metadata or {}),
        }
        for item in list(page_obj.object_list)
    ]
    for index, item in enumerate(items):
        normalized_item = cast(dict[str, object], dict(item))
        normalized_item.update(issue_metadata(normalized_item))
        metadata_payload = normalized_item.pop("metadata", {})
        items[index] = cast(
            ReviewRowPayload,
            project_review_metadata(normalized_item, metadata_payload),
        )
    return items, {
        "page": int(page_obj.number),
        "page_size": int(page_obj.paginator.per_page),
        "total_items": int(page_obj.paginator.count),
        "total_pages": int(page_obj.paginator.num_pages),
        "has_next": bool(page_obj.has_next()),
        "has_prev": bool(page_obj.has_previous()),
    }


def pending_item_rows(
    job: ImportJob,
    *,
    group_key: str | None = None,
    active_items: list[ImportReviewItem] | None = None,
) -> list[ReviewRowPayload]:
    items = (
        list(active_items)
        if active_items is not None
        else active_review_items(job, group_key=group_key)
    )
    if group_key:
        items = [item for item in items if str(item.group.group_key or "") == str(group_key)]
    return [build_compatibility_review_row(item) for item in items]


def row_to_item_id_map(
    job: ImportJob,
    *,
    active_items: list[ImportReviewItem] | None = None,
) -> dict[str, int]:
    mapping: dict[str, int] = {}
    plain_row_counts: dict[str, int] = {}
    resolved_items = (
        list(active_items)
        if active_items is not None
        else list(review_item_queryset(job).filter(status__in=_ACTIVE_ITEM_STATUSES))
    )
    for item in resolved_items:
        lookup_keys = review_row_lookup_keys(
            row_num=int(item.row_ordinal or 0),
            entity_type=str(item.entity_type or ""),
        )
        composite_key = lookup_keys[0]
        mapping[composite_key] = int(item.id)
        plain_key = lookup_keys[-1]
        plain_row_counts[plain_key] = plain_row_counts.get(plain_key, 0) + 1
    for item in resolved_items:
        plain_key = review_row_lookup_keys(
            row_num=int(item.row_ordinal or 0),
            entity_type=str(item.entity_type or ""),
        )[-1]
        if plain_row_counts.get(plain_key, 0) == 1:
            mapping[plain_key] = int(item.id)
    return mapping


def group_members(job: ImportJob, *, group_key: str) -> list[ImportReviewItem]:
    return list(
        apply_review_item_filters(
            review_item_queryset(job),
            group_key=group_key,
            issue_group=None,
            search="",
            pending_only=True,
        )
    )


__all__ = [
    "ReviewCountSnapshot",
    "review_group_queryset",
    "review_item_queryset",
    "has_db_review_state",
    "review_count_snapshot",
    "active_review_items",
    "compatibility_review_rows",
    "apply_review_group_filters",
    "apply_review_item_filters",
    "paged_review_groups",
    "paged_review_items",
    "pending_item_rows",
    "row_to_item_id_map",
    "group_members",
]
