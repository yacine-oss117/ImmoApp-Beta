"""Chunk-level planning and loading for distributed importer execution."""

from __future__ import annotations

import os
import tempfile
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.contracts.import_batch_refs import CreatedRowRef
from server.imports.models import ImportArtifactManifest, ImportChunk, ImportChunkPhase, ImportJob
from server.pg.uow import get_uow
from server.services import runtime_pressure_tripwire
from server.services.import_batch_write_refs import insert_batch_refs
from server.services.import_chunk_workflow import (
    job_manifest,
    load_json_manifest,
    load_manifest_to_temp,
    manifest_for_chunk,
    persist_file_manifest,
    persist_jsonl_manifest,
    workflow_payload,
)
from server.services.import_distributed_load_phase import (
    DistributedLoadPhaseDeps,
)
from server.services.import_distributed_load_phase import (
    run_load_chunk_phase as run_distributed_load_chunk_phase,
)
from server.services.import_distributed_plan_phase import (
    DistributedPlanPhaseDeps,
)
from server.services.import_distributed_plan_phase import (
    run_plan_chunk_phase as run_distributed_plan_chunk_phase,
)
from server.services.import_execution_governor import profile_aware_chunk_ceiling
from server.services.import_executor_helpers import insert_batch
from server.services.import_identity_resolution import (
    prefetch_child_match_cache,
    prefetch_root_match_cache,
    resolve_child_anchor,
)
from server.services.import_load_policy import (
    build_root_conflict_error,
    flush_root_entries_with_conflict_isolation,
    remember_created_anchor_keys,
    timed_insert_batch_rows,
)
from server.services.import_load_policy import exception_sqlstate as _shared_exception_sqlstate
from server.services.import_load_policy import is_unique_violation as _shared_is_unique_violation
from server.services.import_phase_attempts import (
    assert_phase_attempt_current,
    is_phase_attempt_current,
    run_with_phase_attempt_fence,
)
from server.services.import_review_row_runtime import anchor_map_keys
from server.services.import_rows import validate_row
from server.services.import_runtime_artifacts import entry_int
from server.services.import_types import ImportLoadOutcome

_LEGACY_MONOTONIC = time.monotonic
_CANCEL_CHECK_TTL_SECONDS = 0.5
_CANCEL_CHECK_CACHE_LIMIT = 1024


@dataclass(frozen=True)
class _CancelCheckCacheEntry:
    checked_at: float
    cancelled: bool


_CANCEL_CHECK_CACHE: OrderedDict[str, _CancelCheckCacheEntry] = OrderedDict()


def _matching_anchor_key(row_data: dict[str, object], known_anchor_keys: set[str]) -> str:
    for key in anchor_map_keys(dict(row_data)):
        if key in known_anchor_keys:
            return key
    return ""


def _temp_jsonl_path(prefix: str) -> Path:
    temp_dir = Path(tempfile.mkdtemp(prefix=prefix))
    return temp_dir / "chunk.jsonl"


def _cleanup_temp_path(path: Path | None) -> None:
    if path is None:
        return
    try:
        parent = path.parent
        if path.exists():
            path.unlink()
        if parent.exists():
            parent.rmdir()
    except OSError:
        pass


def _require_phase_lease(*, phase: ImportChunkPhase) -> None:
    assert_phase_attempt_current(phase=phase)


def _exception_sqlstate(exc: Exception) -> str:
    return _shared_exception_sqlstate(exc)


def _is_unique_violation(exc: Exception) -> bool:
    return _shared_is_unique_violation(exc)


def _clear_cancel_check_cache(job_id: str | None = None) -> None:
    if job_id is None:
        _CANCEL_CHECK_CACHE.clear()
        return
    _CANCEL_CHECK_CACHE.pop(str(job_id).strip(), None)


def _remember_cancel_check(
    job_key: str,
    *,
    checked_at: float,
    cancelled: bool,
) -> None:
    if not job_key:
        return
    _CANCEL_CHECK_CACHE[job_key] = _CancelCheckCacheEntry(
        checked_at=checked_at,
        cancelled=cancelled,
    )
    _CANCEL_CHECK_CACHE.move_to_end(job_key)
    while len(_CANCEL_CHECK_CACHE) > _CANCEL_CHECK_CACHE_LIMIT:
        _CANCEL_CHECK_CACHE.popitem(last=False)


def _is_cancel_requested(job: ImportJob) -> bool:
    now = _LEGACY_MONOTONIC()
    job_key = str(getattr(job, "id", "") or "").strip()
    cached = _CANCEL_CHECK_CACHE.get(job_key) if job_key else None
    if cached is not None:
        age_seconds = now - float(cached.checked_at)
        if cached.cancelled or age_seconds <= _CANCEL_CHECK_TTL_SECONDS:
            _CANCEL_CHECK_CACHE.move_to_end(job_key)
            return bool(cached.cancelled)
    job.refresh_from_db(fields=["status", "result_summary"])
    payload = workflow_payload(job)
    cancelled = job.status != ImportJob.Status.RUNNING or bool(
        payload.get("cancel_requested", False)
    )
    _remember_cancel_check(job_key, checked_at=now, cancelled=cancelled)
    return cancelled


