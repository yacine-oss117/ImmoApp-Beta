"""Durable planned-artifact checkpoints for import execution resume."""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
import tempfile
from pathlib import Path
from typing import Any, BinaryIO, Protocol, cast

from server.services.import_constants import normalize_duplicate_strategy, normalize_entity_type
from server.services.import_runtime_artifacts import (
    iter_jsonl_entries,
    require_path,
)
from server.services.import_types import (
    PlannedArtifactCheckpoint,
    PreparedImportArtifact,
    ReviewRowBuffer,
    ReviewRowPayload,
    ReviewRows,
)
from server.services.json_safe import json_safe_value
from server.services.storage import download_to_temp, purge_storage_object_now, store_fileobj

logger = logging.getLogger(__name__)

_CHECKPOINT_KEY = "planned_artifact_checkpoint"


class _UploadArtifact(Protocol):
    def __call__(
        self,
        *,
        fileobj: BinaryIO,
        filename: str,
        content_type: str | None,
        purpose: str,
        user_id: int | None,
        role: str | None,
        created_ip: str | None,
    ) -> str: ...


class _DownloadArtifact(Protocol):
    def __call__(self, storage_id: str, *, suffix: str | None = None) -> Path: ...


class _DeleteArtifact(Protocol):
    def __call__(self, *, storage_id: str) -> int: ...


class _CheckpointJob(Protocol):
    id: object
    user_id: int | str
    user: object
    source_path: str | None
    column_mapping: dict[str, str] | None
    inference_summary: dict[str, object] | None
    result_summary: dict[str, object] | None
    progress_detail: dict[str, object] | None
    review_rows: ReviewRows | None

    def save(self, update_fields: list[str] | None = None) -> None: ...


def _job_user_role(job: _CheckpointJob) -> str | None:
    user = getattr(job, "user", None)
    role = getattr(user, "role", None)
    if role is None:
        return None
    role_text = str(role).strip()
    return role_text or None


