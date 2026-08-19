"""Planning owner for distributed importer chunk execution."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, cast

from server.imports.models import ImportArtifactManifest, ImportChunk, ImportChunkPhase, ImportJob
from server.services.import_constants import (
    DUPLICATE_STRATEGY_ALLOW_ALL,
    DUPLICATE_STRATEGY_REVIEW,
    ENTITY_TYPE_CLIENT,
    ENTITY_TYPE_DEMANDE,
    ENTITY_TYPE_LISTING,
    ENTITY_TYPE_OFFER,
)
from server.services.import_identity_resolution import (
    IdentityResolutionCache,
    resolve_existing_matches,
)
from server.services.import_phase_attempts import (
    StaleImportPhaseLeaseError,
    raise_phase_attempt_cancelled,
)
from server.services.import_planning_service import (
    plan_child_only_import,
    plan_single_entity_import,
)
from server.services.import_review_row_runtime import (
    anchor_map_keys,
    manual_review_row,
    remember_anchor,
    review_row_from_resolution,
)
from server.services.import_review_runtime import (
    append_review_row_limited,
    review_overflow_count,
)
from server.services.import_runtime_artifacts import (
    entry_dict,
    entry_row_num,
    entry_str_list,
    iter_jsonl_entries,
    write_jsonl_entry,
)
from server.services.import_type_inference import unsupported_child_only_import_message
from server.services.import_types import ImportResult, PreparedImportArtifact, ReviewRowBuffer


@dataclass(frozen=True)
class DistributedPlanPhaseDeps:
    matching_anchor_key_fn: Callable[[dict[str, object], set[str]], str]
    temp_jsonl_path_fn: Callable[[str], Path]
    cleanup_temp_path_fn: Callable[[Path | None], None]
    require_phase_lease_fn: Callable[..., None]
    is_cancel_requested_fn: Callable[[ImportJob], bool]
    phase_lease_active_fn: Callable[..., bool]
    run_with_phase_attempt_fence_fn: Callable[..., Any]
    planned_root_plan_index_fn: Callable[[ImportJob], dict[str, Any]]
    blocked_duplicate_resolution_message_fn: Callable[[object], str]
    manifest_for_chunk_fn: Callable[..., Any]
    load_manifest_to_temp_fn: Callable[[Any], Path]
    get_uow_fn: Callable[[], Any]
    workflow_payload_fn: Callable[[ImportJob], dict[str, Any]]
    prefetch_root_match_cache_fn: Callable[..., None]
    prefetch_child_match_cache_fn: Callable[..., None]
    resolve_child_anchor_fn: Callable[..., int]
    validate_row_fn: Callable[[dict[str, Any], str], tuple[dict[str, Any], list[str]]]
    persist_file_manifest_fn: Callable[..., object]
    persist_jsonl_manifest_fn: Callable[..., object]


def run_plan_chunk_phase(
    *,
    phase: ImportChunkPhase,
    user_id: int,
    deps: DistributedPlanPhaseDeps,
) -> dict[str, Any]:
    chunk = phase.chunk
    job = cast(ImportJob, chunk.job)
    prepared_manifest = deps.manifest_for_chunk_fn(
        chunk=chunk,
        phase=ImportArtifactManifest.Phase.PREPARE,
        artifact_kind="prepared",
    )
    if prepared_manifest is None:
        raise ValueError(f"Missing prepared artifact manifest for chunk {chunk.id}.")
    prepared_path = deps.load_manifest_to_temp_fn(prepared_manifest)
    planned_path = deps.temp_jsonl_path_fn("immoapp-import-planned-")
    review_rows = ReviewRowBuffer()
    errors: list[dict[str, Any]] = []
    result = ImportResult(success=False)
    resolution_cache = IdentityResolutionCache()
    workflow = deps.workflow_payload_fn(job)
    params = dict(workflow.get("params", {}) or {})
    duplicate_strategy = str(params.get("duplicate_strategy", "skip") or "skip")
    skip_review_rows = bool(params.get("skip_review_rows", False))
    agency_id = int(getattr(job, "agency_id", 0) or 0)
    planned_count = 0
    existing_anchor_map: dict[str, int] = {}
    planned_root_anchor_keys: set[str] = set()

    try:
        with (
            planned_path.open("w", encoding="utf-8") as planned_handle,
            deps.get_uow_fn().session(
                actor=f"import-plan-chunk:{job.id}:{chunk.id}"
            ) as read_session,
        ):
            entries = [dict(entry) for entry in iter_jsonl_entries(prepared_path)]
            if chunk.chunk_role == ImportChunk.Role.SINGLE:
                entity_type = str(chunk.entity_type or "")
                unsupported_message = unsupported_child_only_import_message(
                    {
                        "bundle_mode": "single_entity",
                        "detected_entity": entity_type,
                    }
                )
                if unsupported_message:
                    raise ValueError(unsupported_message)
                delegated_artifact = PreparedImportArtifact(
                    bundle_mode="single_entity",
                    total_rows=len(entries),
                    current_batch_size=max(1, len(entries)),
                    chunks_total=1,
                    spool_dir=planned_path.parent,
                    prepared_entries_path=prepared_path,
                    entity_type=entity_type,
                    topology_side=str(workflow.get("topology_side", "unknown") or "unknown"),
                )
                if entity_type in {ENTITY_TYPE_DEMANDE, ENTITY_TYPE_OFFER}:
                    delegated_artifact = plan_child_only_import(
                        job=job,
                        user_id=user_id,
                        entity_type=entity_type,
                        duplicate_strategy=duplicate_strategy,
                        skip_review_rows=skip_review_rows,
                        review_rows=review_rows,
                        errors=errors,
                        result=result,
                        artifact=delegated_artifact,
                    )
                else:
                    delegated_artifact = plan_single_entity_import(
                        job=job,
                        entity_type=entity_type,
                        duplicate_strategy=duplicate_strategy,
                        skip_review_rows=skip_review_rows,
                        review_rows=review_rows,
                        errors=errors,
                        result=result,
                        artifact=delegated_artifact,
                    )
                delegated_planned_path = cast(Path | None, delegated_artifact.planned_entries_path)
                if delegated_planned_path is None:
                    raise ValueError(f"Missing planned entries path for chunk {chunk.id}.")
                planned_handle.close()
                planned_path.unlink(missing_ok=True)
                planned_path = delegated_planned_path
                planned_count = int(getattr(delegated_artifact, "planned_row_count", 0) or 0)

            elif chunk.chunk_role == ImportChunk.Role.ROOT:
                deps.prefetch_root_match_cache_fn(
                    entity_type=str(chunk.entity_type or ""),
                    rows=[entry_dict(entry, "data") for entry in entries],
                    session=read_session,
                    agency_id=agency_id,
                    cache=resolution_cache,
                )
                for entry in entries:
                    deps.require_phase_lease_fn(phase=phase)
                    row_num = entry_row_num(entry)
                    row_data = entry_dict(entry, "data")
                    original = entry_dict(entry, "original")

                    validated_row, row_errors = deps.validate_row_fn(
                        row_data,
                        str(chunk.entity_type or ""),
                    )
                    if row_errors:
                        if skip_review_rows:
                            errors.append({"row": row_num, "errors": row_errors})
                            result.error_count += 1
                        else:
                            append_review_row_limited(
                                review_rows,
                                manual_review_row(
                                    row_num=row_num,
                                    row_data=row_data,
                                    original=original,
                                    entity_type=str(chunk.entity_type or ""),
                                    topology_side=str(workflow.get("topology_side", "unknown")),
                                    review_fields=[
                                        {
                                            "field": "validation",
                                            "original": "",
                                            "normalized": "",
                                            "confidence": 0.0,
                                            "remark": "; ".join(row_errors),
                                        }
                                    ],
                                    remarks=row_errors,
                                ),
                            )
                            result.skipped_count += 1
                        continue

                    if duplicate_strategy != DUPLICATE_STRATEGY_ALLOW_ALL:
                        resolution = resolve_existing_matches(
                            entity_type=str(chunk.entity_type or ""),
                            row_data=validated_row,
                            session=read_session,
                            agency_id=agency_id,
                            cache=resolution_cache,
                        )
                        if (
                            resolution.suggested_action == "update_existing"
                            and resolution.suggested_existing_id > 0
                        ):
                            remember_anchor(
                                existing_anchor_map,
                                validated_row,
                                resolution.suggested_existing_id,
                            )
                        if resolution.candidate_matches:
                            if (
                                duplicate_strategy == DUPLICATE_STRATEGY_REVIEW
                                and not skip_review_rows
                            ):
                                append_review_row_limited(
                                    review_rows,
                                    review_row_from_resolution(
                                        row_num=row_num,
                                        row_data=validated_row,
                                        original=original,
                                        entity_type=str(chunk.entity_type or ""),
                                        topology_side=str(workflow.get("topology_side", "unknown")),
                                        resolution=resolution,
                                    ),
                                )
                                result.skipped_count += 1
                            elif duplicate_strategy == DUPLICATE_STRATEGY_REVIEW:
                                errors.append(
                                    {
                                        "row": row_num,
                                        "errors": [
                                            deps.blocked_duplicate_resolution_message_fn(resolution)
                                        ],
                                    }
                                )
                                result.error_count += 1
                            else:
                                result.skipped_count += 1
                            continue

                    validated_row["created_by_id"] = user_id
                    row_anchor_keys = anchor_map_keys(validated_row)
                    planned_root_anchor_keys.update(row_anchor_keys)
                    write_jsonl_entry(
                        planned_handle,
                        {
                            "row": row_num,
                            "data": validated_row,
                            "original": original,
                            "anchor_keys": row_anchor_keys,
                        },
                    )
                    planned_count += 1

            else:
                row_topology_side = str(workflow.get("topology_side", "unknown"))
                parent_entity = (
                    ENTITY_TYPE_CLIENT
                    if row_topology_side == "client_side"
                    else ENTITY_TYPE_LISTING
                )
                root_plan_index = deps.planned_root_plan_index_fn(job)
                local_anchor_map = dict(root_plan_index.get("existing_anchor_map", {}) or {})
                planned_root_keys = set(root_plan_index.get("planned_root_anchor_keys", []) or [])
                deps.prefetch_root_match_cache_fn(
                    entity_type=parent_entity,
                    rows=[entry_dict(entry, "data") for entry in entries],
                    session=read_session,
                    agency_id=agency_id,
                    cache=resolution_cache,
                )
                planned_rows: list[tuple[dict[str, Any], dict[str, Any], int, str]] = []
                anchor_ids: set[int] = set()
                for entry in entries:
                    row_data = entry_dict(entry, "data")
                    anchor_id = deps.resolve_child_anchor_fn(
                        topology_side=row_topology_side,
                        row_data=row_data,
                        session=read_session,
                        agency_id=agency_id,
                        local_anchor_map=local_anchor_map,
                        cache=resolution_cache,
                    )
                    planned_anchor_key = ""
                    if anchor_id <= 0:
                        for anchor_key in entry_str_list(entry, "root_anchor_keys"):
                            if anchor_key in local_anchor_map:
                                anchor_id = int(local_anchor_map.get(anchor_key, 0) or 0)
                                break
                            if anchor_key in planned_root_keys:
                                planned_anchor_key = anchor_key
                                break
                    if anchor_id <= 0 and not planned_anchor_key:
                        planned_anchor_key = deps.matching_anchor_key_fn(
                            row_data,
                            planned_root_keys,
                        )
                    planned_rows.append((entry, row_data, anchor_id, planned_anchor_key))
                    if anchor_id > 0:
                        anchor_ids.add(anchor_id)

                deps.prefetch_child_match_cache_fn(
                    entity_type=str(chunk.entity_type or ""),
                    anchor_ids=anchor_ids,
                    session=read_session,
                    agency_id=agency_id,
                    cache=resolution_cache,
                )

                child_parent_field = (
                    "client_id"
                    if str(chunk.entity_type or "") == ENTITY_TYPE_DEMANDE
                    else "listing_id"
                )
                for entry, row_data, anchor_id, planned_anchor_key in planned_rows:
                    deps.require_phase_lease_fn(phase=phase)
                    row_num = entry_row_num(entry)
                    original = entry_dict(entry, "original")
                    if anchor_id <= 0 and not planned_anchor_key:
                        remark = "Unable to resolve a same-agency parent anchor."
                        if anchor_id < 0:
                            remark = (
                                "A same-agency parent was found but confidence was too low "
                                "to anchor automatically. Review the parent record."
                            )
                        if skip_review_rows:
                            errors.append({"row": row_num, "errors": [remark]})
                            result.error_count += 1
                        else:
                            append_review_row_limited(
                                review_rows,
                                manual_review_row(
                                    row_num=row_num,
                                    row_data=row_data,
                                    original=original,
                                    entity_type=str(chunk.entity_type or ""),
                                    topology_side=row_topology_side,
                                    review_fields=[
                                        {
                                            "field": child_parent_field,
                                            "original": "",
                                            "normalized": "",
                                            "confidence": 0.0,
                                            "remark": remark,
                                        }
                                    ],
                                    remarks=[remark],
                                ),
                            )
                            result.skipped_count += 1
                        continue

                    validated_input = dict(row_data)
                    if anchor_id > 0:
                        validated_input[child_parent_field] = anchor_id
                    validated_row, row_errors = deps.validate_row_fn(
                        validated_input,
                        str(chunk.entity_type or ""),
                    )
                    if row_errors:
                        if skip_review_rows:
                            errors.append({"row": row_num, "errors": row_errors})
                            result.error_count += 1
                        else:
                            append_review_row_limited(
                                review_rows,
                                manual_review_row(
                                    row_num=row_num,
                                    row_data=validated_input,
                                    original=original,
                                    entity_type=str(chunk.entity_type or ""),
                                    topology_side=row_topology_side,
                                    review_fields=[
                                        {
                                            "field": "validation",
                                            "original": "",
                                            "normalized": "",
                                            "confidence": 0.0,
                                            "remark": "; ".join(row_errors),
                                        }
                                    ],
                                    remarks=row_errors,
                                ),
                            )
                            result.skipped_count += 1
                        continue

                    if anchor_id > 0 and duplicate_strategy != DUPLICATE_STRATEGY_ALLOW_ALL:
                        resolution = resolve_existing_matches(
                            entity_type=str(chunk.entity_type or ""),
                            row_data=validated_row,
                            session=read_session,
                            agency_id=agency_id,
                            anchor_id=anchor_id,
                            cache=resolution_cache,
                        )
                        if resolution.candidate_matches:
                            if (
                                duplicate_strategy == DUPLICATE_STRATEGY_REVIEW
                                and not skip_review_rows
                            ):
                                append_review_row_limited(
                                    review_rows,
                                    review_row_from_resolution(
                                        row_num=row_num,
                                        row_data=validated_row,
                                        original=original,
                                        entity_type=str(chunk.entity_type or ""),
                                        topology_side=row_topology_side,
                                        resolution=resolution,
                                    ),
                                )
                                result.skipped_count += 1
                            elif duplicate_strategy == DUPLICATE_STRATEGY_REVIEW:
                                errors.append(
                                    {
                                        "row": row_num,
                                        "errors": [
                                            deps.blocked_duplicate_resolution_message_fn(resolution)
                                        ],
                                    }
                                )
                                result.error_count += 1
                            else:
                                result.skipped_count += 1
                            continue

                    validated_row["created_by_id"] = user_id
                    if anchor_id > 0:
                        validated_row[child_parent_field] = anchor_id
                    else:
                        validated_row.pop(child_parent_field, None)
                    write_jsonl_entry(
                        planned_handle,
                        {
                            "row": row_num,
                            "data": validated_row,
                            "original": original,
                            "anchor_id": anchor_id,
                            "anchor_key": planned_anchor_key,
                        },
                    )
                    planned_count += 1

        if deps.is_cancel_requested_fn(job):
            raise_phase_attempt_cancelled(phase=phase, reason="persisting plan artifacts")

        if not deps.phase_lease_active_fn(
            phase_id=phase.id,
            lease_token=str(phase.lease_token or ""),
        ):
            raise StaleImportPhaseLeaseError(
                f"Chunk phase {phase.id} lost its lease before persisting plan artifacts."
            )
        deps.run_with_phase_attempt_fence_fn(
            phase=phase,
            operation="persist_plan_artifact",
            fn=lambda: deps.persist_file_manifest_fn(
                job=job,
                phase=ImportArtifactManifest.Phase.PLAN,
                artifact_kind="planned",
                path=planned_path,
                chunk=chunk,
                row_count=planned_count,
                metadata={"processed_count": len(entries)},
            ),
        )
        if review_rows:
            review_spool_path = getattr(review_rows, "spool_path", None)
            if isinstance(review_spool_path, Path) and review_spool_path.exists():
                flush_review_rows = getattr(review_rows, "flush", None)
                if callable(flush_review_rows):
                    flush_review_rows()
                if not deps.phase_lease_active_fn(
                    phase_id=phase.id,
                    lease_token=str(phase.lease_token or ""),
                ):
                    raise StaleImportPhaseLeaseError(
                        f"Chunk phase {phase.id} lost its lease before persisting review artifacts."
                    )
                deps.run_with_phase_attempt_fence_fn(
                    phase=phase,
                    operation="persist_review_file_artifact",
                    fn=lambda: deps.persist_file_manifest_fn(
                        job=job,
                        phase=ImportArtifactManifest.Phase.PLAN,
                        artifact_kind="review_rows",
                        path=review_spool_path,
                        chunk=chunk,
                        row_count=len(review_rows),
                    ),
                )
            else:
                if not deps.phase_lease_active_fn(
                    phase_id=phase.id,
                    lease_token=str(phase.lease_token or ""),
                ):
                    raise StaleImportPhaseLeaseError(
                        f"Chunk phase {phase.id} lost its lease before persisting review artifacts."
                    )
                deps.run_with_phase_attempt_fence_fn(
                    phase=phase,
                    operation="persist_review_jsonl_artifact",
                    fn=lambda: deps.persist_jsonl_manifest_fn(
                        job=job,
                        phase=ImportArtifactManifest.Phase.PLAN,
                        artifact_kind="review_rows",
                        rows=[dict(row) for row in review_rows],
                        chunk=chunk,
                    ),
                )
        if errors:
            if not deps.phase_lease_active_fn(
                phase_id=phase.id,
                lease_token=str(phase.lease_token or ""),
            ):
                raise StaleImportPhaseLeaseError(
                    f"Chunk phase {phase.id} lost its lease before persisting error artifacts."
                )
            deps.run_with_phase_attempt_fence_fn(
                phase=phase,
                operation="persist_error_artifact",
                fn=lambda: deps.persist_jsonl_manifest_fn(
                    job=job,
                    phase=ImportArtifactManifest.Phase.PLAN,
                    artifact_kind="errors",
                    rows=errors,
                    chunk=chunk,
                ),
            )
        return {
            "processed_count": len(entries),
            "planned_count": planned_count,
            "review_count": len(review_rows),
            "skipped_count": int(result.skipped_count),
            "error_count": int(result.error_count),
            "review_overflow_count": review_overflow_count(review_rows),
            "existing_anchor_map": existing_anchor_map,
            "planned_root_anchor_keys": sorted(planned_root_anchor_keys),
        }
    finally:
        review_rows.cleanup()
        deps.cleanup_temp_path_fn(prepared_path)
        deps.cleanup_temp_path_fn(planned_path)


__all__ = ["DistributedPlanPhaseDeps", "run_plan_chunk_phase"]
