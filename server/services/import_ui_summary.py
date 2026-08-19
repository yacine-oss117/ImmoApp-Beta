"""UI-facing summary helpers for importer preview, status, and review flows."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from server.services.duplicate_checker import _normalize_phone_for_dedup

_ENTITY_KEYS = ("client", "demande", "listing", "offer")
_AUTO_FIX_KEYS = (
    "phone_format_fixed",
    "name_case_fixed",
    "location_normalized",
    "grouped_related_rows",
    "other_auto_fixes",
)
_ATTENTION_KEYS = (
    "needs_attention",
    "blocking",
    "possible_duplicates",
    "missing_information",
)
_TERMINAL_REASONS = {
    "success",
    "zero_change",
    "review_required",
    "failed",
    "cancelled",
    "emergency_overflow",
}
_ZERO_CHANGE_REASON_CODES = {
    "all_rows_skipped",
    "all_rows_need_review",
    "all_rows_duplicate_noop",
    "all_rows_invalid",
}


def _coerce_nonnegative_int(value: object) -> int | None:
    if isinstance(value, bool):
        return max(0, int(value))
    if isinstance(value, (int, float)):
        return max(0, int(value))
    if isinstance(value, str):
        try:
            return max(0, int(value))
        except ValueError:
            return None
    return None


def _normalized_text(value: object) -> str:
    return str(value or "").strip().lower()


def _normalize_reason_codes(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    normalized: list[str] = []
    seen: set[str] = set()
    for item in value:
        code = _normalized_text(item)
        if code not in _ZERO_CHANGE_REASON_CODES or code in seen:
            continue
        normalized.append(code)
        seen.add(code)
    return normalized


def empty_entity_counts() -> dict[str, int]:
    return {key: 0 for key in _ENTITY_KEYS}


def empty_auto_fix_summary() -> dict[str, int]:
    return {key: 0 for key in _AUTO_FIX_KEYS}


def empty_attention_summary() -> dict[str, int]:
    return {key: 0 for key in _ATTENTION_KEYS}


def review_overflow_count_for_payload(
    *,
    progress_detail: Mapping[str, Any] | None = None,
    result_summary: Mapping[str, Any] | None = None,
) -> int:
    resolved = 0
    candidates = [
        (progress_detail or {}).get("review_overflow_count"),
        (result_summary or {}).get("review_overflow_count"),
    ]
    for value in candidates:
        parsed = _coerce_nonnegative_int(value)
        if parsed is None:
            continue
        resolved = max(resolved, parsed)
    return resolved


def review_state_for_payload(
    *,
    progress_detail: Mapping[str, Any] | None = None,
    result_summary: Mapping[str, Any] | None = None,
) -> str:
    candidates = [
        (result_summary or {}).get("review_state"),
        (progress_detail or {}).get("review_state"),
    ]
    for value in candidates:
        text = str(value or "").strip().lower()
        if text:
            return text
    if (
        review_overflow_count_for_payload(
            progress_detail=progress_detail,
            result_summary=result_summary,
        )
        > 0
    ):
        return "emergency_overflow"
    return "normal"


def review_total_count_for_payload(
    *,
    visible_review_count: int,
    progress_detail: Mapping[str, Any] | None = None,
    result_summary: Mapping[str, Any] | None = None,
) -> int:
    computed_total = max(0, int(visible_review_count or 0)) + review_overflow_count_for_payload(
        progress_detail=progress_detail,
        result_summary=result_summary,
    )
    explicit_total = 0
    for value in (
        (result_summary or {}).get("review_total_count"),
        (progress_detail or {}).get("review_total_count"),
        (result_summary or {}).get("review_remaining"),
    ):
        parsed = _coerce_nonnegative_int(value)
        if parsed is None:
            continue
        explicit_total = max(explicit_total, parsed)
    return max(computed_total, explicit_total)


def classify_terminal_reason(
    *,
    status: object,
    created_count: int,
    updated_count: int,
    error_count: int,
    review_total_count: int,
    overflow_blocking: bool,
) -> str | None:
    normalized_status = _normalized_text(status)
    rows_changed = created_count > 0 or updated_count > 0
    if overflow_blocking:
        return "emergency_overflow"
    if review_total_count > 0 and normalized_status in {"review", "ready"}:
        return "review_required"
    if normalized_status in {
        "",
        "idle",
        "uploading",
        "pending",
        "parsing",
        "mapping",
        "execute_ready",
        "queued",
        "running",
    }:
        return None
    if normalized_status == "failed" or (error_count > 0 and not rows_changed):
        return "failed"
    if rows_changed:
        return "success"
    if normalized_status == "completed":
        return "zero_change"
    return None


def derive_terminal_result_state(
    *,
    status: object,
    row_count: int,
    created_count: int,
    updated_count: int,
    skipped_count: int,
    error_count: int,
    review_total_count: int,
    overflow_blocking: bool,
    explicit_terminal_reason: object = "",
    explicit_zero_change_reasons: object = None,
    explicit_unchanged_count: object = None,
) -> dict[str, object]:
    terminal_reason = _normalized_text(explicit_terminal_reason)
    if terminal_reason not in _TERMINAL_REASONS:
        classified = classify_terminal_reason(
            status=status,
            created_count=created_count,
            updated_count=updated_count,
            error_count=error_count,
            review_total_count=review_total_count,
            overflow_blocking=overflow_blocking,
        )
        terminal_reason = str(classified or "")

    unchanged_count = _coerce_nonnegative_int(explicit_unchanged_count)
    if unchanged_count is None:
        unchanged_count = max(
            0,
            int(row_count or 0)
            - int(created_count or 0)
            - int(updated_count or 0)
            - int(skipped_count or 0)
            - int(error_count or 0),
        )

    zero_change_reasons = _normalize_reason_codes(explicit_zero_change_reasons)
    if terminal_reason == "zero_change" and not zero_change_reasons:
        if review_total_count > 0:
            zero_change_reasons = ["all_rows_need_review"]
        elif error_count > 0:
            zero_change_reasons = ["all_rows_invalid"]
        elif skipped_count > 0:
            zero_change_reasons = ["all_rows_skipped"]
        elif unchanged_count > 0 or row_count > 0:
            zero_change_reasons = ["all_rows_duplicate_noop"]
    elif terminal_reason != "zero_change":
        zero_change_reasons = []

    return {
        "terminal_reason": terminal_reason or None,
        "result_zero_change": terminal_reason == "zero_change",
        "result_zero_change_reasons": zero_change_reasons,
        "unchanged_count": int(unchanged_count or 0),
    }


def accumulate_preview_summary_row(
    row: Mapping[str, Any],
    *,
    bundle_mode: str,
    entity_counts: dict[str, int],
    auto_fix_summary: dict[str, int],
    attention_summary: dict[str, int],
    seen_bundle_root_keys: set[str] | None = None,
) -> int:
    entity_type = str(row.get("entity_type", "") or "").strip().lower()

    normalized = row.get("normalized")
    normalized_payload = normalized if isinstance(normalized, Mapping) else {}
    recovered_fields = [
        dict(value)
        for value in list(row.get("recovered_fields", []) or [])
        if isinstance(value, Mapping)
    ]

    categorized = False
    if any(str(item.get("field", "") or "") == "phone" for item in recovered_fields):
        auto_fix_summary["phone_format_fixed"] += 1
        categorized = True
    if any(
        str(item.get("field", "") or "") in {"location", "locations", "wilaya"}
        for item in recovered_fields
    ):
        auto_fix_summary["location_normalized"] += 1
        categorized = True
    if any(
        key in normalized_payload
        and isinstance(normalized_payload.get(key), str)
        and str(normalized_payload.get(key) or "").strip()
        for key in ("family_name", "owner_name")
    ):
        original = row.get("original")
        if isinstance(original, Mapping) and any(
            str(original.get(key, "") or "").strip()
            and str(original.get(key, "")).strip() != str(normalized_payload.get(key, "")).strip()
            and str(original.get(key, "")).strip().lower()
            == str(normalized_payload.get(key, "")).strip().lower()
            for key in ("family_name", "owner_name")
            if key in normalized_payload
        ):
            auto_fix_summary["name_case_fixed"] += 1
            categorized = True
    if recovered_fields and not categorized:
        auto_fix_summary["other_auto_fixes"] += 1

    issue_group, _, _ = classify_review_issue(row)
    needs_attention = (
        bool(row.get("needs_review", False))
        or bool(list(row.get("errors", []) or []))
        or bool(list(row.get("blocking_reasons", []) or []))
    )
    if needs_attention:
        attention_summary["needs_attention"] += 1
    if list(row.get("blocking_reasons", []) or []):
        attention_summary["blocking"] += 1
    if issue_group == "possible_duplicate":
        attention_summary["possible_duplicates"] += 1
    if issue_group == "missing_information":
        attention_summary["missing_information"] += 1

    if bundle_mode == "same_side_bundle" and entity_type in {"client", "listing"}:
        root_key = _preview_bundle_root_key(row, implicit_root_type=entity_type)
        if root_key and seen_bundle_root_keys is not None:
            if root_key not in seen_bundle_root_keys:
                entity_counts[entity_type] += 1
                seen_bundle_root_keys.add(root_key)
        elif entity_type in entity_counts:
            entity_counts[entity_type] += 1
    elif entity_type in entity_counts:
        entity_counts[entity_type] += 1

    if bundle_mode == "same_side_bundle" and entity_type in {"demande", "offer"}:
        implicit_root_type = "client" if entity_type == "demande" else "listing"
        root_key = _preview_bundle_root_key(row, implicit_root_type=implicit_root_type)
        if root_key and seen_bundle_root_keys is not None and root_key not in seen_bundle_root_keys:
            entity_counts[implicit_root_type] += 1
            seen_bundle_root_keys.add(root_key)
        return 1
    return 0


def _preview_bundle_root_key(
    row: Mapping[str, Any],
    *,
    implicit_root_type: str,
) -> str:
    normalized_payload = row.get("normalized")
    normalized = normalized_payload if isinstance(normalized_payload, Mapping) else {}
    original_payload = row.get("original")
    original = original_payload if isinstance(original_payload, Mapping) else {}

    phone = _normalize_phone_for_dedup(
        str(normalized.get("phone") or original.get("phone") or "").strip()
    )
    if phone:
        return f"{implicit_root_type}:phone:{phone}"

    name_value = str(
        normalized.get("family_name")
        or normalized.get("name")
        or original.get("family_name")
        or original.get("name")
        or ""
    ).strip()
    if name_value:
        return f"{implicit_root_type}:name:{name_value.casefold()}"

    email_value = str(normalized.get("email") or original.get("email") or "").strip().casefold()
    if email_value:
        return f"{implicit_root_type}:email:{email_value}"

    return ""


def _row_text_fragments(row: Mapping[str, Any]) -> list[str]:
    fragments: list[str] = []
    for key in ("remarks", "blocking_reasons"):
        raw_values = row.get(key, [])
        if isinstance(raw_values, list):
            fragments.extend(str(value or "").strip().lower() for value in raw_values if value)
    for review_field in list(row.get("review_fields", []) or []):
        if not isinstance(review_field, Mapping):
            continue
        for key in ("field", "remark", "original", "normalized"):
            value = review_field.get(key)
            if value:
                fragments.append(str(value).strip().lower())
    return fragments


def classify_review_issue(row: Mapping[str, Any]) -> tuple[str, str, str]:
    fragments = " ".join(_row_text_fragments(row))
    review_fields = [
        str(field.get("field", "") or "").strip().lower()
        for field in list(row.get("review_fields", []) or [])
        if isinstance(field, Mapping)
    ]
    blocking_reasons = [
        str(value or "").strip().lower()
        for value in list(row.get("blocking_reasons", []) or [])
        if str(value or "").strip()
    ]
    persisted_issue_group = str(row.get("issue_group", "") or "").strip().lower()
    if bool(row.get("immutable_conflict", False)):
        return (
            "field_conflict",
            "Information conflict",
            "Some information conflicts with an existing record and needs your confirmation.",
        )
    if list(row.get("candidate_matches", []) or []):
        return (
            "possible_duplicate",
            "Possible duplicate",
            "This looks very close to an existing record.",
        )
    if (
        any(
            reason in {"parent", "anchor", "missing_parent", "child_anchor_missing"}
            for reason in blocking_reasons
        )
        or any(field in {"client_id", "listing_id"} for field in review_fields)
        or persisted_issue_group == "parent_match_needed"
    ):
        return (
            "parent_match_needed",
            "Parent match needed",
            "This line needs a matching parent record before it can be added.",
        )
    if any(field in {"location", "locations", "wilaya"} for field in review_fields) or (
        persisted_issue_group == "unclear_location"
    ):
        return (
            "unclear_location",
            "Location needs checking",
            "The location needs a quick check before we continue.",
        )
    if (
        any(field in {"type"} for field in review_fields)
        or persisted_issue_group == "unclear_property_type"
    ):
        return (
            "unclear_property_type",
            "Property type needs checking",
            "The property type needs a quick check before we continue.",
        )
    if any(
        field in {"budget", "budget_min", "budget_max", "price"} for field in review_fields
    ) and any(
        token in fragments
        for token in (
            "price scale",
            "dzd",
            "centime",
            "ambiguous_million_token",
            "ambiguous_decimal_no_scale",
        )
    ):
        return (
            "unclear_price_scale",
            "Price scale needs checking",
            "We need to confirm whether this price is written in DZD or local centime-style shorthand.",
        )
    if persisted_issue_group in {
        "field_conflict",
        "possible_duplicate",
        "missing_information",
        "other",
    }:
        if persisted_issue_group == "field_conflict":
            return (
                "field_conflict",
                "Information conflict",
                "Some information conflicts with an existing record and needs your confirmation.",
            )
        if persisted_issue_group == "possible_duplicate":
            return (
                "possible_duplicate",
                "Possible duplicate",
                "This looks very close to an existing record.",
            )
        if persisted_issue_group == "missing_information":
            return (
                "missing_information",
                "Missing information",
                "A few important details are missing or unclear.",
            )
    if any(token in fragments for token in ("missing", "required", "empty", "invalid")):
        return (
            "missing_information",
            "Missing information",
            "A few important details are missing or unclear.",
        )
    if "immutable" in fragments:
        return (
            "field_conflict",
            "Information conflict",
            "Some information conflicts with an existing record and needs your confirmation.",
        )
    if "parent" in fragments or "anchor" in fragments:
        return (
            "parent_match_needed",
            "Parent match needed",
            "This line needs a matching parent record before it can be added.",
        )
    if any(token in fragments for token in ("location", "wilaya", "commune")):
        return (
            "unclear_location",
            "Location needs checking",
            "The location needs a quick check before we continue.",
        )
    if "property type" in fragments:
        return (
            "unclear_property_type",
            "Property type needs checking",
            "The property type needs a quick check before we continue.",
        )
    return (
        "other",
        "Needs attention",
        "This line needs a quick review before we continue.",
    )


def summarize_preview_rows(
    preview_rows: Iterable[Mapping[str, Any]],
    *,
    bundle_mode: str = "single_entity",
) -> tuple[dict[str, int], dict[str, int], dict[str, int]]:
    entity_counts = empty_entity_counts()
    auto_fix_summary = empty_auto_fix_summary()
    attention_summary = empty_attention_summary()
    same_side_grouped = 0
    seen_bundle_root_keys: set[str] = set()

    for row in preview_rows:
        same_side_grouped += accumulate_preview_summary_row(
            row,
            bundle_mode=bundle_mode,
            entity_counts=entity_counts,
            auto_fix_summary=auto_fix_summary,
            attention_summary=attention_summary,
            seen_bundle_root_keys=seen_bundle_root_keys,
        )

    if same_side_grouped > 0:
        auto_fix_summary["grouped_related_rows"] = same_side_grouped
    return entity_counts, auto_fix_summary, attention_summary


def summarize_result_state(
    *,
    result_summary: Mapping[str, Any] | None,
    review_rows: Iterable[Mapping[str, Any]] | None = None,
) -> tuple[dict[str, int], dict[str, int], dict[str, int]]:
    summary = dict(result_summary or {})
    entity_counts = empty_entity_counts()
    for key, value in dict(summary.get("result_entity_counts", {}) or {}).items():
        if key in entity_counts and isinstance(value, (int, float)):
            entity_counts[str(key)] = int(value)

    auto_fix_summary = empty_auto_fix_summary()
    for key, value in dict(summary.get("result_auto_fix_summary", {}) or {}).items():
        if key in auto_fix_summary and isinstance(value, (int, float)):
            auto_fix_summary[str(key)] = int(value)

    attention_summary = empty_attention_summary()
    dead_letter_summary = {
        str(key): int(value)
        for key, value in dict(summary.get("dead_letter_summary", {}) or {}).items()
        if isinstance(value, (int, float))
    }
    unresolved_review_rows = [
        dict(row) for row in list(review_rows or []) if isinstance(row, Mapping)
    ]
    review_overflow_count = review_overflow_count_for_payload(result_summary=summary)
    review_total_count = max(
        0,
        int(summary.get("review_total_count", 0) or 0),
    )
    for row in unresolved_review_rows:
        issue_group, _, _ = classify_review_issue(row)
        attention_summary["needs_attention"] += 1
        if list(row.get("blocking_reasons", []) or []):
            attention_summary["blocking"] += 1
        if issue_group == "possible_duplicate":
            attention_summary["possible_duplicates"] += 1
        if issue_group == "missing_information":
            attention_summary["missing_information"] += 1

    error_count = int(summary.get("error_count", 0) or 0)
    blocking_discarded = int(dead_letter_summary.get("blocking_discarded", 0) or 0)
    outstanding_review_attention = max(
        review_total_count,
        len(unresolved_review_rows) + review_overflow_count,
    )
    attention_summary["needs_attention"] = max(
        attention_summary["needs_attention"],
        outstanding_review_attention + blocking_discarded + error_count,
    )
    attention_summary["blocking"] = max(
        attention_summary["blocking"],
        review_overflow_count + blocking_discarded + error_count,
    )
    return entity_counts, auto_fix_summary, attention_summary


def issue_metadata(row: Mapping[str, Any]) -> dict[str, str]:
    issue_group, issue_title, issue_summary = classify_review_issue(row)
    return {
        "issue_group": issue_group,
        "issue_title": issue_title,
        "issue_summary": issue_summary,
    }


__all__ = [
    "classify_terminal_reason",
    "classify_review_issue",
    "derive_terminal_result_state",
    "empty_attention_summary",
    "empty_auto_fix_summary",
    "empty_entity_counts",
    "issue_metadata",
    "review_overflow_count_for_payload",
    "review_state_for_payload",
    "review_total_count_for_payload",
    "summarize_preview_rows",
    "accumulate_preview_summary_row",
    "summarize_result_state",
]
