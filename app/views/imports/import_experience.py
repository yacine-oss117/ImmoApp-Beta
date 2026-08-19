from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Literal

Tone = Literal["ready", "attention", "success", "warning", "error", "queued", "processing"]
MetricKind = Literal["primary", "success", "warning", "muted"]

FIELD_LABELS: dict[str, str] = {
    "family_name": "Name",
    "owner_name": "Owner name",
    "phone": "Phone",
    "remarks": "Notes",
    "status": "Status",
    "tags": "Tags",
    "action": "Looking for",
    "type": "Property type",
    "wilaya": "City",
    "locations": "Preferred areas",
    "location": "Area",
    "budget_min": "Minimum budget",
    "budget_max": "Maximum budget",
    "budget": "Budget",
    "surface_min": "Minimum size",
    "surface_max": "Maximum size",
    "surface": "Size",
    "beds_min": "Minimum bedrooms",
    "beds": "Bedrooms",
    "floor_min": "Minimum floor",
    "floor_max": "Maximum floor",
    "floor": "Floor",
    "furnished": "Furnished",
    "elevator": "Elevator",
    "accessibility_required": "Accessibility required",
    "accessibility_supported": "Accessibility supported",
    "price_negotiable": "Price negotiable",
    "price_flex_pct": "Negotiation margin",
    "link": "Map link",
    "latitude": "Latitude",
    "longitude": "Longitude",
}

ENTITY_FIELD_ORDER: dict[str, list[str]] = {
    "client": ["family_name", "phone", "status", "remarks", "tags"],
    "listing": ["family_name", "phone", "status", "remarks"],
    "demande": [
        "action",
        "type",
        "wilaya",
        "locations",
        "budget_min",
        "budget_max",
        "surface_min",
        "surface_max",
        "beds_min",
        "floor_min",
        "floor_max",
        "furnished",
        "elevator",
        "accessibility_required",
        "remarks",
        "tags",
    ],
    "offer": [
        "status",
        "action",
        "type",
        "wilaya",
        "location",
        "budget",
        "surface",
        "beds",
        "floor",
        "furnished",
        "elevator",
        "accessibility_supported",
        "price_negotiable",
        "price_flex_pct",
        "remarks",
        "link",
        "latitude",
        "longitude",
    ],
}

ISSUE_GROUP_TEXT: dict[str, tuple[str, str]] = {
    "possible_duplicate": (
        "Possible duplicates",
        "These lines look very close to records already in your agency.",
    ),
    "missing_information": (
        "Missing information",
        "These lines are missing a few important details.",
    ),
    "unclear_location": (
        "Location needs checking",
        "We found locations that need a quick confirmation.",
    ),
    "unclear_property_type": (
        "Property type needs checking",
        "A few property types need a quick confirmation.",
    ),
    "unclear_price_scale": (
        "Price scale needs checking",
        "A few prices need confirmation before we can tell whether they are written in DZD or local centime-style shorthand.",
    ),
    "parent_match_needed": (
        "This line needs a parent match",
        "These lines need a matching client or property before they can be added.",
    ),
    "field_conflict": (
        "Information conflict",
        "Some information conflicts with existing records and needs your confirmation.",
    ),
    "other": (
        "Needs attention",
        "A few lines need a quick review before we continue.",
    ),
}


@dataclass(frozen=True)
class SummaryMetric:
    label: str
    value: int
    kind: MetricKind


@dataclass(frozen=True)
class ImportExperienceSummary:
    tone: Tone
    headline: str
    supporting_text: str
    primary_counts: list[SummaryMetric]
    automation_points: list[str]
    attention_points: list[str]
    detail_lines: list[str]


@dataclass(frozen=True)
class ImportReviewPage:
    page: int
    page_size: int
    total_items: int
    total_pages: int
    has_next: bool
    has_prev: bool


@dataclass(frozen=True)
class ImportReviewGroupRecord:
    group_key: str
    group_kind: str
    status: str
    issue_group: str
    issue_title: str
    issue_summary: str
    entity_type: str
    topology_side: str
    root_label: str
    item_count: int
    pending_item_count: int
    blocking_item_count: int
    suggested_group_action: str
    sample_rows: list[int]
    apply_to_all_allowed: bool = False
    apply_to_all_count: int = 0
    consistent_existing_id: int | None = None
    resolution_template: dict[str, Any] | None = None
    resolved_item_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def key(self) -> str:
        return self.group_key

    @property
    def title(self) -> str:
        return self.issue_title

    @property
    def count(self) -> int:
        return int(self.pending_item_count or self.item_count or 0)


