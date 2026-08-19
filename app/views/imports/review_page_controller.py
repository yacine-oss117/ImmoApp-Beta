"""Page-level state helpers for importer review UI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from app.utils.i18n import tr_factory
from app.views.imports.import_experience import (
    ImportReviewGroupRecord,
    ImportReviewPage,
    review_group_from_payload,
    review_page_from_payload,
)

_TR = tr_factory("ImportWizardStepReview")


@dataclass(frozen=True)
class RefreshReviewModel:
    group_records: list[ImportReviewGroupRecord]
    review_rows: list[dict[str, Any]]
    item_entries: dict[int, dict[str, Any]]
    item_entry_cache: dict[int, dict[str, Any]]
    subtitle: str


@dataclass(frozen=True)
class ReviewPageHydration:
    status: str
    stage: str
    review_count: int
    review_pending_group_count: int
    review_overflow_count: int
    review_total_count: int
    review_mode: Literal["groups", "items"]
    review_state: str
    overflow_blocking: bool
    review_disabled: bool
    review_disabled_reason: str
    review_groups: list[ImportReviewGroupRecord]
    review_page: ImportReviewPage | None
    review_rows: list[dict[str, Any]]
    selected_group_key: str | None
    issue_group_filter: str
    search_text: str
    page: int | None
    page_size: int | None


def build_refresh_review_model(state: Any) -> RefreshReviewModel:
    group_records = list(state.review_groups or [])
    raw_review_rows = list(state.review_rows or [])
    review_rows: list[dict[str, Any]] = []
    for index, entry in enumerate(raw_review_rows, start=1):
        normalized_entry = dict(entry)
        item_id = int(normalized_entry.get("item_id", 0) or normalized_entry.get("row", 0) or index)
        normalized_entry["item_id"] = item_id
        normalized_entry.setdefault(
            "group_key",
            str(normalized_entry.get("issue_group", "") or f"row:{item_id}"),
        )
        review_rows.append(normalized_entry)
    if not group_records and review_rows:
        group_records = [
            ImportReviewGroupRecord(
                group_key=str(entry.get("group_key", f"row:{entry.get('item_id', 0)}") or ""),
                group_kind="single_row",
                status=str(entry.get("status", "pending") or "pending"),
                issue_group=str(entry.get("issue_group", "other") or "other"),
                issue_title=str(
                    entry.get("issue_title", _TR("Needs attention")) or _TR("Needs attention")
                ),
                issue_summary=str(
                    entry.get("issue_summary", _TR("A few details need your attention."))
                    or _TR("A few details need your attention.")
                ),
                entity_type=str(entry.get("entity_type", "") or ""),
                topology_side=str(entry.get("topology_side", "") or ""),
                root_label=_TR("Line {row}").format(row=int(entry.get("row", 0) or 0)),
                item_count=1,
                pending_item_count=1,
                blocking_item_count=(
                    1
                    if bool(entry.get("immutable_conflict", False))
                    or bool(list(entry.get("blocking_reasons", []) or []))
                    else 0
                ),
                suggested_group_action=str(entry.get("suggested_action", "") or ""),
                sample_rows=[int(entry.get("row", 0) or 0)],
                metadata={},
            )
            for entry in review_rows
        ]
    item_entries = {int(entry.get("item_id", 0) or 0): dict(entry) for entry in review_rows}
    item_entry_cache = {item_id: dict(entry) for item_id, entry in item_entries.items()}
    overflow_count = int(state.review_overflow_count or 0)
    if state.review_state == "emergency_overflow":
        subtitle = _TR(
            "This file exceeded the safe review capacity for a single import job. "
            "{count} additional lines could not be opened in the normal review flow."
        ).format(count=max(0, overflow_count))
    else:
        subtitle = _TR(
            "{groups} groups and {lines} lines need a quick review before we continue."
        ).format(
            groups=max(
                0,
                int(state.review_pending_group_count or len(group_records)),
            ),
            lines=max(
                0,
                int(state.review_total_count or state.review_count or len(review_rows)),
            ),
        )
    return RefreshReviewModel(
        group_records=group_records,
        review_rows=review_rows,
        item_entries=item_entries,
        item_entry_cache=item_entry_cache,
        subtitle=subtitle,
    )


def hydrate_review_page_payload(
    data: dict[str, Any], *, pane_state: Any, current_status: str, current_stage: str
) -> ReviewPageHydration:
    review_rows_raw = data.get("review_rows", [])
    review_rows = list(review_rows_raw) if isinstance(review_rows_raw, list) else []
    review_groups_raw = data.get("review_groups", [])
    review_groups = (
        [
            review_group_from_payload(dict(item))
            for item in review_groups_raw
            if isinstance(item, dict)
        ]
        if isinstance(review_groups_raw, list)
        else []
    )
    review_page_raw = data.get("review_page", {})
    review_page = (
        review_page_from_payload(dict(review_page_raw))
        if isinstance(review_page_raw, dict)
        else None
    )
    filters_raw = data.get("review_filters", {})
    review_mode = str(data.get("review_mode", "") or "")
    if isinstance(filters_raw, dict):
        review_mode = str(review_mode or filters_raw.get("mode", "groups") or "groups")
    else:
        review_mode = str(review_mode or "groups")
    resolved_review_mode: Literal["groups", "items"] = (
        "items" if review_mode == "items" else "groups"
    )
    visible_group_keys = {group.group_key for group in review_groups}
    requested_group_key = ""
    issue_group_filter = str(pane_state.issue_group_filter or "all")
    search_text = str(pane_state.search_text or "")
    if isinstance(filters_raw, dict):
        requested_group_key = str(
            filters_raw.get("group_key", "") or pane_state.selected_group_key or ""
        )
        issue_group_filter = str(
            filters_raw.get("issue_group", pane_state.issue_group_filter or "all") or "all"
        )
        search_text = str(filters_raw.get("search", pane_state.search_text or "") or "")
    if requested_group_key and requested_group_key in visible_group_keys:
        selected_group_key: str | None = requested_group_key
    elif review_groups:
        selected_group_key = review_groups[0].group_key
    else:
        selected_group_key = None
    return ReviewPageHydration(
        status=str(data.get("status", current_status) or current_status),
        stage=str(data.get("stage", current_stage) or current_stage),
        review_count=int(data.get("review_count", len(review_rows)) or len(review_rows)),
        review_pending_group_count=int(
            data.get("review_pending_group_count", len(review_groups)) or len(review_groups)
        ),
        review_overflow_count=int(data.get("review_overflow_count", 0) or 0),
        review_total_count=int(
            data.get("review_total_count", data.get("review_count", len(review_rows))) or 0
        ),
        review_mode=resolved_review_mode,
        review_state=str(data.get("review_state", "normal") or "normal"),
        overflow_blocking=bool(data.get("overflow_blocking", False)),
        review_disabled=bool(data.get("review_disabled", False)),
        review_disabled_reason=str(data.get("review_disabled_reason", "") or ""),
        review_groups=review_groups,
        review_page=review_page,
        review_rows=review_rows,
        selected_group_key=selected_group_key,
        issue_group_filter=issue_group_filter,
        search_text=search_text,
        page=(int(review_page.page or 1) if review_page is not None else None),
        page_size=(int(review_page.page_size or 50) if review_page is not None else None),
    )


def map_review_conflicts_to_items(
    *,
    item_entries: dict[int, dict[str, Any]],
    row_conflicts: list[dict[str, Any]],
    conflict_item_ids: list[int] | None = None,
) -> dict[int, dict[str, Any]]:
    row_entity_to_item: dict[tuple[int, str], int] = {}
    plain_row_to_items: dict[int, list[int]] = {}
    for entry in item_entries.values():
        row_num = int(entry.get("row", 0) or 0)
        item_id = int(entry.get("item_id", 0) or 0)
        entity_type = str(entry.get("entity_type", "") or "").strip().lower()
        if item_id <= 0:
            continue
        row_entity_to_item[(row_num, entity_type)] = item_id
        plain_row_to_items.setdefault(row_num, []).append(item_id)
    conflicts_by_item: dict[int, dict[str, Any]] = {}
    for conflict_payload in row_conflicts:
        row_num = int(conflict_payload.get("row", 0) or 0)
        entity_type = str(conflict_payload.get("entity_type", "") or "").strip().lower()
        item_id = int(row_entity_to_item.get((row_num, entity_type), 0) or 0)
        if item_id <= 0:
            candidates = [value for value in plain_row_to_items.get(row_num, []) if value > 0]
            if len(candidates) == 1:
                item_id = int(candidates[0] or 0)
        if item_id > 0:
            conflicts_by_item[item_id] = dict(conflict_payload)
    for item_id in conflict_item_ids or []:
        conflicts_by_item.setdefault(int(item_id), {"row": 0})
    return conflicts_by_item


def format_conflict_message(conflict: dict[str, Any]) -> str:
    existing_summary = str(conflict.get("existing_summary", "") or "")
    if existing_summary:
        return _TR("Please review this line again. Existing record: {summary}").format(
            summary=existing_summary
        )
    return _TR("Please review this line again before continuing.")


__all__ = [
    "RefreshReviewModel",
    "ReviewPageHydration",
    "build_refresh_review_model",
    "format_conflict_message",
    "hydrate_review_page_payload",
    "map_review_conflicts_to_items",
]
