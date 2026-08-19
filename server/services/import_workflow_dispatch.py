"""Workflow dispatch and progress helpers for distributed importer execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from server.imports.models import ImportArtifactManifest, ImportChunk, ImportChunkPhase, ImportJob
from server.services.import_job_topology import job_topology
from server.services.import_progress_runtime import build_progress_detail

_ARTIFACT_ROOT_PLAN_INDEX = "root_plan_index"
_ARTIFACT_ROOT_LOAD_ANCHOR_MAP = "root_load_anchor_map"


@dataclass
class WorkflowDispatchPlan:
    plan_phase_ids: list[int] = field(default_factory=list)
    load_phase_ids: list[int] = field(default_factory=list)
    finalize_job: bool = False


def aggregate_review_overflow_count(
    *,
    workflow: dict[str, Any],
    phases: list[ImportChunkPhase],
) -> int:
    prepare_counts = dict(workflow.get("prepare_counts", {}) or {})
    overflow_count = int(prepare_counts.get("review_overflow_count", 0) or 0)
    for phase in phases:
        metrics = dict(phase.metrics_payload or {})
        overflow_count += int(metrics.get("review_overflow_count", 0) or 0)
    return max(0, overflow_count)


def rollup_workflow_progress(
    *,
    job: ImportJob,
    workflow: dict[str, Any],
    phases: list[ImportChunkPhase],
) -> None:
    total_rows = int((job.result_summary or {}).get("row_count") or 0)
    completed_rows = 0
    created_rows = 0
    skipped_rows = 0
    prepare_counts = dict(workflow.get("prepare_counts", {}) or {})
    review_rows_count = int(prepare_counts.get("review_count", 0) or 0)
    error_rows = int(prepare_counts.get("error_count", 0) or 0)
    review_overflow_total = aggregate_review_overflow_count(workflow=workflow, phases=phases)
    for phase in phases:
        metrics = dict(phase.metrics_payload or {})
        completed_rows += int(metrics.get("processed_count", 0) or 0)
        created_rows += int(metrics.get("created_count", 0) or 0)
        skipped_rows += int(metrics.get("skipped_count", 0) or 0)
        review_rows_count += int(metrics.get("review_count", 0) or 0)
        error_rows += int(metrics.get("error_count", 0) or 0)
    review_rows_total = review_rows_count + review_overflow_total
    total_phase_slots = max(1, len(phases) + 1)
    completed_phase_slots = (1 if workflow.get("prepare_completed") else 0) + sum(
        1 for phase in phases if phase.status == ImportChunkPhase.Status.COMPLETED
    )
    running_phases = [phase for phase in phases if phase.status in {"queued", "running", "pending"}]
    if any(phase.phase == ImportChunkPhase.Phase.LOAD for phase in running_phases):
        phase_name = "executing"
    elif running_phases:
        phase_name = "planning"
    elif workflow.get("finalize_queued"):
        phase_name = "rebuild"
    else:
        phase_name = "mapping"
    progress = min(99, int((completed_phase_slots / total_phase_slots) * 99))
    progress_detail = build_progress_detail(
        rows_total=total_rows,
        rows_processed=min(total_rows, completed_rows),
        rows_created=created_rows,
        rows_updated=0,
        rows_skipped=skipped_rows,
        rows_review=review_rows_total,
        current_chunk=completed_phase_slots,
        chunks_total=total_phase_slots,
        phase=phase_name,
        bundle_mode=job_topology(job).bundle_mode,
        review_overflow_count_value=review_overflow_total,
    )
    job.progress = progress
    job.progress_detail = {
        **progress_detail,
        "error_count": error_rows,
    }
    job.save(update_fields=["progress", "progress_detail", "updated_at"])


def _completed(phases: list[ImportChunkPhase]) -> bool:
    return bool(phases) and all(
        phase.status == ImportChunkPhase.Status.COMPLETED for phase in phases
    )


def _has_failed(phases: list[ImportChunkPhase]) -> bool:
    return any(phase.status == ImportChunkPhase.Status.FAILED for phase in phases)


def _queue_pending(
    phases: list[ImportChunkPhase],
    *,
    allow_blocked: bool = False,
) -> list[int]:
    queued: list[int] = []
    for phase in phases:
        if phase.status == ImportChunkPhase.Status.PENDING or (
            allow_blocked and phase.status == ImportChunkPhase.Status.BLOCKED
        ):
            phase.status = ImportChunkPhase.Status.QUEUED
            phase.save(update_fields=["status", "updated_at"])
            queued.append(int(phase.id))
    return queued


def _aggregate_root_plan_index(phases: list[ImportChunkPhase]) -> dict[str, Any]:
    existing_anchor_map: dict[str, int] = {}
    planned_root_anchor_keys: set[str] = set()
    for phase in phases:
        metrics = dict(phase.metrics_payload or {})
        for key, value in dict(metrics.get("existing_anchor_map", {}) or {}).items():
            try:
                existing_anchor_map[str(key)] = int(value)
            except (TypeError, ValueError):
                continue
        for key in list(metrics.get("planned_root_anchor_keys", []) or []):
            key_text = str(key or "").strip()
            if key_text:
                planned_root_anchor_keys.add(key_text)
    return {
        "existing_anchor_map": existing_anchor_map,
        "planned_root_anchor_keys": sorted(planned_root_anchor_keys),
    }


def _aggregate_root_load_anchor_map(phases: list[ImportChunkPhase]) -> dict[str, int]:
    created_anchor_map: dict[str, int] = {}
    for phase in phases:
        metrics = dict(phase.metrics_payload or {})
        for key, value in dict(metrics.get("created_anchor_map", {}) or {}).items():
            try:
                created_anchor_map[str(key)] = int(value)
            except (TypeError, ValueError):
                continue
    return created_anchor_map


def advance_workflow_dispatch(
    *,
    job: ImportJob,
    payload: dict[str, Any],
    chunks: list[ImportChunk],
    phases: list[ImportChunkPhase],
    save_workflow_payload_fn: Callable[[ImportJob, dict[str, Any]], None],
    persist_root_index_manifest_fn: Callable[..., dict[str, Any]],
) -> WorkflowDispatchPlan:
    dispatch = WorkflowDispatchPlan()
    rollup_workflow_progress(job=job, workflow=payload, phases=phases)
    if _has_failed(phases):
        return dispatch
    if not chunks:
        if not payload.get("finalize_queued"):
            payload["finalize_queued"] = True
            save_workflow_payload_fn(job, payload)
            dispatch.finalize_job = True
        return dispatch

    if payload.get("bundle_mode") == "same_side_bundle":
        root_plan = [
            phase
            for phase in phases
            if phase.phase == ImportChunkPhase.Phase.PLAN
            and phase.chunk.chunk_role == ImportChunk.Role.ROOT
        ]
        child_plan = [
            phase
            for phase in phases
            if phase.phase == ImportChunkPhase.Phase.PLAN
            and phase.chunk.chunk_role == ImportChunk.Role.CHILD
        ]
        root_load = [
            phase
            for phase in phases
            if phase.phase == ImportChunkPhase.Phase.LOAD
            and phase.chunk.chunk_role == ImportChunk.Role.ROOT
        ]
        child_load = [
            phase
            for phase in phases
            if phase.phase == ImportChunkPhase.Phase.LOAD
            and phase.chunk.chunk_role == ImportChunk.Role.CHILD
        ]
        if not root_plan and not payload.get("root_plan_index_ready"):
            payload["root_plan_index_manifest_id"] = 0
            payload["root_plan_index_checksum"] = ""
            payload["root_plan_index_key_count"] = 0
            payload["root_plan_index_ready"] = True
            save_workflow_payload_fn(job, payload)
        if not payload.get("root_plan_index_ready"):
            if _completed(root_plan):
                manifest_meta = persist_root_index_manifest_fn(
                    job=job,
                    artifact_kind=_ARTIFACT_ROOT_PLAN_INDEX,
                    payload=_aggregate_root_plan_index(root_plan),
                    phase=ImportArtifactManifest.Phase.PLAN,
                )
                payload["root_plan_index_manifest_id"] = manifest_meta["manifest_id"]
                payload["root_plan_index_checksum"] = manifest_meta["checksum"]
                payload["root_plan_index_key_count"] = manifest_meta["key_count"]
                payload["root_plan_index_ready"] = True
                save_workflow_payload_fn(job, payload)
            else:
                dispatch.plan_phase_ids.extend(_queue_pending(root_plan))
                return dispatch

        if child_plan:
            dispatch.plan_phase_ids.extend(_queue_pending(child_plan, allow_blocked=True))
            if not _completed(child_plan):
                dispatch.load_phase_ids.extend(_queue_pending(root_load, allow_blocked=True))
                return dispatch

        if root_load:
            dispatch.load_phase_ids.extend(_queue_pending(root_load, allow_blocked=True))
            if not payload.get("root_load_anchor_map_ready"):
                if _completed(root_load):
                    manifest_meta = persist_root_index_manifest_fn(
                        job=job,
                        artifact_kind=_ARTIFACT_ROOT_LOAD_ANCHOR_MAP,
                        payload=_aggregate_root_load_anchor_map(root_load),
                        phase=ImportArtifactManifest.Phase.LOAD,
                    )
                    payload["root_load_anchor_map_manifest_id"] = manifest_meta["manifest_id"]
                    payload["root_load_anchor_map_checksum"] = manifest_meta["checksum"]
                    payload["root_load_anchor_map_key_count"] = manifest_meta["key_count"]
                    payload["root_load_anchor_map_ready"] = True
                    save_workflow_payload_fn(job, payload)
                else:
                    return dispatch
        elif not payload.get("root_load_anchor_map_ready"):
            payload["root_load_anchor_map_manifest_id"] = 0
            payload["root_load_anchor_map_checksum"] = ""
            payload["root_load_anchor_map_key_count"] = 0
            payload["root_load_anchor_map_ready"] = True
            save_workflow_payload_fn(job, payload)

        if child_load:
            dispatch.load_phase_ids.extend(_queue_pending(child_load, allow_blocked=True))
            if not _completed(child_load):
                return dispatch
    else:
        plan_phases = [phase for phase in phases if phase.phase == ImportChunkPhase.Phase.PLAN]
        load_phases = [phase for phase in phases if phase.phase == ImportChunkPhase.Phase.LOAD]
        dispatch.plan_phase_ids.extend(_queue_pending(plan_phases))
        if not _completed(plan_phases):
            return dispatch
        dispatch.load_phase_ids.extend(_queue_pending(load_phases, allow_blocked=True))
        if not _completed(load_phases):
            return dispatch

    if not payload.get("finalize_queued"):
        payload["finalize_queued"] = True
        save_workflow_payload_fn(job, payload)
        dispatch.finalize_job = True
    return dispatch


__all__ = [
    "WorkflowDispatchPlan",
    "advance_workflow_dispatch",
    "aggregate_review_overflow_count",
    "rollup_workflow_progress",
]
