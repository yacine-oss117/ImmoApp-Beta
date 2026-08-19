"""Artifact manifest helpers for distributed importer execution."""

from __future__ import annotations

import hashlib
import json
import logging
from io import BytesIO
from pathlib import Path
from typing import Any, BinaryIO, Callable, Protocol, cast

from django.db import transaction

from server.imports.models import ImportArtifactManifest, ImportChunk, ImportChunkPhase, ImportJob
from server.pg.uow import use_security_context
from server.services.import_review_runtime import review_overflow_count
from server.services.import_runtime_artifacts import (
    entry_row_num,
    iter_jsonl_entries,
    iter_jsonl_entry_batches,
    write_jsonl_entry,
)
from server.services.import_types import (
    ImportResult,
    PreparedImportArtifact,
    ReviewRowBuffer,
    ReviewRows,
)
from server.services.import_workflow_dispatch import aggregate_review_overflow_count
from server.services.import_workflow_storage import (
    _save_workflow_payload,
    clear_distributed_workflow,
    workflow_payload,
)
from server.services.json_safe import json_safe_value
from server.services.storage import download_to_temp, purge_storage_object_now, store_fileobj

logger = logging.getLogger(__name__)

_ARTIFACT_PREPARED = "prepared"
_ARTIFACT_REVIEW_ROWS = "review_rows"
_ARTIFACT_ERRORS = "errors"
_ARTIFACT_ROOT_PLAN_INDEX = "root_plan_index"
_ARTIFACT_ROOT_LOAD_ANCHOR_MAP = "root_load_anchor_map"
_ARTIFACT_LOAD_ERRORS = "load_errors"


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


def _job_user_role(job: ImportJob) -> str | None:
    role = getattr(getattr(job, "user", None), "role", None)
    if role is None:
        return None
    text = str(role).strip()
    return text or None


def _manifest_filename(
    *,
    job: ImportJob,
    chunk: ImportChunk | None,
    phase: str,
    artifact_kind: str,
    suffix: str,
) -> str:
    chunk_suffix = f"-chunk-{chunk.id}" if chunk is not None else ""
    return f"import-job-{job.id}{chunk_suffix}-{phase}-{artifact_kind}{suffix}"


def _replace_manifest(
    *,
    job: ImportJob,
    phase: str,
    artifact_kind: str,
    chunk: ImportChunk | None,
    storage_id: str,
    checksum: str,
    row_count: int,
    metadata: dict[str, Any] | None,
    delete_artifact_fn: _DeleteArtifact = purge_storage_object_now,
) -> ImportArtifactManifest:
    existing = list(
        ImportArtifactManifest.objects.filter(
            job=job,
            chunk=chunk,
            phase=phase,
            artifact_kind=artifact_kind,
        )
    )
    for manifest in existing:
        existing_storage_id = str(manifest.storage_id or "").strip()
        if existing_storage_id:
            try:
                delete_artifact_fn(storage_id=existing_storage_id)
            except Exception:
                logger.warning(
                    "Failed to purge previous import artifact manifest %s",
                    existing_storage_id,
                    exc_info=True,
                )
    if existing:
        ImportArtifactManifest.objects.filter(
            job=job,
            chunk=chunk,
            phase=phase,
            artifact_kind=artifact_kind,
        ).delete()
    return cast(
        ImportArtifactManifest,
        ImportArtifactManifest.objects.create(
            job=job,
            agency_id=int(getattr(job, "agency_id", 0) or 0),
            chunk=chunk,
            phase=phase,
            artifact_kind=artifact_kind,
            storage_id=storage_id,
            checksum=checksum,
            row_count=max(0, int(row_count)),
            metadata=cast(dict[str, Any], json_safe_value(dict(metadata or {}))),
        ),
    )


