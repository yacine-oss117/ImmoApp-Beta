"""Post-import follow-up shaping, normalization, and persistence."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, TypedDict

from server.imports.models import ImportJob
from server.services.import_constants import normalize_entity_type
from server.services.import_jobs import get_job_by_id
from server.services.json_safe import json_safe_value

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FollowUpPersistenceTarget:
    resolved_job: ImportJob
    safe_outcome: dict[str, object]
    result_summary: dict[str, object]
    workflow_payload: dict[str, object] | None
    workflow_save_fn: Callable[[ImportJob, dict[str, object]], None] | None


class CacheInvalidationStepOutcome(TypedDict):
    state: Literal["completed", "best_effort_failed"]
    reason_code: str
    recovery_owner: str


class SuccessNotificationStepOutcome(TypedDict):
    state: Literal["completed", "deferred", "skipped"]
    reason_code: str
    recovery_owner: str


class RebuildHandoffStepOutcome(TypedDict):
    state: Literal["completed", "deferred", "skipped"]
    reason_code: str
    recovery_owner: str


class PostImportFollowUpSteps(TypedDict):
    cache_invalidation: CacheInvalidationStepOutcome
    success_notification: SuccessNotificationStepOutcome
    rebuild_handoff: RebuildHandoffStepOutcome


class PostImportFollowUpOutcome(TypedDict):
    state: Literal["completed", "partial", "deferred"]
    reason_code: str
    recovery_owner: str
    entities: list[str]
    steps: PostImportFollowUpSteps


def _normalized_follow_up_entities(entity_types: set[str]) -> list[str]:
    return sorted(
        {
            normalize_entity_type(value)
            for value in entity_types
            if str(normalize_entity_type(value) or "").strip()
        }
    )


def build_cache_invalidation_step(
    *,
    state: Literal["completed", "best_effort_failed"] = "completed",
    reason_code: str = "",
    recovery_owner: str = "",
) -> CacheInvalidationStepOutcome:
    return {
        "state": state,
        "reason_code": reason_code,
        "recovery_owner": recovery_owner,
    }


def build_success_notification_step(
    *,
    state: Literal["completed", "deferred", "skipped"] = "skipped",
    reason_code: str = "",
    recovery_owner: str = "",
) -> SuccessNotificationStepOutcome:
    return {
        "state": state,
        "reason_code": reason_code,
        "recovery_owner": recovery_owner,
    }


def build_rebuild_handoff_step(
    *,
    state: Literal["completed", "deferred", "skipped"] = "skipped",
    reason_code: str = "",
    recovery_owner: str = "",
) -> RebuildHandoffStepOutcome:
    return {
        "state": state,
        "reason_code": reason_code,
        "recovery_owner": recovery_owner,
    }


def _default_follow_up_steps(
    *,
    has_entities: bool,
    success_notification_step: SuccessNotificationStepOutcome | None = None,
) -> PostImportFollowUpSteps:
    return {
        "cache_invalidation": build_cache_invalidation_step(),
        "success_notification": (
            success_notification_step
            if success_notification_step is not None
            else build_success_notification_step()
        ),
        "rebuild_handoff": build_rebuild_handoff_step(
            state="completed" if has_entities else "skipped"
        ),
    }


def _build_follow_up_outcome(
    *,
    state: Literal["completed", "partial", "deferred"],
    entities: set[str],
    steps: PostImportFollowUpSteps,
    reason_code: str = "",
    recovery_owner: str = "",
) -> PostImportFollowUpOutcome:
    return {
        "state": state,
        "reason_code": reason_code,
        "recovery_owner": recovery_owner,
        "entities": _normalized_follow_up_entities(entities),
        "steps": steps,
    }


def _derive_follow_up_outcome(
    *,
    entities: set[str],
    steps: PostImportFollowUpSteps,
) -> PostImportFollowUpOutcome:
    if steps["rebuild_handoff"]["state"] == "deferred":
        return _build_follow_up_outcome(
            state="deferred",
            reason_code="rebuild_enqueue_failed",
            recovery_owner="existing_match_recovery",
            entities=entities,
            steps=steps,
        )
    if (
        steps["cache_invalidation"]["state"] == "best_effort_failed"
        or steps["success_notification"]["state"] == "deferred"
    ):
        return _build_follow_up_outcome(
            state="partial",
            reason_code="noncritical_follow_up_failed",
            recovery_owner="",
            entities=entities,
            steps=steps,
        )
    return _build_follow_up_outcome(
        state="completed",
        reason_code="",
        recovery_owner="",
        entities=entities,
        steps=steps,
    )


def _normalize_cache_invalidation_step(value: object) -> CacheInvalidationStepOutcome:
    if not isinstance(value, dict):
        return build_cache_invalidation_step()
    if str(value.get("state") or "").strip().lower() == "best_effort_failed":
        return build_cache_invalidation_step(
            state="best_effort_failed",
            reason_code="cache_invalidation_failed",
            recovery_owner="durable_surface_generation",
        )
    return build_cache_invalidation_step()


def _normalize_success_notification_step(value: object) -> SuccessNotificationStepOutcome:
    if not isinstance(value, dict):
        return build_success_notification_step()
    normalized_state = str(value.get("state") or "").strip().lower()
    if normalized_state in {"best_effort_failed", "deferred"}:
        return build_success_notification_step(
            state="deferred",
            reason_code="notification_record_deferred",
            recovery_owner="canonical_notification_subsystem",
        )
    if normalized_state == "completed":
        return build_success_notification_step(state="completed")
    return build_success_notification_step(state="skipped")


def _normalize_rebuild_handoff_step(
    value: object,
    *,
    has_entities: bool,
) -> RebuildHandoffStepOutcome:
    if not isinstance(value, dict):
        return build_rebuild_handoff_step(state="completed" if has_entities else "skipped")
    normalized_state = str(value.get("state") or "").strip().lower()
    if normalized_state == "deferred":
        return build_rebuild_handoff_step(
            state="deferred",
            reason_code="rebuild_enqueue_failed",
            recovery_owner="existing_match_recovery",
        )
    if normalized_state == "completed":
        return build_rebuild_handoff_step(state="completed")
    return build_rebuild_handoff_step(state="skipped")


def normalize_follow_up_outcome(value: object) -> PostImportFollowUpOutcome:
    if not isinstance(value, dict):
        return _derive_follow_up_outcome(
            entities=set(),
            steps=_default_follow_up_steps(has_entities=False),
        )

    raw_entities = value.get("entities")
    entities = {
        normalize_entity_type(item)
        for item in (list(raw_entities) if isinstance(raw_entities, list) else [])
        if str(normalize_entity_type(item) or "").strip()
    }
    raw_steps = value.get("steps")
    if isinstance(raw_steps, dict):
        steps: PostImportFollowUpSteps = {
            "cache_invalidation": _normalize_cache_invalidation_step(
                raw_steps.get("cache_invalidation")
            ),
            "success_notification": _normalize_success_notification_step(
                raw_steps.get("success_notification")
            ),
            "rebuild_handoff": _normalize_rebuild_handoff_step(
                raw_steps.get("rebuild_handoff"),
                has_entities=bool(entities),
            ),
        }
        return _derive_follow_up_outcome(entities=entities, steps=steps)

    legacy_state = str(value.get("state") or "").strip().lower()
    steps = _default_follow_up_steps(has_entities=bool(entities))
    if legacy_state == "deferred":
        steps["rebuild_handoff"] = build_rebuild_handoff_step(
            state="deferred",
            reason_code="rebuild_enqueue_failed",
            recovery_owner="existing_match_recovery",
        )
    return _derive_follow_up_outcome(entities=entities, steps=steps)


def merge_follow_up_outcomes(existing: object, incoming: object) -> PostImportFollowUpOutcome:
    normalized_existing = normalize_follow_up_outcome(existing)
    normalized_incoming = normalize_follow_up_outcome(incoming)
    entities = set(normalized_existing["entities"]) | set(normalized_incoming["entities"])
    existing_steps = normalized_existing["steps"]
    incoming_steps = normalized_incoming["steps"]
    success_step = incoming_steps["success_notification"]
    if success_step["state"] == "skipped":
        success_step = existing_steps["success_notification"]
    steps: PostImportFollowUpSteps = {
        "cache_invalidation": (
            incoming_steps["cache_invalidation"]
            if incoming_steps["cache_invalidation"]["state"] == "best_effort_failed"
            or existing_steps["cache_invalidation"]["state"] != "best_effort_failed"
            else existing_steps["cache_invalidation"]
        ),
        "success_notification": success_step,
        "rebuild_handoff": (
            incoming_steps["rebuild_handoff"]
            if incoming_steps["rebuild_handoff"]["state"] == "deferred"
            or existing_steps["rebuild_handoff"]["state"] == "skipped"
            else existing_steps["rebuild_handoff"]
        ),
    }
    if (
        steps["rebuild_handoff"]["state"] == "skipped"
        and existing_steps["rebuild_handoff"]["state"] == "completed"
    ):
        steps["rebuild_handoff"] = existing_steps["rebuild_handoff"]
    return _derive_follow_up_outcome(entities=entities, steps=steps)


def run_post_import_follow_up(
    *,
    job_id: str,
    entity_types: set[str],
    success_notification_step: SuccessNotificationStepOutcome | None = None,
    rebuild_handoff: Callable[[], None],
) -> PostImportFollowUpOutcome:
    normalized_entities = set(_normalized_follow_up_entities(entity_types))
    steps = _default_follow_up_steps(
        has_entities=bool(normalized_entities),
        success_notification_step=success_notification_step,
    )
    if not normalized_entities:
        return _derive_follow_up_outcome(entities=set(), steps=steps)
    try:
        rebuild_handoff()
    except Exception:
        steps["rebuild_handoff"] = build_rebuild_handoff_step(
            state="deferred",
            reason_code="rebuild_enqueue_failed",
            recovery_owner="existing_match_recovery",
        )
        logger.warning(
            "Post-import rebuild handoff deferred for job %s; existing match recovery will repair derived state",
            job_id,
            exc_info=True,
        )
    return _derive_follow_up_outcome(entities=normalized_entities, steps=steps)


def _json_safe_dict(value: object) -> dict[str, object]:
    safe_value = json_safe_value(value)
    return dict(safe_value) if isinstance(safe_value, dict) else {}


def _resolve_follow_up_job(
    *,
    job: ImportJob | None,
    job_id: str,
) -> ImportJob | None:
    if job is not None:
        return job
    if not str(job_id or "").strip():
        return None
    try:
        resolved_job = get_job_by_id(job_id=job_id)
    except Exception:
        logger.warning(
            "Post-import follow-up state lookup failed for job %s",
            job_id,
            exc_info=True,
        )
        return None
    if resolved_job is None:
        logger.warning(
            "Post-import follow-up state could not be persisted; job %s is missing",
            job_id,
        )
    return resolved_job


def _merge_follow_up_payload(
    *,
    existing_follow_up: object,
    incoming_outcome: PostImportFollowUpOutcome,
) -> PostImportFollowUpOutcome:
    return merge_follow_up_outcomes(existing_follow_up, incoming_outcome)


def _resolve_workflow_follow_up_payload(
    *,
    resolved_job: ImportJob,
    workflow: dict[str, object] | None,
    save_workflow_payload_fn: Callable[[ImportJob, dict[str, object]], None] | None,
) -> tuple[
    dict[str, object] | None,
    Callable[[ImportJob, dict[str, object]], None] | None,
]:
    from server.services.import_workflow_storage import (
        save_workflow_payload as save_workflow_payload_impl,
    )
    from server.services.import_workflow_storage import (
        workflow_payload,
        workflow_state_for_job,
    )

    workflow_payload_value = workflow
    workflow_save_fn = save_workflow_payload_fn
    if workflow_payload_value is not None or workflow_state_for_job(resolved_job) is None:
        return workflow_payload_value, workflow_save_fn
    workflow_payload_value = {
        str(key): value for key, value in workflow_payload(resolved_job).items()
    }
    workflow_save_fn = save_workflow_payload_impl
    return workflow_payload_value, workflow_save_fn


def _apply_follow_up_to_result_summary(
    *,
    existing_summary: dict[str, object],
    merged_outcome: PostImportFollowUpOutcome,
) -> tuple[dict[str, object], dict[str, object]]:
    safe_outcome = _json_safe_dict(dict(merged_outcome))
    updated_summary = dict(existing_summary)
    updated_summary["follow_up"] = safe_outcome
    return _json_safe_dict(updated_summary), safe_outcome


def _save_follow_up_state(target: FollowUpPersistenceTarget) -> None:
    target.resolved_job.result_summary = target.result_summary
    if target.workflow_payload is not None and target.workflow_save_fn is not None:
        target.workflow_payload["follow_up"] = dict(target.safe_outcome)
        target.workflow_save_fn(target.resolved_job, target.workflow_payload)
    target.resolved_job.save(update_fields=["result_summary", "updated_at"])


def persist_post_import_follow_up(
    *,
    outcome: PostImportFollowUpOutcome,
    job: ImportJob | None = None,
    job_id: str = "",
    workflow: dict[str, object] | None = None,
    save_workflow_payload_fn: Callable[[ImportJob, dict[str, object]], None] | None = None,
) -> None:
    resolved_job = _resolve_follow_up_job(job=job, job_id=job_id)
    if resolved_job is None:
        return

    try:
        existing_summary = dict(resolved_job.result_summary or {})
        merged_outcome = _merge_follow_up_payload(
            existing_follow_up=existing_summary.get("follow_up"),
            incoming_outcome=outcome,
        )
        result_summary, safe_outcome = _apply_follow_up_to_result_summary(
            existing_summary=existing_summary,
            merged_outcome=merged_outcome,
        )
        workflow_payload_value, workflow_save_fn = _resolve_workflow_follow_up_payload(
            resolved_job=resolved_job,
            workflow=workflow,
            save_workflow_payload_fn=save_workflow_payload_fn,
        )
        _save_follow_up_state(
            FollowUpPersistenceTarget(
                resolved_job=resolved_job,
                safe_outcome=safe_outcome,
                result_summary=result_summary,
                workflow_payload=workflow_payload_value,
                workflow_save_fn=workflow_save_fn,
            )
        )
    except Exception:
        logger.warning(
            "Post-import follow-up state persistence failed for job %s",
            str(getattr(resolved_job, "id", job_id) or job_id),
            exc_info=True,
        )


__all__ = [
    "CacheInvalidationStepOutcome",
    "PostImportFollowUpOutcome",
    "PostImportFollowUpSteps",
    "RebuildHandoffStepOutcome",
    "SuccessNotificationStepOutcome",
    "build_success_notification_step",
    "merge_follow_up_outcomes",
    "normalize_follow_up_outcome",
    "persist_post_import_follow_up",
    "run_post_import_follow_up",
]
