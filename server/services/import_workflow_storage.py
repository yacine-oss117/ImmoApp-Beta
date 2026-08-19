"""Workflow state storage helpers for distributed importer execution."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, cast

from django.db.utils import DatabaseError, OperationalError, ProgrammingError
from django.utils import timezone

from server.imports.models import (
    ImportArtifactManifest,
    ImportChunk,
    ImportJob,
    ImportWorkflowState,
)
from server.services.import_artifact_checkpoint import (
    build_planned_artifact_fingerprint,
    clear_planned_artifact_checkpoint,
)
from server.services.import_job_topology import job_topology
from server.services.json_safe import json_safe_value

_WORKFLOW_KEY = "workflow"
_WORKFLOW_METADATA_KEYS = {
    "version",
    "prepare_chunk_counts",
    "execution_cost",
    "review_overflow_count",
}


def _normalize_json_dict(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _parse_datetimeish(value: object) -> Any:
    if value in {None, ""}:
        return None
    if hasattr(value, "tzinfo"):
        return value
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _legacy_workflow_payload(job: ImportJob) -> dict[str, Any]:
    return dict((job.result_summary or {}).get(_WORKFLOW_KEY, {}) or {})


def _workflow_state_payload(state: ImportWorkflowState) -> dict[str, Any]:
    payload = _normalize_json_dict(state.metadata)
    payload.update(
        {
            "run_id": str(state.run_id or ""),
            "status": str(state.status or ""),
            "fingerprint": str(state.fingerprint or ""),
            "bundle_mode": str(state.bundle_mode or ""),
            "topology_side": str(state.topology_side or ""),
            "params": _normalize_json_dict(state.params),
            "prepare_completed": bool(state.prepare_completed),
            "prepare_counts": _normalize_json_dict(state.prepare_counts),
            "load_counts": _normalize_json_dict(state.load_counts),
            "cancel_requested": bool(state.cancel_requested),
            "queue_position": int(state.queue_position or 0),
            "execution_profile": str(state.execution_profile or ""),
            "admission_mode": str(state.admission_mode or ""),
            "pressure_reason": str(state.pressure_reason or ""),
            "root_plan_index_ready": bool(state.root_plan_index_ready),
            "root_plan_index_manifest_id": int(state.root_plan_index_manifest_id or 0),
            "root_plan_index_checksum": str(state.root_plan_index_checksum or ""),
            "root_plan_index_key_count": int(state.root_plan_index_key_count or 0),
            "root_load_anchor_map_ready": bool(state.root_load_anchor_map_ready),
            "root_load_anchor_map_manifest_id": int(state.root_load_anchor_map_manifest_id or 0),
            "root_load_anchor_map_checksum": str(state.root_load_anchor_map_checksum or ""),
            "root_load_anchor_map_key_count": int(state.root_load_anchor_map_key_count or 0),
            "finalize_queued": bool(state.finalize_queued),
            "finalized": bool(state.finalized),
        }
    )
    if state.queued_at is not None:
        payload["queued_at"] = state.queued_at.isoformat()
    if state.started_at is not None:
        payload["started_at"] = state.started_at.isoformat()
    if state.finished_at is not None:
        payload["finished_at"] = state.finished_at.isoformat()
    return payload


def _copy_payload_to_workflow_state(state: ImportWorkflowState, payload: dict[str, Any]) -> None:
    metadata = {
        key: json_safe_value(value)
        for key, value in payload.items()
        if key in _WORKFLOW_METADATA_KEYS
    }
    explicit_keys = {
        "run_id",
        "status",
        "fingerprint",
        "bundle_mode",
        "topology_side",
        "params",
        "prepare_completed",
        "prepare_counts",
        "load_counts",
        "cancel_requested",
        "queue_position",
        "queued_at",
        "execution_profile",
        "admission_mode",
        "pressure_reason",
        "root_plan_index_ready",
        "root_plan_index_manifest_id",
        "root_plan_index_checksum",
        "root_plan_index_key_count",
        "root_load_anchor_map_ready",
        "root_load_anchor_map_manifest_id",
        "root_load_anchor_map_checksum",
        "root_load_anchor_map_key_count",
        "finalize_queued",
        "finalized",
        "started_at",
        "finished_at",
    }
    metadata.update(
        {
            key: json_safe_value(value)
            for key, value in payload.items()
            if key not in explicit_keys and key not in _WORKFLOW_METADATA_KEYS
        }
    )
    state.run_id = str(payload.get("run_id", "") or "")
    state.status = str(payload.get("status", "") or "")
    state.fingerprint = str(payload.get("fingerprint", "") or "")
    state.bundle_mode = str(payload.get("bundle_mode", "") or "")
    state.topology_side = str(payload.get("topology_side", "") or "")
    state.params = cast(
        dict[str, Any], json_safe_value(_normalize_json_dict(payload.get("params")))
    )
    state.prepare_completed = bool(payload.get("prepare_completed", False))
    state.prepare_counts = cast(
        dict[str, Any],
        json_safe_value(_normalize_json_dict(payload.get("prepare_counts"))),
    )
    state.load_counts = cast(
        dict[str, Any],
        json_safe_value(_normalize_json_dict(payload.get("load_counts"))),
    )
    state.cancel_requested = bool(payload.get("cancel_requested", False))
    state.queue_position = int(payload.get("queue_position", 0) or 0)
    state.queued_at = _parse_datetimeish(payload.get("queued_at"))
    state.execution_profile = str(payload.get("execution_profile", "") or "")
    state.admission_mode = str(payload.get("admission_mode", "") or "")
    state.pressure_reason = str(payload.get("pressure_reason", "") or "")
    state.root_plan_index_ready = bool(payload.get("root_plan_index_ready", False))
    state.root_plan_index_manifest_id = int(payload.get("root_plan_index_manifest_id", 0) or 0)
    state.root_plan_index_checksum = str(payload.get("root_plan_index_checksum", "") or "")
    state.root_plan_index_key_count = int(payload.get("root_plan_index_key_count", 0) or 0)
    state.root_load_anchor_map_ready = bool(payload.get("root_load_anchor_map_ready", False))
    state.root_load_anchor_map_manifest_id = int(
        payload.get("root_load_anchor_map_manifest_id", 0) or 0
    )
    state.root_load_anchor_map_checksum = str(
        payload.get("root_load_anchor_map_checksum", "") or ""
    )
    state.root_load_anchor_map_key_count = int(
        payload.get("root_load_anchor_map_key_count", 0) or 0
    )
    state.finalize_queued = bool(payload.get("finalize_queued", False))
    state.finalized = bool(payload.get("finalized", False))
    state.started_at = _parse_datetimeish(payload.get("started_at"))
    state.finished_at = _parse_datetimeish(payload.get("finished_at"))
    state.metadata = cast(dict[str, Any], json_safe_value(metadata))


def workflow_state_for_job(job: ImportJob) -> ImportWorkflowState | None:
    try:
        state = getattr(job, "workflow_state", None)
    except Exception:
        state = None
    if isinstance(state, ImportWorkflowState):
        return state
    try:
        return cast(ImportWorkflowState | None, ImportWorkflowState.objects.filter(job=job).first())
    except (DatabaseError, OperationalError, ProgrammingError):
        return None


def workflow_payload(job: ImportJob) -> dict[str, Any]:
    state = workflow_state_for_job(job)
    if state is not None:
        return _workflow_state_payload(state)
    return _legacy_workflow_payload(job)


def workflow_params(job: ImportJob) -> dict[str, Any]:
    payload = workflow_payload(job)
    params = payload.get("params")
    return dict(params) if isinstance(params, dict) else {}


def save_workflow_payload(job: ImportJob, payload: dict[str, Any]) -> None:
    state = workflow_state_for_job(job)
    if state is not None:
        try:
            _copy_payload_to_workflow_state(state, payload)
            state.save()
            cast(Any, job).workflow_state = state
            result_summary = dict(job.result_summary or {})
            if _WORKFLOW_KEY in result_summary:
                result_summary.pop(_WORKFLOW_KEY, None)
                job.result_summary = cast(dict[str, Any], json_safe_value(result_summary))
                job.save(update_fields=["result_summary", "updated_at"])
            return
        except (DatabaseError, OperationalError, ProgrammingError):
            pass
    else:
        try:
            state = ImportWorkflowState(job=job)
            _copy_payload_to_workflow_state(state, payload)
            state.save()
            cast(Any, job).workflow_state = state
            result_summary = dict(job.result_summary or {})
            if _WORKFLOW_KEY in result_summary:
                result_summary.pop(_WORKFLOW_KEY, None)
                job.result_summary = cast(dict[str, Any], json_safe_value(result_summary))
                job.save(update_fields=["result_summary", "updated_at"])
            return
        except (DatabaseError, OperationalError, ProgrammingError):
            pass
    result_summary = dict(job.result_summary or {})
    result_summary[_WORKFLOW_KEY] = cast(dict[str, Any], json_safe_value(payload))
    job.result_summary = cast(dict[str, Any], json_safe_value(result_summary))
    job.save(update_fields=["result_summary", "updated_at"])


def _save_workflow_payload(job: ImportJob, payload: dict[str, Any]) -> None:
    save_workflow_payload(job, payload)


def _clear_workflow_payload(job: ImportJob) -> None:
    try:
        ImportWorkflowState.objects.filter(job=job).delete()
    except (DatabaseError, OperationalError, ProgrammingError):
        pass
    result_summary = dict(job.result_summary or {})
    if _WORKFLOW_KEY in result_summary:
        result_summary.pop(_WORKFLOW_KEY, None)
        job.result_summary = cast(dict[str, Any], json_safe_value(result_summary))
        job.save(update_fields=["result_summary", "updated_at"])


def build_workflow_fingerprint(
    *,
    job: ImportJob,
    entity_type: str,
    duplicate_strategy: str,
    skip_rows: int,
    skip_review_rows: bool,
    corrections: dict[str, dict[str, object]] | None,
) -> str:
    return build_planned_artifact_fingerprint(
        job=cast(Any, job),
        entity_type=entity_type,
        duplicate_strategy=duplicate_strategy,
        skip_rows=skip_rows,
        skip_review_rows=skip_review_rows,
        corrections=corrections,
    )


def clear_distributed_workflow(
    *,
    job: ImportJob,
    delete_objects: bool = True,
    delete_artifact_fn: Any,
) -> None:
    manifests = list(ImportArtifactManifest.objects.filter(job=job))
    if delete_objects:
        for manifest in manifests:
            storage_id = str(manifest.storage_id or "").strip()
            if not storage_id:
                continue
            try:
                delete_artifact_fn(storage_id=storage_id)
            except Exception:
                pass
    ImportArtifactManifest.objects.filter(job=job).delete()
    ImportChunk.objects.filter(job=job).delete()
    clear_planned_artifact_checkpoint(job=cast(Any, job), delete_objects=delete_objects)
    _clear_workflow_payload(job)


def initialize_distributed_workflow(
    *,
    job: ImportJob,
    entity_type: str,
    duplicate_strategy: str,
    skip_rows: int,
    skip_review_rows: bool,
    corrections: dict[str, dict[str, object]] | None,
    delete_artifact_fn: Any,
) -> tuple[dict[str, Any], bool]:
    fingerprint = build_workflow_fingerprint(
        job=job,
        entity_type=entity_type,
        duplicate_strategy=duplicate_strategy,
        skip_rows=skip_rows,
        skip_review_rows=skip_review_rows,
        corrections=corrections,
    )
    existing = workflow_payload(job)
    if existing and str(existing.get("fingerprint", "")) == fingerprint:
        prepare_started = (
            bool(existing.get("prepare_completed", False))
            or ImportChunk.objects.filter(job=job).exists()
        )
        if bool(existing.get("finalize_queued", False)) or bool(existing.get("finalized", False)):
            prepare_started = True
        return existing, not prepare_started

    clear_distributed_workflow(
        job=job,
        delete_artifact_fn=delete_artifact_fn,
    )
    topology = job_topology(job)
    payload = {
        "version": 1,
        "run_id": str(uuid.uuid4()),
        "fingerprint": fingerprint,
        "bundle_mode": topology.bundle_mode,
        "topology_side": topology.topology_side,
        "params": {
            "entity_type": entity_type,
            "duplicate_strategy": duplicate_strategy,
            "skip_rows": int(skip_rows or 0),
            "skip_review_rows": bool(skip_review_rows),
            "corrections": cast(dict[str, Any], json_safe_value(dict(corrections or {}))),
            "column_mapping": dict(job.column_mapping or {}),
        },
        "prepare_completed": False,
        "prepare_counts": {
            "review_count": 0,
            "error_count": 0,
            "skipped_count": 0,
            "review_overflow_count": 0,
        },
        "cancel_requested": False,
        "queued_at": None,
        "root_plan_index_ready": False,
        "root_plan_index_manifest_id": 0,
        "root_plan_index_checksum": "",
        "root_plan_index_key_count": 0,
        "root_load_anchor_map_ready": False,
        "root_load_anchor_map_manifest_id": 0,
        "root_load_anchor_map_checksum": "",
        "root_load_anchor_map_key_count": 0,
        "finalize_queued": False,
        "finalized": False,
        "started_at": timezone.now().isoformat(),
    }
    _save_workflow_payload(job, payload)
    return payload, True


__all__ = [
    "build_workflow_fingerprint",
    "clear_distributed_workflow",
    "initialize_distributed_workflow",
    "save_workflow_payload",
    "workflow_params",
    "workflow_payload",
    "workflow_state_for_job",
]
