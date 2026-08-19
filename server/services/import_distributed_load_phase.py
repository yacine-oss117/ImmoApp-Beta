"""Load owner for distributed importer chunk execution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, cast

from server.imports.models import ImportArtifactManifest, ImportChunk, ImportChunkPhase, ImportJob
from server.services import e2e_control
from server.services.import_constants import ENTITY_TYPE_DEMANDE
from server.services.import_load_accounting import (
    root_conflict_failure_delta,
)
from server.services.import_load_policy import (
    build_child_anchor_failure_rows,
    classify_child_anchor,
    evaluate_orphan_threshold,
)
from server.services.import_load_service import ImportLoadConsistencyError
from server.services.import_phase_attempts import raise_phase_attempt_cancelled
from server.services.import_runtime_artifacts import (
    entry_dict,
    entry_int,
    entry_row_num,
    entry_str,
    iter_jsonl_entries,
)
from server.services.import_types import ImportLoadOutcome


@dataclass(frozen=True)
class DistributedLoadPhaseDeps:
    cleanup_temp_path_fn: Callable[[Any], None]
    require_phase_lease_fn: Callable[..., None]
    phase_lease_active_fn: Callable[..., bool]
    run_with_phase_attempt_fence_fn: Callable[..., Any]
    is_cancel_requested_fn: Callable[[ImportJob], bool]
    adaptive_inner_batch_size_fn: Callable[[int], int]
    publish_tripwire_from_db_time_fn: Callable[[float], None]
    publish_tripwire_from_exception_fn: Callable[[Exception], None]
    load_child_root_precheck_fn: Callable[..., dict[str, int]]
    persist_load_errors_fn: Callable[..., None]
    flush_root_batch_with_conflict_isolation_fn: Callable[..., tuple[int, int, float]]
    manifest_for_chunk_fn: Callable[..., Any]
    load_manifest_to_temp_fn: Callable[[Any], Any]
    get_uow_fn: Callable[[], Any]
    timed_insert_batch_rows_fn: Callable[..., Any]
    insert_batch_fn: Callable[..., Any]


def run_load_chunk_phase(
    *,
    phase: ImportChunkPhase,
    user_id: int,
    deps: DistributedLoadPhaseDeps,
) -> dict[str, Any]:
    chunk = phase.chunk
    job = cast(ImportJob, chunk.job)
    planned_manifest = deps.manifest_for_chunk_fn(
        chunk=chunk,
        phase=ImportArtifactManifest.Phase.PLAN,
        artifact_kind="planned",
    )
    if planned_manifest is None:
        return {
            "processed_count": 0,
            "created_count": 0,
            "skipped_count": 0,
            "error_count": 0,
            "total_db_time": 0.0,
        }
    planned_path = deps.load_manifest_to_temp_fn(planned_manifest)
    load_outcome = ImportLoadOutcome()
    created_anchor_map: dict[str, int] = {}
    created_count = 0
    skipped_count = 0
    error_count = 0
    load_errors: list[dict[str, Any]] = []
    entries = [dict(entry) for entry in iter_jsonl_entries(planned_path)]
    child_root_load_anchor_map: dict[str, int] = {}

    try:
        if e2e_control.e2e_test_mode_enabled():
            e2e_control.maybe_pause_import_job(job_id=str(job.id))
        if deps.is_cancel_requested_fn(job):
            raise_phase_attempt_cancelled(phase=phase, reason="loading chunk")
        if chunk.chunk_role == ImportChunk.Role.CHILD:
            child_root_load_anchor_map = deps.load_child_root_precheck_fn(job=job, chunk=chunk)
        with deps.get_uow_fn().transaction(
            actor=f"import-load-chunk:{user_id}:{chunk.id}"
        ) as write_session:
            inner_batch_size = deps.adaptive_inner_batch_size_fn(len(entries))
            if chunk.chunk_role == ImportChunk.Role.SINGLE:
                for start_index in range(0, len(entries), inner_batch_size):
                    deps.require_phase_lease_fn(phase=phase)
                    if deps.is_cancel_requested_fn(job):
                        raise_phase_attempt_cancelled(
                            phase=phase, reason="single chunk batch insert"
                        )
                    entry_batch = entries[start_index : start_index + inner_batch_size]
                    insert_result = deps.run_with_phase_attempt_fence_fn(
                        phase=phase,
                        operation="single_chunk_batch_insert",
                        fn=lambda entry_batch=entry_batch: deps.timed_insert_batch_rows_fn(
                            write_session=write_session,
                            entity_type=str(chunk.entity_type or ""),
                            batch_rows=[entry_dict(entry, "data") for entry in entry_batch],
                            load_outcome=load_outcome,
                            insert_batch_fn=deps.insert_batch_fn,
                        ),
                    )
                    batch_ids = insert_result.created_ids
                    batch_db_time = insert_result.db_duration
                    load_outcome.total_db_time += batch_db_time
                    deps.publish_tripwire_from_db_time_fn(batch_db_time)
                    created_count += len(batch_ids)
                    if batch_ids:
                        load_outcome.committed_entities.add(str(chunk.entity_type or ""))

            elif chunk.chunk_role == ImportChunk.Role.ROOT:
                for start_index in range(0, len(entries), inner_batch_size):
                    deps.require_phase_lease_fn(phase=phase)
                    if deps.is_cancel_requested_fn(job):
                        raise_phase_attempt_cancelled(phase=phase, reason="root chunk batch insert")
                    entry_batch = entries[start_index : start_index + inner_batch_size]
                    batch_created, batch_skipped, batch_db_time = (
                        deps.run_with_phase_attempt_fence_fn(
                            phase=phase,
                            operation="root_chunk_batch_insert",
                            fn=lambda entry_batch=entry_batch: (
                                deps.flush_root_batch_with_conflict_isolation_fn(
                                    write_session=write_session,
                                    entity_type=str(chunk.entity_type or ""),
                                    batch_entries=entry_batch,
                                    load_outcome=load_outcome,
                                    created_anchor_map=created_anchor_map,
                                    load_errors=load_errors,
                                )
                            ),
                        )
                    )
                    created_count += batch_created
                    batch_delta = root_conflict_failure_delta(failure_count=batch_skipped)
                    skipped_count += batch_delta.skipped_count
                    error_count += batch_delta.error_count
                    load_outcome.total_db_time += batch_db_time
                    deps.publish_tripwire_from_db_time_fn(batch_db_time)

            else:
                child_parent_field = (
                    "client_id"
                    if str(chunk.entity_type or "") == ENTITY_TYPE_DEMANDE
                    else "listing_id"
                )
                for start_index in range(0, len(entries), inner_batch_size):
                    deps.require_phase_lease_fn(phase=phase)
                    if deps.is_cancel_requested_fn(job):
                        raise_phase_attempt_cancelled(
                            phase=phase, reason="child chunk batch insert"
                        )
                    entry_batch = entries[start_index : start_index + inner_batch_size]
                    batch_rows: list[dict[str, Any]] = []
                    for entry in entry_batch:
                        original_anchor_id = entry_int(entry, "anchor_id")
                        anchor_id = original_anchor_id
                        if anchor_id <= 0:
                            anchor_id = int(
                                child_root_load_anchor_map.get(entry_str(entry, "anchor_key"), 0)
                                or 0
                            )
                        anchor_classification = classify_child_anchor(
                            original_anchor_id=original_anchor_id,
                            resolved_anchor_id=anchor_id,
                        )
                        if not anchor_classification.is_resolved:
                            failure_rows = build_child_anchor_failure_rows(
                                row_num=entry_row_num(entry),
                                row_data=entry_dict(entry, "data"),
                                anchor_classification=anchor_classification,
                            )
                            error_count += 1
                            load_errors.append(
                                failure_rows.user_row_error | {"data": entry_dict(entry, "data")}
                            )
                            continue
                        row_data = entry_dict(entry, "data")
                        row_data[child_parent_field] = anchor_classification.resolved_anchor_id
                        batch_rows.append(row_data)
                    if batch_rows:
                        insert_result = deps.run_with_phase_attempt_fence_fn(
                            phase=phase,
                            operation="child_chunk_batch_insert",
                            fn=lambda batch_rows=batch_rows: deps.timed_insert_batch_rows_fn(
                                write_session=write_session,
                                entity_type=str(chunk.entity_type or ""),
                                batch_rows=batch_rows,
                                load_outcome=load_outcome,
                                insert_batch_fn=deps.insert_batch_fn,
                            ),
                        )
                        batch_ids = insert_result.created_ids
                        batch_db_time = insert_result.db_duration
                        load_outcome.total_db_time += batch_db_time
                        deps.publish_tripwire_from_db_time_fn(batch_db_time)
                        created_count += len(batch_ids)
                        if batch_ids:
                            load_outcome.committed_entities.add(str(chunk.entity_type or ""))

            if load_errors:
                if chunk.chunk_role == ImportChunk.Role.CHILD:
                    orphan_decision = evaluate_orphan_threshold(
                        orphan_count=len(load_errors),
                        total_count=len(entries),
                    )
                    if orphan_decision.hard_fail:
                        deps.persist_load_errors_fn(
                            job=job,
                            chunk=chunk,
                            rows=load_errors,
                            phase=phase,
                        )
                        raise ImportLoadConsistencyError(
                            "A significant number of planned lines lost their parent anchor during load. Restart the import so those rows can be planned again.",
                            row_errors=load_errors,
                        )
                else:
                    deps.persist_load_errors_fn(
                        job=job,
                        chunk=chunk,
                        rows=load_errors,
                        phase=phase,
                    )
                    raise ImportLoadConsistencyError(
                        "A few planned lines changed while the import was loading. Restart the import so those rows can be planned again.",
                        row_errors=load_errors,
                    )

        deps.persist_load_errors_fn(job=job, chunk=chunk, rows=load_errors, phase=phase)

        return {
            "processed_count": len(entries),
            "created_count": created_count,
            "skipped_count": skipped_count,
            "error_count": error_count,
            "total_db_time": round(load_outcome.total_db_time, 6),
            "listing_wilaya_ids": sorted(load_outcome.listing_wilaya_ids),
            "demande_ids": sorted(load_outcome.demande_ids),
            "demande_client_ids": sorted(load_outcome.demande_client_ids),
            "offer_ids": sorted(load_outcome.offer_ids),
            "committed_entities": sorted(load_outcome.committed_entities),
            "created_anchor_map": created_anchor_map,
            "load_error_count": len(load_errors),
        }
    except Exception as exc:
        deps.publish_tripwire_from_exception_fn(exc)
        raise
    finally:
        deps.cleanup_temp_path_fn(planned_path)


__all__ = ["DistributedLoadPhaseDeps", "run_load_chunk_phase"]
