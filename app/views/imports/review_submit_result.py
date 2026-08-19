from __future__ import annotations

from typing import Any

from app.utils.i18n import tr_factory
from app.views.imports.import_experience import review_group_from_payload
from app.views.imports.wizard_state import ImportWizardController

_TR = tr_factory("ImportWizardStepReview")


def apply_final_review_submit_response(
    controller: ImportWizardController,
    data: dict[str, Any],
) -> tuple[bool, str]:
    controller.state.review_pane_state.pending_bulk_operations = {}
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
    still_review = list(data.get("still_review", []) or [])
    result_summary = dict(data.get("result_summary", {}) or {})
    resolved_status = str(data.get("job_status", "ready" if still_review else "completed") or "")
    if not still_review and resolved_status == "ready":
        resolved_status = "completed"
    resolved_stage = str(data.get("stage", "review" if still_review else "done") or "")
    if not still_review and resolved_stage == "execution":
        resolved_stage = "done"
    controller.update_state(
        created_count=int(result_summary.get("created_count", 0) or 0),
        updated_count=int(result_summary.get("updated_count", 0) or 0),
        skipped_count=int(result_summary.get("skipped_count", 0) or 0),
        error_count=int(result_summary.get("error_count", data.get("error_count", 0)) or 0),
        review_rows=still_review,
        review_groups=review_groups,
        review_count=int(data.get("still_review_count", 0) or 0),
        review_pending_group_count=int(
            data.get("review_pending_group_count", len(review_groups)) or len(review_groups)
        ),
        review_overflow_count=int(
            data.get("review_overflow_count", result_summary.get("review_overflow_count", 0)) or 0
        ),
        review_total_count=int(
            data.get("review_total_count", result_summary.get("review_total_count", 0)) or 0
        ),
        review_state=str(
            data.get("review_state", result_summary.get("review_state", "normal")) or "normal"
        ),
        overflow_blocking=bool(
            data.get("overflow_blocking", result_summary.get("overflow_blocking", False))
        ),
        review_disabled=bool(
            data.get("review_disabled", result_summary.get("review_disabled", False))
        ),
        review_disabled_reason=str(
            data.get(
                "review_disabled_reason",
                result_summary.get("review_disabled_reason", ""),
            )
            or ""
        ),
        result_entity_counts=dict(data.get("result_entity_counts", {}) or {}),
        result_auto_fix_summary=dict(data.get("result_auto_fix_summary", {}) or {}),
        result_attention_summary=dict(data.get("result_attention_summary", {}) or {}),
        stage=resolved_stage,
        status=resolved_status,
    )
    if not still_review:
        return False, ""
    count = int(data.get("still_review_count", len(still_review)) or len(still_review))
    return True, _TR("{count} lines still need a quick review.").format(count=count)


__all__ = ["apply_final_review_submit_response"]