def _persist_bytes_manifest(
    *,
    job: ImportJob,
    phase: str,
    artifact_kind: str,
    payload_bytes: bytes,
    chunk: ImportChunk | None = None,
    row_count: int = 0,
    metadata: dict[str, Any] | None = None,
    filename_suffix: str = ".jsonl",
    content_type: str = "application/x-ndjson",
    store_fileobj_fn: _UploadArtifact = store_fileobj,
    delete_artifact_fn: _DeleteArtifact = purge_storage_object_now,
) -> ImportArtifactManifest | None:
    if not payload_bytes:
        return None
    checksum = hashlib.sha256(payload_bytes).hexdigest()
    with use_security_context(
        agency_id=int(getattr(job, "agency_id", 0) or 0) or None,
        is_superuser=False,
    ):
        storage_id = store_fileobj_fn(
            fileobj=BytesIO(payload_bytes),
            filename=_manifest_filename(
                job=job,
                chunk=chunk,
                phase=phase,
                artifact_kind=artifact_kind,
                suffix=filename_suffix,
            ),
            content_type=content_type,
            purpose="import_artifact",
            user_id=int(getattr(job, "user_id", 0) or 0) or None,
            role=_job_user_role(job),
            created_ip=None,
        )
    return _replace_manifest(
        job=job,
        phase=phase,
        artifact_kind=artifact_kind,
        chunk=chunk,
        storage_id=storage_id,
        checksum=checksum,
        row_count=row_count,
        metadata=metadata,
        delete_artifact_fn=delete_artifact_fn,
    )