@dataclass(frozen=True)
class ImportReviewItemRecord:
    item_id: int
    group_key: str
    row: int
    entity_type: str
    issue_group: str
    issue_title: str
    issue_summary: str
    raw_data: dict[str, Any]
    normalized_data: dict[str, Any]
    status: str
    suggested_action: str
    suggested_existing_id: int
    suggested_confidence: float
    candidate_matches: list[dict[str, Any]]
    candidate_total_count: int = 0
    candidate_matches_truncated: bool = False
    group_resolvable: bool = False
    group_resolution_blockers: list[str] = field(default_factory=list)
    resolution_source: str = ""
    effective_action: str | None = None


@dataclass(frozen=True)
class ImportReviewTableRow:
    row: int
    issue_group: str
    title: str
    summary: str
    entity_type: str
    suggested_action: str
    has_conflict: bool
    has_bulk_fix: bool
    raw: dict[str, Any]


@dataclass
class ImportReviewPaneState:
    mode: Literal["groups", "items"] = "groups"
    selected_group_key: str | None = None
    selected_item_id: int | None = None
    issue_group_filter: str | None = "all"
    search_text: str = ""
    page: int = 1
    page_size: int = 50
    pending_bulk_operations: dict[str, dict[str, Any]] | None = None
    review_state: str = "normal"
    review_disabled: bool = False
    review_disabled_reason: str = ""


def friendly_field_label(field_name: str) -> str:
    return FIELD_LABELS.get(field_name, field_name.replace("_", " ").capitalize())


def ordered_editable_fields(entity_type: str, payload: dict[str, Any]) -> list[str]:
    preferred = ENTITY_FIELD_ORDER.get(entity_type, [])
    ordered: list[str] = [field for field in preferred if field in payload]
    for field_name in payload:
        if field_name not in ordered and field_name not in {
            "created_by_id",
            "client_id",
            "listing_id",
        }:
            ordered.append(field_name)
    return ordered


def group_review_rows(review_rows: list[dict[str, Any]]) -> list[ImportReviewGroupRecord]:
    grouped: OrderedDict[str, list[dict[str, Any]]] = OrderedDict()
    for row in review_rows:
        key = str(row.get("issue_group", "other") or "other")
        grouped.setdefault(key, []).append(row)
    groups: list[ImportReviewGroupRecord] = []
    for key, rows in grouped.items():
        title, description = ISSUE_GROUP_TEXT.get(key, ISSUE_GROUP_TEXT["other"])
        groups.append(
            ImportReviewGroupRecord(
                group_key=key,
                group_kind="single_row",
                status="pending",
                issue_group=key,
                issue_title=title,
                issue_summary=description,
                entity_type=str(rows[0].get("entity_type", "") or "") if rows else "",
                topology_side=str(rows[0].get("topology_side", "") or "") if rows else "",
                root_label=title,
                item_count=len(rows),
                pending_item_count=len(rows),
                blocking_item_count=sum(
                    1
                    for row in rows
                    if bool(list(row.get("blocking_reasons", []) or []))
                    or bool(row.get("immutable_conflict", False))
                ),
                suggested_group_action=str(rows[0].get("suggested_action", "") if rows else ""),
                sample_rows=[
                    int(row.get("row", 0) or 0) for row in rows[:5] if isinstance(row, dict)
                ],
                metadata={},
            )
        )
    return groups


def review_page_from_payload(payload: dict[str, Any]) -> ImportReviewPage:
    return ImportReviewPage(
        page=int(payload.get("page", 1) or 1),
        page_size=int(payload.get("page_size", 50) or 50),
        total_items=int(payload.get("total_items", 0) or 0),
        total_pages=int(payload.get("total_pages", 0) or 0),
        has_next=bool(payload.get("has_next", False)),
        has_prev=bool(payload.get("has_prev", False)),
    )