def _adaptive_inner_batch_size(row_count: int) -> int:
    return max(
        25, min(max(1, int(row_count)), profile_aware_chunk_ceiling(max(25, int(row_count))))
    )


def _blocked_duplicate_resolution_message(resolution: object) -> str:
    suggested_reasons = [
        str(reason).strip()
        for reason in list(getattr(resolution, "suggested_reasons", []) or [])
        if str(reason).strip()
    ]
    low_signal_reasons = {
        "same phone",
        "same name",
        "very similar name",
        "similar name",
        "active record",
    }
    primary_reason = suggested_reasons[0] if suggested_reasons else ""
    if primary_reason and primary_reason.casefold() not in low_signal_reasons:
        return primary_reason
    return "This line matches existing records in your agency and needs review."


def _pressure_tripwire_yellow_seconds() -> float:
    raw = (os.environ.get("IMMOAPP_IMPORT_TRIPWIRE_YELLOW_SECONDS") or "").strip()
    try:
        value = float(raw)
    except ValueError:
        value = 1.5
    return max(0.25, min(value, 30.0))


def _pressure_tripwire_red_seconds() -> float:
    raw = (os.environ.get("IMMOAPP_IMPORT_TRIPWIRE_RED_SECONDS") or "").strip()
    try:
        value = float(raw)
    except ValueError:
        value = 4.0
    return max(_pressure_tripwire_yellow_seconds(), min(value, 60.0))


def _publish_tripwire_from_exception(exc: Exception) -> None:
    sqlstate = str(getattr(exc, "sqlstate", "") or "").strip()
    text = str(exc).lower()
    if sqlstate == "57014" or "statement timeout" in text:
        runtime_pressure_tripwire.publish_override(
            profile="red",
            reason="red_statement_timeout",
        )
    elif sqlstate in {"55P03", "40P01"} or "lock timeout" in text or "deadlock" in text:
        runtime_pressure_tripwire.publish_override(
            profile="red",
            reason="red_lock_timeout",
        )


def _publish_tripwire_from_db_time(duration_seconds: float) -> None:
    if duration_seconds >= _pressure_tripwire_red_seconds():
        runtime_pressure_tripwire.publish_override(
            profile="red",
            reason="red_sub_batch_db_time",
        )
    elif duration_seconds >= _pressure_tripwire_yellow_seconds():
        runtime_pressure_tripwire.publish_override(
            profile="yellow",
            reason="yellow_sub_batch_db_time",
        )


def _planned_root_plan_index(job: ImportJob) -> dict[str, Any]:
    manifest = job_manifest(
        job=job,
        phase=ImportArtifactManifest.Phase.PLAN,
        artifact_kind="root_plan_index",
    )
    if manifest is None:
        return {"existing_anchor_map": {}, "planned_root_anchor_keys": []}
    payload = load_json_manifest(manifest)
    return {
        "existing_anchor_map": dict(payload.get("existing_anchor_map", {}) or {}),
        "planned_root_anchor_keys": list(payload.get("planned_root_anchor_keys", []) or []),
    }


def _root_load_anchor_map(job: ImportJob) -> dict[str, int]:
    manifest = job_manifest(
        job=job,
        phase=ImportArtifactManifest.Phase.LOAD,
        artifact_kind="root_load_anchor_map",
    )
    if manifest is None:
        return {}
    payload = load_json_manifest(manifest)
    return {
        str(key): int(value) for key, value in dict(payload or {}).items() if str(key or "").strip()
    }


def _load_child_root_precheck(*, job: ImportJob, chunk: ImportChunk) -> dict[str, int]:
    root_load_anchor_map = _root_load_anchor_map(job)
    uow = get_uow()
    session_factory = getattr(uow, "session", None)
    if callable(session_factory):
        read_context = session_factory(actor=f"import-load-child-precheck:{job.id}:{chunk.id}")
    else:
        read_context = uow.transaction(actor=f"import-load-child-precheck:{job.id}:{chunk.id}")
    with read_context as read_session:
        root_chunk_rows = read_session.execute(
            f"""
            SELECT id
            FROM {ImportChunk._meta.db_table}
            WHERE job_id = %s AND chunk_role = %s
            ORDER BY id
            """,
            (job.id, ImportChunk.Role.ROOT),
        ).fetchall()
        root_chunk_ids = [entry_int(dict(row), "id") for row in root_chunk_rows]
        if root_chunk_ids:
            root_load_statuses = {
                entry_int(dict(row), "chunk_id"): str(dict(row).get("status", "") or "")
                for row in read_session.execute(
                    f"""
                    SELECT chunk_id, status
                    FROM {ImportChunkPhase._meta.db_table}
                    WHERE chunk_id = ANY(%s) AND phase = %s
                    """,
                    (root_chunk_ids, ImportChunkPhase.Phase.LOAD),
                ).fetchall()
            }
            if len(root_load_statuses) != len(root_chunk_ids) or any(
                root_load_statuses.get(int(chunk_id)) != ImportChunkPhase.Status.COMPLETED
                for chunk_id in root_chunk_ids
            ):
                raise ValueError(
                    f"Cannot load child chunk {chunk.id}: root chunk load has not completed yet."
                )
    return root_load_anchor_map