def persist_json_manifest(
    *,
    job: ImportJob,
    phase: str,
    artifact_kind: str,
    payload: dict[str, Any],
    chunk: ImportChunk | None = None,
    metadata: dict[str, Any] | None = None,
    store_fileobj_fn: _UploadArtifact = store_fileobj,
    delete_artifact_fn: _DeleteArtifact = purge_storage_object_now,
) -> ImportArtifactManifest | None:
    payload_bytes = json.dumps(
        cast(dict[str, object], json_safe_value(dict(payload))),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return _persist_bytes_manifest(
        job=job,
        phase=phase,
        artifact_kind=artifact_kind,
        payload_bytes=payload_bytes,
        chunk=chunk,
        row_count=int(metadata.get("row_count", 0) if isinstance(metadata, dict) else 0),
        metadata=metadata,
        filename_suffix=".json",
        content_type="application/json",
        store_fileobj_fn=store_fileobj_fn,
        delete_artifact_fn=delete_artifact_fn,
    )


def persist_jsonl_manifest(
    *,
    job: ImportJob,
    phase: str,
    artifact_kind: str,
    rows: list[dict[str, Any]],
    chunk: ImportChunk | None = None,
    metadata: dict[str, Any] | None = None,
    store_fileobj_fn: _UploadArtifact = store_fileobj,
    delete_artifact_fn: _DeleteArtifact = purge_storage_object_now,
) -> ImportArtifactManifest | None:
    if not rows:
        return None
    payload = "".join(
        json.dumps(
            cast(dict[str, object], json_safe_value(dict(row))),
            ensure_ascii=True,
            separators=(",", ":"),
        )
        + "\n"
        for row in rows
    ).encode("utf-8")
    return _persist_bytes_manifest(
        job=job,
        phase=phase,
        artifact_kind=artifact_kind,
        payload_bytes=payload,
        chunk=chunk,
        row_count=len(rows),
        metadata=metadata,
        store_fileobj_fn=store_fileobj_fn,
        delete_artifact_fn=delete_artifact_fn,
    )


def persist_file_manifest(
    *,
    job: ImportJob,
    phase: str,
    artifact_kind: str,
    path: Path,
    chunk: ImportChunk | None = None,
    row_count: int = 0,
    metadata: dict[str, Any] | None = None,
    store_fileobj_fn: _UploadArtifact = store_fileobj,
    delete_artifact_fn: _DeleteArtifact = purge_storage_object_now,
) -> ImportArtifactManifest | None:
    if not path.exists() or path.stat().st_size <= 0:
        return None
    with path.open("rb") as handle:
        payload = handle.read()
    return _persist_bytes_manifest(
        job=job,
        phase=phase,
        artifact_kind=artifact_kind,
        payload_bytes=payload,
        chunk=chunk,
        row_count=row_count,
        metadata=metadata,
        store_fileobj_fn=store_fileobj_fn,
        delete_artifact_fn=delete_artifact_fn,
    )


def load_manifest_to_temp(
    manifest: ImportArtifactManifest,
    *,
    suffix: str | None = ".jsonl",
    download_to_temp_fn: _DownloadArtifact = download_to_temp,
) -> Path:
    return download_to_temp_fn(str(manifest.storage_id), suffix=suffix)


def load_jsonl_manifest_rows(
    manifest: ImportArtifactManifest,
    *,
    download_to_temp_fn: _DownloadArtifact = download_to_temp,
) -> list[dict[str, Any]]:
    temp_path = load_manifest_to_temp(manifest, download_to_temp_fn=download_to_temp_fn)
    try:
        return [dict(entry) for entry in iter_jsonl_entries(temp_path)]
    finally:
        try:
            temp_path.unlink()
        except OSError:
            pass


def load_json_manifest(
    manifest: ImportArtifactManifest,
    *,
    download_to_temp_fn: _DownloadArtifact = download_to_temp,
) -> dict[str, Any]:
    temp_path = load_manifest_to_temp(
        manifest, suffix=".json", download_to_temp_fn=download_to_temp_fn
    )
    try:
        with temp_path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return dict(payload) if isinstance(payload, dict) else {}
    finally:
        try:
            temp_path.unlink()
        except OSError:
            pass


def _chunk_source_to_paths(
    *,
    source_path: Path,
    batch_size: int,
    target_dir: Path,
    stem: str,
) -> list[dict[str, Any]]:
    target_dir.mkdir(parents=True, exist_ok=True)
    chunk_payloads: list[dict[str, Any]] = []
    for ordinal, batch in enumerate(iter_jsonl_entry_batches(source_path, batch_size), start=1):
        if not batch:
            continue
        chunk_path = target_dir / f"{stem}-{ordinal}.jsonl"
        with chunk_path.open("w", encoding="utf-8") as handle:
            for entry in batch:
                write_jsonl_entry(handle, dict(entry))
        chunk_payloads.append(
            {
                "ordinal": ordinal,
                "path": chunk_path,
                "row_start": entry_row_num(batch[0]),
                "row_end": entry_row_num(batch[-1]),
                "row_count": len(batch),
            }
        )
    return chunk_payloads


def stage_prepared_artifact(
    *,
    job: ImportJob,
    artifact: PreparedImportArtifact,
    review_rows: ReviewRows,
    errors: list[dict[str, Any]],
    result: ImportResult,
    persist_file_manifest_fn: Callable[..., ImportArtifactManifest | None] = persist_file_manifest,
    persist_jsonl_manifest_fn: Callable[
        ..., ImportArtifactManifest | None
    ] = persist_jsonl_manifest,
    clear_distributed_workflow_fn: Callable[..., None] = clear_distributed_workflow,
    workflow_payload_fn: Callable[[ImportJob], dict[str, Any]] = workflow_payload,
    save_workflow_payload_fn: Callable[[ImportJob, dict[str, Any]], None] = _save_workflow_payload,
) -> None:
    spool_dir = artifact.spool_dir
    if spool_dir is None:
        raise ValueError("Prepared import artifact is missing spool_dir.")

    chunk_dir = spool_dir / "distributed-chunks"
    chunk_specs: list[tuple[str, str, list[dict[str, Any]], str]] = []
    if artifact.bundle_mode == "same_side_bundle":
        if artifact.root_entries_path is not None:
            chunk_specs.append(
                (
                    ImportChunk.Role.ROOT,
                    artifact.root_entity,
                    _chunk_source_to_paths(
                        source_path=artifact.root_entries_path,
                        batch_size=artifact.current_batch_size,
                        target_dir=chunk_dir / "root",
                        stem="prepared-root",
                    ),
                    ImportChunkPhase.Status.PENDING,
                )
            )
        if artifact.child_entries_path is not None:
            chunk_specs.append(
                (
                    ImportChunk.Role.CHILD,
                    artifact.child_entity,
                    _chunk_source_to_paths(
                        source_path=artifact.child_entries_path,
                        batch_size=artifact.current_batch_size,
                        target_dir=chunk_dir / "child",
                        stem="prepared-child",
                    ),
                    ImportChunkPhase.Status.BLOCKED,
                )
            )
    else:
        prepared_entries_path = artifact.prepared_entries_path
        if prepared_entries_path is not None:
            chunk_specs.append(
                (
                    ImportChunk.Role.SINGLE,
                    artifact.entity_type,
                    _chunk_source_to_paths(
                        source_path=prepared_entries_path,
                        batch_size=artifact.current_batch_size,
                        target_dir=chunk_dir / "single",
                        stem="prepared-single",
                    ),
                    ImportChunkPhase.Status.PENDING,
                )
            )

    created_chunks: list[ImportChunk] = []
    try:
        with transaction.atomic():
            for chunk_role, entity_type, chunk_payloads, initial_plan_status in chunk_specs:
                for payload in chunk_payloads:
                    chunk = ImportChunk.objects.create(
                        job=job,
                        agency_id=int(getattr(job, "agency_id", 0) or 0),
                        ordinal=int(payload["ordinal"]),
                        chunk_role=chunk_role,
                        entity_type=str(entity_type or ""),
                        row_start=int(payload["row_start"]),
                        row_end=int(payload["row_end"]),
                        row_count=int(payload["row_count"]),
                    )
                    ImportChunkPhase.objects.create(
                        chunk=chunk,
                        phase=ImportChunkPhase.Phase.PLAN,
                        status=initial_plan_status,
                    )
                    ImportChunkPhase.objects.create(
                        chunk=chunk,
                        phase=ImportChunkPhase.Phase.LOAD,
                        status=ImportChunkPhase.Status.BLOCKED,
                    )
                    created_chunks.append(chunk)
    except Exception:
        ImportChunk.objects.filter(job=job).delete()
        raise

    try:
        chunk_by_key = {(chunk.chunk_role, chunk.ordinal): chunk for chunk in created_chunks}
        for chunk_role, _entity_type, chunk_payloads, _initial_plan_status in chunk_specs:
            for payload in chunk_payloads:
                chunk = chunk_by_key[(chunk_role, int(payload["ordinal"]))]
                persist_file_manifest_fn(
                    job=job,
                    phase=ImportArtifactManifest.Phase.PREPARE,
                    artifact_kind=_ARTIFACT_PREPARED,
                    path=cast(Path, payload["path"]),
                    chunk=chunk,
                    row_count=int(payload["row_count"]),
                    metadata={
                        "chunk_role": chunk_role,
                        "row_start": int(payload["row_start"]),
                        "row_end": int(payload["row_end"]),
                    },
                )

        if review_rows:
            review_spool_path = getattr(review_rows, "spool_path", None)
            if isinstance(review_spool_path, Path) and review_spool_path.exists():
                flush_review_rows = getattr(review_rows, "flush", None)
                if callable(flush_review_rows):
                    flush_review_rows()
                review_manifest = persist_file_manifest_fn(
                    job=job,
                    phase=ImportArtifactManifest.Phase.PREPARE,
                    artifact_kind=_ARTIFACT_REVIEW_ROWS,
                    path=review_spool_path,
                    row_count=len(review_rows),
                    metadata={"scope": "prepare"},
                )
                if review_manifest is not None and hasattr(
                    review_rows, "remember_artifact_manifest_id"
                ):
                    review_rows.remember_artifact_manifest_id(int(review_manifest.id))
            else:
                persist_jsonl_manifest_fn(
                    job=job,
                    phase=ImportArtifactManifest.Phase.PREPARE,
                    artifact_kind=_ARTIFACT_REVIEW_ROWS,
                    rows=[dict(row) for row in review_rows],
                    metadata={"scope": "prepare"},
                )
        if errors:
            persist_jsonl_manifest_fn(
                job=job,
                phase=ImportArtifactManifest.Phase.PREPARE,
                artifact_kind=_ARTIFACT_ERRORS,
                rows=[dict(row) for row in errors],
                metadata={"scope": "prepare"},
            )
    except Exception:
        clear_distributed_workflow_fn(
            job=job,
            delete_objects=True,
        )
        raise

    payload = workflow_payload_fn(job)
    payload["prepare_completed"] = True
    payload["prepare_chunk_counts"] = {
        "root_chunks": sum(
            1
            for role, _entity_type, chunk_payloads, _initial_plan_status in chunk_specs
            if role == ImportChunk.Role.ROOT
            for _payload in chunk_payloads
        ),
        "child_chunks": sum(
            1
            for role, _entity_type, chunk_payloads, _initial_plan_status in chunk_specs
            if role == ImportChunk.Role.CHILD
            for _payload in chunk_payloads
        ),
        "single_chunks": sum(
            1
            for role, _entity_type, chunk_payloads, _initial_plan_status in chunk_specs
            if role == ImportChunk.Role.SINGLE
            for _payload in chunk_payloads
        ),
    }
    payload["prepare_counts"] = {
        "review_count": len(review_rows),
        "error_count": len(errors),
        "skipped_count": int(result.skipped_count),
        "dead_letter_summary": {
            str(key): int(value)
            for key, value in dict(result.dead_letter_summary or {}).items()
            if isinstance(value, (int, float))
        },
        "review_overflow_count": review_overflow_count(review_rows),
        "root_row_count": int(getattr(artifact, "root_row_count", 0) or 0),
        "child_row_count": int(getattr(artifact, "child_row_count", 0) or 0),
        "planned_row_count": int(getattr(artifact, "planned_row_count", 0) or 0),
    }
    save_workflow_payload_fn(job, payload)


def manifest_for_chunk(
    *,
    chunk: ImportChunk,
    phase: str,
    artifact_kind: str,
) -> ImportArtifactManifest | None:
    return cast(
        ImportArtifactManifest | None,
        ImportArtifactManifest.objects.filter(
            job=chunk.job,
            chunk=chunk,
            phase=phase,
            artifact_kind=artifact_kind,
        )
        .order_by("-id")
        .first(),
    )


def job_manifest(
    *,
    job: ImportJob,
    phase: str,
    artifact_kind: str,
) -> ImportArtifactManifest | None:
    return cast(
        ImportArtifactManifest | None,
        ImportArtifactManifest.objects.filter(
            job=job,
            chunk__isnull=True,
            phase=phase,
            artifact_kind=artifact_kind,
        )
        .order_by("-id")
        .first(),
    )


def _persist_root_index_manifest(
    *,
    job: ImportJob,
    artifact_kind: str,
    payload: dict[str, Any],
    phase: str,
    persist_json_manifest_fn: Callable[..., ImportArtifactManifest | None] = persist_json_manifest,
) -> dict[str, Any]:
    manifest = persist_json_manifest_fn(
        job=job,
        phase=phase,
        artifact_kind=artifact_kind,
        payload=payload,
        metadata={
            "row_count": int(
                len(payload.get("planned_root_anchor_keys", []))
                if artifact_kind == _ARTIFACT_ROOT_PLAN_INDEX
                else len(payload)
            )
        },
    )
    return {
        "manifest_id": int(getattr(manifest, "id", 0) or 0) if manifest is not None else 0,
        "checksum": str(getattr(manifest, "checksum", "") or "") if manifest is not None else "",
        "key_count": int(
            len(payload.get("planned_root_anchor_keys", []))
            if artifact_kind == _ARTIFACT_ROOT_PLAN_INDEX
            else len(payload)
        ),
    }


def collected_review_rows(job: ImportJob) -> tuple[ReviewRows, list[dict[str, Any]]]:
    return _collected_review_rows_impl(job)


def _collected_review_rows_impl(
    job: ImportJob,
    *,
    load_jsonl_manifest_rows_fn: Callable[
        [ImportArtifactManifest], list[dict[str, Any]]
    ] = load_jsonl_manifest_rows,
    workflow_payload_fn: Callable[[ImportJob], dict[str, Any]] = workflow_payload,
    aggregate_review_overflow_count_fn: Callable[..., int] = aggregate_review_overflow_count,
) -> tuple[ReviewRows, list[dict[str, Any]]]:
    review_rows: ReviewRowBuffer = ReviewRowBuffer()
    errors: list[dict[str, Any]] = []
    try:
        manifests = list(
            ImportArtifactManifest.objects.filter(
                job=job,
                artifact_kind__in=[_ARTIFACT_REVIEW_ROWS, _ARTIFACT_ERRORS, _ARTIFACT_LOAD_ERRORS],
            ).order_by("chunk__chunk_role", "chunk__ordinal", "id")
        )
        for manifest in manifests:
            rows = load_jsonl_manifest_rows_fn(manifest)
            if manifest.artifact_kind == _ARTIFACT_REVIEW_ROWS:
                review_rows.extend(dict(row) for row in rows)
            else:
                errors.extend(dict(row) for row in rows)
        workflow = workflow_payload_fn(job)
        phase_list = list(
            ImportChunkPhase.objects.filter(chunk__job=job).order_by(
                "chunk__chunk_role", "chunk__ordinal", "id"
            )
        )
        review_rows.overflow_count = aggregate_review_overflow_count_fn(
            workflow=workflow,
            phases=phase_list,
        )
        return review_rows, errors
    except Exception:
        review_rows.cleanup()
        raise


__all__ = [
    "collected_review_rows",
    "job_manifest",
    "load_json_manifest",
    "load_jsonl_manifest_rows",
    "load_manifest_to_temp",
    "manifest_for_chunk",
    "persist_file_manifest",
    "persist_json_manifest",
    "persist_jsonl_manifest",
    "stage_prepared_artifact",
]