def review_group_from_payload(payload: dict[str, Any]) -> ImportReviewGroupRecord:
    return ImportReviewGroupRecord(
        group_key=str(payload.get("group_key", "") or ""),
        group_kind=str(payload.get("group_kind", "single_row") or "single_row"),
        status=str(payload.get("status", "pending") or "pending"),
        issue_group=str(payload.get("issue_group", "other") or "other"),
        issue_title=str(payload.get("issue_title", "Needs attention") or "Needs attention"),
        issue_summary=str(
            payload.get("issue_summary", "A few details need your attention.")
            or "A few details need your attention."
        ),
        entity_type=str(payload.get("entity_type", "") or ""),
        topology_side=str(payload.get("topology_side", "") or ""),
        root_label=str(payload.get("root_label", "") or ""),
        item_count=int(payload.get("item_count", 0) or 0),
        pending_item_count=int(payload.get("pending_item_count", 0) or 0),
        blocking_item_count=int(payload.get("blocking_item_count", 0) or 0),
        suggested_group_action=str(payload.get("suggested_group_action", "") or ""),
        sample_rows=[int(value) for value in list(payload.get("sample_rows", []) or [])],
        apply_to_all_allowed=bool(payload.get("apply_to_all_allowed", False)),
        apply_to_all_count=int(payload.get("apply_to_all_count", 0) or 0),
        consistent_existing_id=(int(payload.get("consistent_existing_id", 0) or 0) or None),
        resolution_template=(
            dict(payload.get("resolution_template", {}) or {})
            if isinstance(payload.get("resolution_template"), dict)
            else None
        ),
        resolved_item_count=int(payload.get("resolved_item_count", 0) or 0),
        metadata=dict(payload.get("metadata", {}) or {}),
    )


def review_item_from_payload(payload: dict[str, Any]) -> ImportReviewItemRecord:
    candidate_matches = [
        dict(item)
        for item in list(payload.get("candidate_matches", []) or [])
        if isinstance(item, dict)
    ]
    candidate_total_count = max(
        int(payload.get("candidate_total_count", 0) or 0),
        len(candidate_matches),
    )
    return ImportReviewItemRecord(
        item_id=int(payload.get("item_id", 0) or 0),
        group_key=str(payload.get("group_key", "") or ""),
        row=int(payload.get("row", 0) or 0),
        entity_type=str(payload.get("entity_type", "") or ""),
        issue_group=str(payload.get("issue_group", "other") or "other"),
        issue_title=str(payload.get("issue_title", "Needs attention") or "Needs attention"),
        issue_summary=str(
            payload.get("issue_summary", "A few details need your attention.")
            or "A few details need your attention."
        ),
        raw_data=dict(payload.get("raw_data", {}) or {}),
        normalized_data=dict(payload.get("normalized_data", {}) or {}),
        status=str(payload.get("status", "pending") or "pending"),
        suggested_action=str(payload.get("suggested_action", "") or ""),
        suggested_existing_id=int(payload.get("suggested_existing_id", 0) or 0),
        suggested_confidence=float(payload.get("suggested_confidence", 0.0) or 0.0),
        candidate_matches=candidate_matches,
        candidate_total_count=candidate_total_count,
        candidate_matches_truncated=bool(payload.get("candidate_matches_truncated", False))
        or candidate_total_count > len(candidate_matches),
        group_resolvable=bool(payload.get("group_resolvable", False)),
        group_resolution_blockers=[
            str(item) for item in list(payload.get("group_resolution_blockers", []) or [])
        ],
        resolution_source=str(payload.get("resolution_source", "") or ""),
        effective_action=(str(payload.get("effective_action", "") or "") or None),
    )


def build_review_table_rows(review_rows: list[dict[str, Any]]) -> list[ImportReviewTableRow]:
    rows: list[ImportReviewTableRow] = []
    for raw_row in review_rows:
        issue_group = str(raw_row.get("issue_group", "other") or "other")
        rows.append(
            ImportReviewTableRow(
                row=int(raw_row.get("row", 0) or 0),
                issue_group=issue_group,
                title=str(raw_row.get("issue_title", "Needs attention") or "Needs attention"),
                summary=str(
                    raw_row.get("issue_summary", "Please confirm this line before continuing.")
                    or "Please confirm this line before continuing."
                ),
                entity_type=str(raw_row.get("entity_type", "") or ""),
                suggested_action=str(raw_row.get("suggested_action", "") or ""),
                has_conflict=bool(raw_row.get("immutable_conflict", False))
                or issue_group == "field_conflict",
                has_bulk_fix=bool(list(raw_row.get("bulk_fix_groups", []) or [])),
                raw=dict(raw_row),
            )
        )
    return rows