def build_planned_artifact_fingerprint(
    *,
    job: _CheckpointJob,
    entity_type: str,
    duplicate_strategy: str,
    skip_rows: int,
    skip_review_rows: bool,
    corrections: dict[str, dict[str, object]] | None,
) -> str:
    payload = {
        "job_id": str(job.id),
        "source_path": str(job.source_path or ""),
        "entity_type": normalize_entity_type(entity_type),
        "duplicate_strategy": normalize_duplicate_strategy(duplicate_strategy),
        "skip_rows": int(skip_rows or 0),
        "skip_review_rows": bool(skip_review_rows),
        "column_mapping": dict(job.column_mapping or {}),
        "inference": dict(job.inference_summary or {}),
        "corrections": dict(corrections or {}),
    }
    encoded = json.dumps(
        json_safe_value(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def persist_planned_artifact_checkpoint(
    *,
    job: _CheckpointJob,
    artifact: PreparedImportArtifact,
    fingerprint: str,
    review_rows: ReviewRows,
    errors: list[dict[str, object]],
    skipped_count: int,
    error_count: int,
    store_fileobj_fn: _UploadArtifact = store_fileobj,
) -> None:
    previous_checkpoint = _checkpoint_payload(job)
    if hasattr(review_rows, "flush"):
        review_rows.flush()
    files_to_upload = _planned_artifact_files(artifact)
    review_spool_path = getattr(review_rows, "spool_path", None)
    if isinstance(review_spool_path, Path) and review_spool_path.exists() and len(review_rows) > 0:
        files_to_upload["review_rows_path"] = review_spool_path
    if not files_to_upload:
        return

    uploaded_storage_ids: list[str] = []
    uploaded_files: dict[str, dict[str, object]] = {}
    try:
        uploader_user_id = int(getattr(job, "user_id", 0) or 0) or None
        uploader_role = _job_user_role(job)
        for field_name, path in files_to_upload.items():
            filename = f"import-job-{job.id}-{field_name}.jsonl"
            with path.open("rb") as handle:
                storage_id = store_fileobj_fn(
                    fileobj=handle,
                    filename=filename,
                    content_type="application/x-ndjson",
                    purpose="import_artifact",
                    user_id=uploader_user_id,
                    role=uploader_role,
                    created_ip=None,
                )
            uploaded_storage_ids.append(storage_id)
            uploaded_files[field_name] = {"storage_id": storage_id, "filename": filename}
    except Exception:
        logger.warning("Failed to persist planned import artifact checkpoint", exc_info=True)
        for storage_id in uploaded_storage_ids:
            try:
                purge_storage_object_now(storage_id=storage_id)
            except Exception:
                logger.warning(
                    "Failed to delete partial import artifact checkpoint storage object %s",
                    storage_id,
                    exc_info=True,
                )
        return

    result_summary = dict(job.result_summary or {})
    progress_detail = dict(job.progress_detail or {})
    review_rows_snapshot = cast(
        list[ReviewRowPayload],
        json_safe_value(
            review_rows.diagnostic_sample()
            if hasattr(review_rows, "diagnostic_sample")
            else [dict(row) for row in review_rows][:25]
        ),
    )
    progress_detail["resume_available"] = True
    progress_detail["resume_fingerprint"] = fingerprint
    checkpoint = {
        "version": 1,
        "fingerprint": fingerprint,
        "bundle_mode": artifact.bundle_mode,
        "total_rows": artifact.total_rows,
        "current_batch_size": artifact.current_batch_size,
        "chunks_total": artifact.chunks_total,
        "entity_type": artifact.entity_type,
        "topology_side": artifact.topology_side,
        "root_entity": artifact.root_entity,
        "child_entity": artifact.child_entity,
        "root_row_count": artifact.root_row_count,
        "child_row_count": artifact.child_row_count,
        "planned_row_count": artifact.planned_row_count,
        "planned_root_row_count": artifact.planned_root_row_count,
        "planned_child_row_count": artifact.planned_child_row_count,
        "planning_errors": cast(
            list[dict[str, object]],
            json_safe_value([dict(error) for error in errors]),
        ),
        "planning_counts": {
            "skipped_count": int(skipped_count),
            "error_count": int(error_count),
            "review_count": len(review_rows_snapshot),
            "review_overflow_count": int(getattr(review_rows, "overflow_count", 0) or 0),
        },
        "files": uploaded_files,
    }
    result_summary[_CHECKPOINT_KEY] = cast(dict[str, object], json_safe_value(checkpoint))
    job.result_summary = cast(dict[str, object], json_safe_value(result_summary))
    job.progress_detail = cast(dict[str, object], json_safe_value(progress_detail))
    job.review_rows = review_rows_snapshot
    job.save(update_fields=["result_summary", "progress_detail", "review_rows", "updated_at"])
    _delete_checkpoint_files(previous_checkpoint)


def load_planned_artifact_checkpoint(
    *,
    job: _CheckpointJob,
    fingerprint: str,
    download_to_temp_fn: _DownloadArtifact = download_to_temp,
) -> PlannedArtifactCheckpoint | None:
    checkpoint = _checkpoint_payload(job)
    if not checkpoint:
        return None
    if str(checkpoint.get("fingerprint", "")) != fingerprint:
        return None

    files = checkpoint.get("files")
    if not isinstance(files, dict) or not files:
        return None

    spool_dir = Path(tempfile.mkdtemp(prefix="immoapp-import-resume-"))
    restored_review_rows: ReviewRowBuffer | None = None
    try:
        planned_entries_path: Path | None = None
        planned_root_entries_path: Path | None = None
        planned_child_entries_path: Path | None = None
        review_rows_path: Path | None = None
        for field_name, suffix, target_name in (
            ("planned_entries_path", ".jsonl", "planned_entries.jsonl"),
            ("planned_root_entries_path", ".jsonl", "planned_root_entries.jsonl"),
            ("planned_child_entries_path", ".jsonl", "planned_child_entries.jsonl"),
            ("review_rows_path", ".jsonl", "review_rows.jsonl"),
        ):
            file_payload = files.get(field_name)
            if not isinstance(file_payload, dict):
                continue
            storage_id = str(file_payload.get("storage_id", "") or "")
            if not storage_id:
                continue
            temp_path = download_to_temp_fn(storage_id, suffix=suffix)
            target_path = spool_dir / target_name
            temp_path.replace(target_path)
            if field_name == "planned_entries_path":
                planned_entries_path = target_path
            elif field_name == "planned_root_entries_path":
                planned_root_entries_path = target_path
            elif field_name == "review_rows_path":
                review_rows_path = target_path
            else:
                planned_child_entries_path = target_path

        artifact = PreparedImportArtifact(
            bundle_mode=str(checkpoint.get("bundle_mode", "single_entity") or "single_entity"),
            total_rows=int(checkpoint.get("total_rows", 0) or 0),
            current_batch_size=int(checkpoint.get("current_batch_size", 1) or 1),
            chunks_total=int(checkpoint.get("chunks_total", 0) or 0),
            spool_dir=spool_dir,
            planned_entries_path=planned_entries_path,
            planned_root_entries_path=planned_root_entries_path,
            planned_child_entries_path=planned_child_entries_path,
            entity_type=str(checkpoint.get("entity_type", "") or ""),
            topology_side=str(checkpoint.get("topology_side", "unknown") or "unknown"),
            root_entity=str(checkpoint.get("root_entity", "") or ""),
            child_entity=str(checkpoint.get("child_entity", "") or ""),
            root_row_count=int(checkpoint.get("root_row_count", 0) or 0),
            child_row_count=int(checkpoint.get("child_row_count", 0) or 0),
            planned_row_count=int(checkpoint.get("planned_row_count", 0) or 0),
            planned_root_row_count=int(checkpoint.get("planned_root_row_count", 0) or 0),
            planned_child_row_count=int(checkpoint.get("planned_child_row_count", 0) or 0),
        )
        review_rows = ReviewRowBuffer()
        restored_review_rows = review_rows
        if review_rows_path is None:
            review_rows_path = spool_dir / "review_rows.jsonl"
        if review_rows_path.exists():
            for row in iter_jsonl_entries(review_rows_path):
                review_rows.append(dict(row))
        else:
            for row in list(job.review_rows or []):
                if isinstance(row, dict):
                    review_rows.append(dict(row))
        counts = checkpoint.get("planning_counts")
        counts_payload = dict(counts) if isinstance(counts, dict) else {}
        review_rows.overflow_count = int(counts_payload.get("review_overflow_count", 0) or 0)
        planning_errors = checkpoint.get("planning_errors")
        errors = (
            [dict(error) for error in planning_errors if isinstance(error, dict)]
            if isinstance(planning_errors, list)
            else []
        )
        return PlannedArtifactCheckpoint(
            artifact=artifact,
            review_rows=review_rows,
            errors=errors,
            skipped_count=int(counts_payload.get("skipped_count", 0) or 0),
            error_count=int(counts_payload.get("error_count", 0) or 0),
            review_overflow_count=int(counts_payload.get("review_overflow_count", 0) or 0),
        )
    except Exception:
        if restored_review_rows is not None:
            restored_review_rows.cleanup()
        shutil.rmtree(spool_dir, ignore_errors=True)
        logger.warning("Failed to restore planned import artifact checkpoint", exc_info=True)
        return None


def clear_planned_artifact_checkpoint(
    *,
    job: _CheckpointJob,
    delete_objects: bool = True,
    mark_storage_deleted_fn: _DeleteArtifact = purge_storage_object_now,
) -> None:
    checkpoint = _checkpoint_payload(job)
    if not checkpoint:
        return
    if delete_objects:
        _delete_checkpoint_files(checkpoint, mark_storage_deleted_fn=mark_storage_deleted_fn)

    result_summary = dict(job.result_summary or {})
    progress_detail = dict(job.progress_detail or {})
    result_summary.pop(_CHECKPOINT_KEY, None)
    progress_detail.pop("resume_available", None)
    progress_detail.pop("resume_fingerprint", None)
    job.result_summary = result_summary
    job.progress_detail = progress_detail
    job.save(update_fields=["result_summary", "progress_detail", "updated_at"])


def _planned_artifact_files(artifact: PreparedImportArtifact) -> dict[str, Path]:
    files: dict[str, Path] = {}
    if artifact.planned_entries_path is not None:
        planned_entries_path = require_path(
            artifact.planned_entries_path,
            field_name="planned_entries_path",
        )
        if planned_entries_path.exists() and planned_entries_path.stat().st_size > 0:
            files["planned_entries_path"] = planned_entries_path
    if artifact.planned_root_entries_path is not None:
        planned_root_entries_path = require_path(
            artifact.planned_root_entries_path,
            field_name="planned_root_entries_path",
        )
        if planned_root_entries_path.exists() and planned_root_entries_path.stat().st_size > 0:
            files["planned_root_entries_path"] = planned_root_entries_path
    if artifact.planned_child_entries_path is not None:
        planned_child_entries_path = require_path(
            artifact.planned_child_entries_path,
            field_name="planned_child_entries_path",
        )
        if planned_child_entries_path.exists() and planned_child_entries_path.stat().st_size > 0:
            files["planned_child_entries_path"] = planned_child_entries_path
    return files


def _checkpoint_payload(job: _CheckpointJob) -> dict[str, Any]:
    result_summary = dict(job.result_summary or {})
    payload = result_summary.get(_CHECKPOINT_KEY)
    return dict(payload) if isinstance(payload, dict) else {}


def _delete_checkpoint_files(
    checkpoint: dict[str, Any],
    *,
    mark_storage_deleted_fn: _DeleteArtifact = purge_storage_object_now,
) -> None:
    files = checkpoint.get("files")
    if not isinstance(files, dict):
        return
    for file_payload in files.values():
        if not isinstance(file_payload, dict):
            continue
        storage_id = str(file_payload.get("storage_id", "") or "")
        if not storage_id:
            continue
        try:
            mark_storage_deleted_fn(storage_id=storage_id)
        except Exception:
            logger.warning(
                "Failed to mark import artifact checkpoint storage object deleted: %s",
                storage_id,
                exc_info=True,
            )


__all__ = [
    "build_planned_artifact_fingerprint",
    "clear_planned_artifact_checkpoint",
    "load_planned_artifact_checkpoint",
    "persist_planned_artifact_checkpoint",
]