def _persist_load_errors(
    *,
    job: ImportJob,
    chunk: ImportChunk,
    rows: list[dict[str, Any]],
    phase: ImportChunkPhase | None = None,
) -> None:
    if not rows:
        return
    if phase is not None and not is_phase_attempt_current(
        phase_id=phase.id,
        attempt_id=str(phase.lease_token or ""),
    ):
        return
    persist_jsonl_manifest(
        job=job,
        phase=ImportArtifactManifest.Phase.LOAD,
        artifact_kind="load_errors",
        rows=rows,
        chunk=chunk,
    )


def _flush_root_batch_with_conflict_isolation(
    *,
    write_session: Any,
    entity_type: str,
    batch_entries: list[dict[str, Any]],
    load_outcome: ImportLoadOutcome,
    created_anchor_map: dict[str, int],
    load_errors: list[dict[str, Any]],
) -> tuple[int, int, float]:
    def _on_rows_inserted(
        created_rows: list[CreatedRowRef],
        inserted_entries: list[dict[str, Any]],
    ) -> None:
        if created_rows:
            load_outcome.committed_entities.add(entity_type)
        remember_created_anchor_keys(
            created_anchor_map=created_anchor_map,
            batch_entries=inserted_entries,
            created_rows=created_rows,
        )

    def _append_leaf_error(entry: dict[str, Any]) -> None:
        load_errors.append(
            build_root_conflict_error(entry=entry, message="Unique conflict during root load")
        )

    result = flush_root_entries_with_conflict_isolation(
        write_session=write_session,
        entity_type=entity_type,
        batch_entries=batch_entries,
        load_outcome=load_outcome,
        on_rows_inserted=_on_rows_inserted,
        append_leaf_error=_append_leaf_error,
        insert_batch_fn=insert_batch_refs,
    )
    return len(result.created_ids), result.skipped_count, result.db_duration


def _plan_phase_deps() -> DistributedPlanPhaseDeps:
    return DistributedPlanPhaseDeps(
        matching_anchor_key_fn=_matching_anchor_key,
        temp_jsonl_path_fn=_temp_jsonl_path,
        cleanup_temp_path_fn=_cleanup_temp_path,
        require_phase_lease_fn=_require_phase_lease,
        is_cancel_requested_fn=_is_cancel_requested,
        phase_lease_active_fn=is_phase_attempt_current,
        run_with_phase_attempt_fence_fn=run_with_phase_attempt_fence,
        planned_root_plan_index_fn=_planned_root_plan_index,
        blocked_duplicate_resolution_message_fn=_blocked_duplicate_resolution_message,
        manifest_for_chunk_fn=manifest_for_chunk,
        load_manifest_to_temp_fn=load_manifest_to_temp,
        get_uow_fn=get_uow,
        workflow_payload_fn=workflow_payload,
        prefetch_root_match_cache_fn=prefetch_root_match_cache,
        prefetch_child_match_cache_fn=prefetch_child_match_cache,
        resolve_child_anchor_fn=resolve_child_anchor,
        validate_row_fn=validate_row,
        persist_file_manifest_fn=persist_file_manifest,
        persist_jsonl_manifest_fn=persist_jsonl_manifest,
    )


def _load_phase_deps() -> DistributedLoadPhaseDeps:
    return DistributedLoadPhaseDeps(
        cleanup_temp_path_fn=_cleanup_temp_path,
        require_phase_lease_fn=_require_phase_lease,
        phase_lease_active_fn=is_phase_attempt_current,
        run_with_phase_attempt_fence_fn=run_with_phase_attempt_fence,
        is_cancel_requested_fn=_is_cancel_requested,
        adaptive_inner_batch_size_fn=_adaptive_inner_batch_size,
        publish_tripwire_from_db_time_fn=_publish_tripwire_from_db_time,
        publish_tripwire_from_exception_fn=_publish_tripwire_from_exception,
        load_child_root_precheck_fn=_load_child_root_precheck,
        persist_load_errors_fn=_persist_load_errors,
        flush_root_batch_with_conflict_isolation_fn=_flush_root_batch_with_conflict_isolation,
        manifest_for_chunk_fn=manifest_for_chunk,
        load_manifest_to_temp_fn=load_manifest_to_temp,
        get_uow_fn=get_uow,
        timed_insert_batch_rows_fn=timed_insert_batch_rows,
        insert_batch_fn=insert_batch,
    )


def plan_chunk_phase(
    *,
    phase: ImportChunkPhase,
    user_id: int,
) -> dict[str, Any]:
    return run_distributed_plan_chunk_phase(
        phase=phase,
        user_id=user_id,
        deps=_plan_phase_deps(),
    )


def load_chunk_phase(
    *,
    phase: ImportChunkPhase,
    user_id: int,
) -> dict[str, Any]:
    return run_distributed_load_chunk_phase(
        phase=phase,
        user_id=user_id,
        deps=_load_phase_deps(),
    )


__all__ = [
    "load_chunk_phase",
    "plan_chunk_phase",
]