def _entity_metrics(entity_counts: dict[str, int], *, result: bool) -> list[SummaryMetric]:
    noun_map = [
        ("client", "Clients added" if result else "Clients found"),
        ("demande", "Requests added" if result else "Requests found"),
        ("listing", "Properties added" if result else "Properties found"),
        ("offer", "Offers added" if result else "Offers found"),
    ]
    metrics: list[SummaryMetric] = []
    for key, label in noun_map:
        count = int(entity_counts.get(key, 0) or 0)
        if count > 0:
            metrics.append(SummaryMetric(label=label, value=count, kind="primary"))
    return metrics


def _entity_phrase(entity_counts: dict[str, int], *, result: bool) -> str:
    parts: list[str] = []
    noun_map = [
        ("client", ("client", "clients")),
        ("demande", ("request", "requests")),
        ("listing", ("property", "properties")),
        ("offer", ("offer", "offers")),
    ]
    for key, nouns in noun_map:
        count = int(entity_counts.get(key, 0) or 0)
        if count > 0:
            noun = nouns[0] if count == 1 else nouns[1]
            parts.append(f"{count} {noun}")
    if not parts:
        return "your data"
    if len(parts) == 1:
        return parts[0]
    return ", ".join(parts[:-1]) + f" and {parts[-1]}"


def _automation_points(auto_fix_summary: dict[str, int]) -> list[str]:
    points: list[str] = []
    if int(auto_fix_summary.get("phone_format_fixed", 0) or 0) > 0:
        points.append("We cleaned phone number formatting.")
    if int(auto_fix_summary.get("name_case_fixed", 0) or 0) > 0:
        points.append("We standardized names.")
    if int(auto_fix_summary.get("location_normalized", 0) or 0) > 0:
        points.append("We matched cities and areas.")
    if int(auto_fix_summary.get("grouped_related_rows", 0) or 0) > 0:
        points.append("We grouped related lines together.")
    if int(auto_fix_summary.get("other_auto_fixes", 0) or 0) > 0:
        points.append("We fixed common formatting automatically.")
    return points


def _attention_points(attention_summary: dict[str, int]) -> list[str]:
    points: list[str] = []
    if int(attention_summary.get("possible_duplicates", 0) or 0) > 0:
        points.append("A few lines look close to existing records in your agency.")
    if int(attention_summary.get("missing_information", 0) or 0) > 0:
        points.append("Some lines are missing a few important details.")
    blocking = int(attention_summary.get("blocking", 0) or 0)
    if blocking > 0:
        points.append("A few lines need your attention before they can be added.")
    return points


def build_mapping_summary(
    *,
    manual_mapping_required: bool,
    import_supported: bool,
    blocking_message: str,
    preview_entity_counts: dict[str, int],
    preview_auto_fix_summary: dict[str, int],
    row_count: int,
) -> ImportExperienceSummary:
    if not import_supported:
        return ImportExperienceSummary(
            tone="warning",
            headline="This file needs a different import format",
            supporting_text=(
                blocking_message or "This file type is not supported for direct import."
            ),
            primary_counts=_entity_metrics(preview_entity_counts, result=False)
            or [SummaryMetric(label="Lines checked", value=row_count, kind="primary")],
            automation_points=[],
            attention_points=["Use a combined root-and-child file for this import."],
            detail_lines=["Choose another file to continue."],
        )
    if manual_mapping_required:
        if preview_entity_counts and any(
            int(value or 0) > 0 for value in preview_entity_counts.values()
        ):
            supporting_text = (
                f"We found {_entity_phrase(preview_entity_counts, result=False)}. "
                "Most of your file is ready. A few columns need a quick check before import."
            )
        else:
            supporting_text = (
                "Most of your file is ready. A few columns need a quick check before import."
            )
        return ImportExperienceSummary(
            tone="attention",
            headline="Help us match a few columns",
            supporting_text=supporting_text,
            primary_counts=_entity_metrics(preview_entity_counts, result=False)
            or [SummaryMetric(label="Lines checked", value=row_count, kind="primary")],
            automation_points=_automation_points(preview_auto_fix_summary),
            attention_points=["A few columns need your attention before we continue."],
            detail_lines=["Review the suggested matches before continuing."],
        )
    supporting_text = (
        f"We found {_entity_phrase(preview_entity_counts, result=False)}. "
        "We matched the columns for you. You can continue, or review the details if you want."
        if preview_entity_counts
        and any(int(value or 0) > 0 for value in preview_entity_counts.values())
        else "We matched the columns for you. You can continue, or review the details if you want."
    )
    return ImportExperienceSummary(
        tone="ready",
        headline="Your columns look good",
        supporting_text=supporting_text,
        primary_counts=_entity_metrics(preview_entity_counts, result=False)
        or [SummaryMetric(label="Lines checked", value=row_count, kind="primary")],
        automation_points=_automation_points(preview_auto_fix_summary),
        attention_points=[],
        detail_lines=["You can review the column details before importing."],
    )


