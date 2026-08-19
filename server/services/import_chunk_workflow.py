"""Compatibility facade for distributed importer workflow helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from django.db import transaction

from server.imports.models import (
    ImportArtifactManifest,
    ImportChunk,
    ImportChunkPhase,
    ImportJob,
)
from server.services.import_runtime_artifacts import iter_jsonl_entries
from server.services.import_types import ImportResult, PreparedImportArtifact, ReviewRows
from server.services.import_workflow_dispatch import (
    WorkflowDispatchPlan,
    advance_workflow_dispatch,
    aggregate_review_overflow_count,
)
from server.services.import_workflow_leases import (
    StaleImportPhaseLeaseError,
    acquire_phase,
    cancel_pending_phases,
    complete_phase,
    fail_phase,
    heartbeat_phase_lease,
    phase_lease_active,
    request_workflow_cancellation,
    requeue_expired_import_phases,
)
from server.services.import_workflow_manifests import (
    _collected_review_rows_impl,
    job_manifest,
    manifest_for_chunk,
    persist_file_manifest,
    persist_json_manifest,
    persist_jsonl_manifest,
)
from server.services.import_workflow_manifests import (
    _persist_root_index_manifest as _persist_root_index_manifest_impl,
)
from server.services.import_workflow_manifests import (
    load_manifest_to_temp as _load_manifest_to_temp_impl,
)
from server.services.import_workflow_manifests import (
    stage_prepared_artifact as _stage_prepared_artifact_impl,
)
from server.services.import_workflow_storage import (
    _save_workflow_payload,
    build_workflow_fingerprint,
    save_workflow_payload,
    workflow_params,
    workflow_payload,
    workflow_state_for_job,
)
from server.services.import_workflow_storage import (
    clear_distributed_workflow as _clear_distributed_workflow_impl,
)
from server.services.import_workflow_storage import (
    initialize_distributed_workflow as _initialize_distributed_workflow_impl,
)
from server.services.storage import purge_storage_object_now


def load_manifest_to_temp(
    manifest: ImportArtifactManifest,
    *,
    suffix: str | None = ".jsonl",
) -> Path:
    return _load_manifest_to_temp_impl(manifest, suffix=suffix)


def load_jsonl_manifest_rows(manifest: ImportArtifactManifest) -> list[dict[str, Any]]:
    temp_path = load_manifest_to_temp(manifest, suffix=".jsonl")
    try:
        return [dict(entry) for entry in iter_jsonl_entries(temp_path)]
    finally:
        try:
            temp_path.unlink()
        except OSError:
            pass


def load_json_manifest(manifest: ImportArtifactManifest) -> dict[str, Any]:
    temp_path = load_manifest_to_temp(manifest, suffix=".json")
    try:
        with temp_path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return dict(payload) if isinstance(payload, dict) else {}
    finally:
        try:
            temp_path.unlink()
        except OSError:
            pass


def clear_distributed_workflow(
    *,
    job: ImportJob,
    delete_objects: bool = True,
) -> None:
    _clear_distributed_workflow_impl(
        job=job,
        delete_objects=delete_objects,
        delete_artifact_fn=purge_storage_object_now,
    )


def stage_prepared_artifact(
    *,
    job: ImportJob,
    artifact: PreparedImportArtifact,
    review_rows: ReviewRows,
    errors: list[dict[str, Any]],
    result: ImportResult,
) -> None:
    return _stage_prepared_artifact_impl(
        job=job,
        artifact=artifact,
        review_rows=review_rows,
        errors=errors,
        result=result,
        persist_file_manifest_fn=persist_file_manifest,
        persist_jsonl_manifest_fn=persist_jsonl_manifest,
        clear_distributed_workflow_fn=clear_distributed_workflow,
        workflow_payload_fn=workflow_payload,
        save_workflow_payload_fn=_save_workflow_payload,
    )


def collected_review_rows(job: ImportJob) -> tuple[ReviewRows, list[dict[str, Any]]]:
    return _collected_review_rows_impl(
        job,
        load_jsonl_manifest_rows_fn=load_jsonl_manifest_rows,
        workflow_payload_fn=workflow_payload,
        aggregate_review_overflow_count_fn=aggregate_review_overflow_count,
    )


def _persist_root_index_manifest(
    *,
    job: ImportJob,
    artifact_kind: str,
    payload: dict[str, Any],
    phase: str,
) -> dict[str, Any]:
    return _persist_root_index_manifest_impl(
        job=job,
        artifact_kind=artifact_kind,
        payload=payload,
        phase=phase,
        persist_json_manifest_fn=persist_json_manifest,
    )


def initialize_distributed_workflow(
    *,
    job: ImportJob,
    entity_type: str,
    duplicate_strategy: str,
    skip_rows: int,
    skip_review_rows: bool,
    corrections: dict[str, dict[str, object]] | None,
) -> tuple[dict[str, Any], bool]:
    return _initialize_distributed_workflow_impl(
        job=job,
        entity_type=entity_type,
        duplicate_strategy=duplicate_strategy,
        skip_rows=skip_rows,
        skip_review_rows=skip_review_rows,
        corrections=corrections,
        delete_artifact_fn=purge_storage_object_now,
    )


def advance_workflow(job_id: str) -> WorkflowDispatchPlan:
    with transaction.atomic():
        job = ImportJob.objects.select_for_update().get(id=job_id)
        payload = workflow_payload(job)
        if not payload or not payload.get("prepare_completed"):
            return WorkflowDispatchPlan()
        if job.status != ImportJob.Status.RUNNING or bool(payload.get("cancel_requested", False)):
            return WorkflowDispatchPlan()
        chunks = list(ImportChunk.objects.filter(job=job).order_by("chunk_role", "ordinal", "id"))
        phases = list(
            ImportChunkPhase.objects.filter(chunk__job=job)
            .select_related("chunk")
            .order_by("chunk__chunk_role", "chunk__ordinal", "id")
        )
        return advance_workflow_dispatch(
            job=job,
            payload=payload,
            chunks=chunks,
            phases=phases,
            save_workflow_payload_fn=_save_workflow_payload,
            persist_root_index_manifest_fn=_persist_root_index_manifest,
        )


__all__ = [
    "WorkflowDispatchPlan",
    "StaleImportPhaseLeaseError",
    "acquire_phase",
    "advance_workflow",
    "build_workflow_fingerprint",
    "cancel_pending_phases",
    "clear_distributed_workflow",
    "collected_review_rows",
    "complete_phase",
    "fail_phase",
    "heartbeat_phase_lease",
    "initialize_distributed_workflow",
    "job_manifest",
    "load_json_manifest",
    "load_jsonl_manifest_rows",
    "load_manifest_to_temp",
    "manifest_for_chunk",
    "phase_lease_active",
    "persist_file_manifest",
    "persist_json_manifest",
    "persist_jsonl_manifest",
    "requeue_expired_import_phases",
    "request_workflow_cancellation",
    "save_workflow_payload",
    "stage_prepared_artifact",
    "workflow_params",
    "workflow_payload",
    "workflow_state_for_job",
]