def build_processing_summary(
    *,
    status: str,
    stage: str,
    row_count: int,
    queue_position: int,
    agency_queue_depth: int,
    progress_detail: dict[str, Any],
    topology_side_hint: str,
) -> ImportExperienceSummary:
    if status == "queued":
        return ImportExperienceSummary(
            tone="queued",
            headline="Your import is waiting its turn",
            supporting_text="Another import from your agency is finishing first. We'll start yours automatically.",
            primary_counts=[
                SummaryMetric(label="Lines in this file", value=row_count, kind="primary"),
                SummaryMetric(label="Queue position", value=max(1, queue_position), kind="muted"),
            ],
            automation_points=[],
            attention_points=[],
            detail_lines=[
                f"Position {max(1, queue_position)} of {max(1, agency_queue_depth)} in your agency queue."
            ],
        )

    phase = str(progress_detail.get("phase", stage or "executing") or "executing")
    phase_map = {
        "upload": "Checking your file",
        "mapping": "Checking your file",
        "prepare": "Organizing names, phones and locations",
        "plan": "Preparing your file for import",
        "load": (
            "Preparing clients and requests"
            if topology_side_hint == "client_side"
            else "Preparing properties and offers"
        ),
        "rebuild": "Finishing up",
        "review": "A few details need your attention",
        "done": "Finishing up",
        "executing": "We're preparing your import",
    }
    detail = phase_map.get(phase, "We're preparing your import")
    return ImportExperienceSummary(
        tone="processing",
        headline="We're preparing your import",
        supporting_text="We're organizing your file and checking the details.",
        primary_counts=[SummaryMetric(label="Lines in this file", value=row_count, kind="primary")],
        automation_points=[],
        attention_points=[],
        detail_lines=[detail],
    )


def build_final_summary(
    *,
    status: str,
    created_count: int,
    updated_count: int,
    error_count: int,
    skipped_count: int,
    result_entity_counts: dict[str, int],
    result_auto_fix_summary: dict[str, int],
    result_attention_summary: dict[str, int],
    row_count: int = 0,
    result_zero_change: bool = False,
    result_zero_change_reasons: list[str] | None = None,
    terminal_reason: str = "",
) -> ImportExperienceSummary:
    needs_attention = int(result_attention_summary.get("needs_attention", 0) or 0) > 0
    normalized_terminal_reason = str(terminal_reason or "").strip().lower()
    zero_change_reasons = [
        str(value or "").strip().lower() for value in list(result_zero_change_reasons or [])
    ]
    zero_change_state = bool(result_zero_change or normalized_terminal_reason == "zero_change")
    if normalized_terminal_reason == "cancelled":
        return ImportExperienceSummary(
            tone="warning",
            headline="Your import was cancelled",
            supporting_text="We stopped this import before it could finish.",
            primary_counts=[
                SummaryMetric(label="Added", value=created_count, kind="muted"),
                SummaryMetric(label="Updated", value=updated_count, kind="muted"),
                SummaryMetric(label="Not imported", value=skipped_count, kind="warning"),
            ],
            automation_points=_automation_points(result_auto_fix_summary),
            attention_points=[],
            detail_lines=[],
        )
    if status == "failed" or error_count > 0:
        return ImportExperienceSummary(
            tone="error",
            headline="We couldn't finish the import this time",
            supporting_text="Please try again. If the issue continues, contact support.",
            primary_counts=[
                SummaryMetric(label="Added", value=created_count, kind="success"),
                SummaryMetric(label="Needs attention", value=error_count, kind="warning"),
                SummaryMetric(label="Not imported", value=skipped_count, kind="muted"),
            ],
            automation_points=_automation_points(result_auto_fix_summary),
            attention_points=_attention_points(result_attention_summary),
            detail_lines=[],
        )
    if zero_change_state:
        supporting = "We checked your file, but nothing new was added or updated."
        detail_lines: list[str] = []
        if "all_rows_skipped" in zero_change_reasons:
            supporting = "We checked your file, but every line was skipped."
            detail_lines.append("Review the file and try again when you're ready.")
        elif "all_rows_need_review" in zero_change_reasons:
            supporting = "We checked your file, but every line still needs review before anything can be added."
            detail_lines.append("Review the pending lines to continue.")
        elif "all_rows_invalid" in zero_change_reasons:
            supporting = "We checked your file, but every line was invalid."
            detail_lines.append("Fix the file and try the import again.")
        elif "all_rows_duplicate_noop" in zero_change_reasons:
            supporting = (
                "We checked your file, but everything already matches what's in your agency."
            )
            detail_lines.append("No changes were needed.")
        elif row_count > 0:
            detail_lines.append(f"We checked {row_count} lines in this file.")
        metrics = [
            SummaryMetric(label="Added", value=created_count, kind="muted"),
            SummaryMetric(label="Updated", value=updated_count, kind="muted"),
        ]
        if skipped_count > 0:
            metrics.append(SummaryMetric(label="Not imported", value=skipped_count, kind="warning"))
        return ImportExperienceSummary(
            tone="warning",
            headline="Your import finished with no changes",
            supporting_text=supporting,
            primary_counts=metrics,
            automation_points=_automation_points(result_auto_fix_summary),
            attention_points=[],
            detail_lines=detail_lines,
        )
    if needs_attention:
        headline = "Your import is almost complete"
        supporting = (
            f"Most of {_entity_phrase(result_entity_counts, result=True)} was added. "
            "A few lines still need attention."
        )
        tone: Tone = "warning"
    else:
        headline = "Your import is complete"
        total_added = sum(
            int(value) for value in result_entity_counts.values() if isinstance(value, (int, float))
        )
        verb = "was" if total_added == 1 else "were"
        supporting = f"{_entity_phrase(result_entity_counts, result=True).capitalize()} {verb} added to your agency."
        tone = "success"
    metrics = _entity_metrics(result_entity_counts, result=True)
    if not metrics:
        metrics = [SummaryMetric(label="Added", value=created_count, kind="primary")]
    if updated_count > 0:
        metrics.append(SummaryMetric(label="Updated", value=updated_count, kind="success"))
    if needs_attention:
        metrics.append(
            SummaryMetric(
                label="Needs attention",
                value=int(result_attention_summary.get("needs_attention", 0) or 0),
                kind="warning",
            )
        )
    if skipped_count > 0:
        metrics.append(SummaryMetric(label="Not imported", value=skipped_count, kind="muted"))
    return ImportExperienceSummary(
        tone=tone,
        headline=headline,
        supporting_text=supporting,
        primary_counts=metrics,
        automation_points=_automation_points(result_auto_fix_summary),
        attention_points=_attention_points(result_attention_summary),
        detail_lines=[],
    )


def build_import_banner(summary: ImportExperienceSummary) -> tuple[str, str, str]:
    if summary.tone == "warning":
        return ("warning", "Import finished", summary.supporting_text)
    if summary.tone == "error":
        return ("error", "Import finished with issues", summary.supporting_text)
    return ("success", "Import complete", summary.supporting_text)


__all__ = [
    "ENTITY_FIELD_ORDER",
    "FIELD_LABELS",
    "ISSUE_GROUP_TEXT",
    "ImportExperienceSummary",
    "ImportReviewGroupRecord",
    "ImportReviewItemRecord",
    "ImportReviewPaneState",
    "ImportReviewPage",
    "ImportReviewTableRow",
    "SummaryMetric",
    "build_review_table_rows",
    "build_final_summary",
    "build_import_banner",
    "build_mapping_summary",
    "build_processing_summary",
    "friendly_field_label",
    "group_review_rows",
    "ordered_editable_fields",
    "review_group_from_payload",
    "review_item_from_payload",
    "review_page_from_payload",
]
