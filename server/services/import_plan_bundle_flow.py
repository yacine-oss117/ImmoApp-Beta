"""Same-side bundle planning flow."""

from __future__ import annotations

import math
from typing import Any, cast

from server.imports.models import ImportJob
from server.pg.uow import get_uow
from server.services.duplicate_checker import _normalize_phone_for_dedup
from server.services.import_agency_memory import (
    alias_domain_for_column_type,
    load_agency_alias_memory,
)
from server.services.import_constants import (
    DUPLICATE_STRATEGY_ALLOW_ALL,
    DUPLICATE_STRATEGY_REVIEW,
    ENTITY_TYPE_CLIENT,
    ENTITY_TYPE_DEMANDE,
    ENTITY_TYPE_LISTING,
)
from server.services.import_identity_resolution import (
    IdentityResolutionCache,
    prefetch_child_match_cache,
    prefetch_root_match_cache,
    resolve_child_anchor,
    resolve_existing_matches,
)
from server.services.import_mapping import build_column_types
from server.services.import_plan_common import (
    BlockedDuplicateResolutionErrorFn,
    PlanningRecoveryFn,
    PrefetchChildMatchCacheFn,
    PrefetchRootMatchCacheFn,
    ResolveChildAnchorFn,
    ResolveExistingMatchesFn,
    ValidateRowFn,
    apply_planning_recovery,
    blocked_duplicate_resolution_error,
    matching_anchor_key,
)
from server.services.import_progress_runtime import persist_job_progress
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
from server.services.import_rows import validate_row
from server.services.import_runtime_artifacts import (
    entry_dict,
    entry_row_num,
    entry_str_list,
    iter_jsonl_entry_batches,
    require_path,
    write_jsonl_entry,
)
from server.services.import_types import ImportResult, PreparedImportArtifact, ReviewRows


def plan_same_side_bundle_import(
    *,
    job: ImportJob,
    user_id: int,
    duplicate_strategy: str,
    skip_review_rows: bool,
    review_rows: ReviewRows,
    errors: list[dict[str, object]],
    result: ImportResult,
    artifact: PreparedImportArtifact,
    apply_planning_recovery_fn: PlanningRecoveryFn = apply_planning_recovery,
    blocked_duplicate_resolution_error_fn: BlockedDuplicateResolutionErrorFn = (
        blocked_duplicate_resolution_error
    ),
    prefetch_root_match_cache_fn: PrefetchRootMatchCacheFn = prefetch_root_match_cache,
    prefetch_child_match_cache_fn: PrefetchChildMatchCacheFn = prefetch_child_match_cache,
    resolve_child_anchor_fn: ResolveChildAnchorFn = resolve_child_anchor,
    validate_row_fn: ValidateRowFn = validate_row,
    resolve_existing_matches_fn: ResolveExistingMatchesFn = resolve_existing_matches,
) -> PreparedImportArtifact:
    spool_dir = require_path(artifact.spool_dir, field_name="spool_dir")
    root_entries_path = require_path(artifact.root_entries_path, field_name="root_entries_path")
    child_entries_path = require_path(artifact.child_entries_path, field_name="child_entries_path")
    planned_root_entries_path = spool_dir / "planned_root_entries.jsonl"
    planned_child_entries_path = spool_dir / "planned_child_entries.jsonl"
    resolution_cache = IdentityResolutionCache()
    agency_id = int(cast(Any, job).agency_id)
    seen_root_phones: set[str] = set()
    existing_anchor_map: dict[str, int] = {}
    planned_root_contexts: dict[str, dict[str, object]] = {}
    planned_root_anchor_keys: set[str] = set()
    planned_root_count = 0
    planned_child_count = 0
    current_chunk = 0
    root_chunks = max(1, math.ceil(artifact.root_row_count / max(1, artifact.current_batch_size)))
    child_chunks = max(1, math.ceil(artifact.child_row_count / max(1, artifact.current_batch_size)))
    column_types = build_column_types(
        detected_columns=job.detected_columns or [],
        column_mapping=job.column_mapping or {},
    )
    agency_memory = load_agency_alias_memory(
        agency_id,
        domains={
            domain
            for domain in (
                alias_domain_for_column_type(column_type) for column_type in column_types.values()
            )
            if domain
        },
    )

    with (
        planned_root_entries_path.open("w", encoding="utf-8") as root_handle,
        planned_child_entries_path.open("w", encoding="utf-8") as child_handle,
        get_uow().session(actor=f"import-plan:{job.id}") as read_session,
    ):
        for entry_batch in iter_jsonl_entry_batches(root_entries_path, artifact.current_batch_size):
            prefetch_root_match_cache_fn(
                entity_type=artifact.root_entity,
                rows=[entry_dict(entry, "data") for entry in entry_batch],
                session=read_session,
                agency_id=agency_id,
                cache=resolution_cache,
            )
            for entry in entry_batch:
                row_num = entry_row_num(entry)
                row_data = entry_dict(entry, "data")
                original = entry_dict(entry, "original")
                phone_val = row_data.get("phone")
                if phone_val and duplicate_strategy != DUPLICATE_STRATEGY_ALLOW_ALL:
                    dedup_phone = _normalize_phone_for_dedup(str(phone_val))
                    if dedup_phone and len(dedup_phone) >= 9:
                        if dedup_phone in seen_root_phones:
                            remark = "Duplicate phone in this file"
                            if (
                                duplicate_strategy == DUPLICATE_STRATEGY_REVIEW
                                and not skip_review_rows
                            ):
                                append_review_row_limited(
                                    review_rows,
                                    manual_review_row(
                                        row_num=row_num,
                                        row_data=row_data,
                                        original=original,
                                        entity_type=artifact.root_entity,
                                        topology_side=artifact.topology_side,
                                        review_fields=[
                                            {
                                                "field": "phone",
                                                "original": str(phone_val),
                                                "normalized": dedup_phone,
                                                "confidence": 1.0,
                                                "remark": remark,
                                            }
                                        ],
                                        remarks=[remark],
                                    ),
                                )
                                result.skipped_count += 1
                            elif duplicate_strategy == DUPLICATE_STRATEGY_REVIEW:
                                errors.append({"row": row_num, "errors": [remark]})
                                result.error_count += 1
                            else:
                                result.skipped_count += 1
                            continue
                        seen_root_phones.add(dedup_phone)

                validated_row, row_errors = validate_row_fn(row_data, artifact.root_entity)
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
                                entity_type=artifact.root_entity,
                                topology_side=artifact.topology_side,
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
                    resolution = resolve_existing_matches_fn(
                        entity_type=artifact.root_entity,
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
                            existing_anchor_map, validated_row, resolution.suggested_existing_id
                        )
                    if resolution.candidate_matches:
                        if duplicate_strategy == DUPLICATE_STRATEGY_REVIEW and not skip_review_rows:
                            append_review_row_limited(
                                review_rows,
                                review_row_from_resolution(
                                    row_num=row_num,
                                    row_data=validated_row,
                                    original=original,
                                    entity_type=artifact.root_entity,
                                    topology_side=artifact.topology_side,
                                    resolution=resolution,
                                ),
                            )
                            result.skipped_count += 1
                        elif duplicate_strategy == DUPLICATE_STRATEGY_REVIEW:
                            errors.append(
                                blocked_duplicate_resolution_error_fn(
                                    row_num=row_num,
                                    resolution=resolution,
                                )
                            )
                            result.error_count += 1
                        else:
                            result.skipped_count += 1
                        continue

                validated_row["created_by_id"] = user_id
                row_anchor_keys = anchor_map_keys(validated_row)
                planned_root_anchor_keys.update(row_anchor_keys)
                for anchor_key in row_anchor_keys:
                    planned_root_contexts[anchor_key] = dict(validated_row)
                write_jsonl_entry(
                    root_handle,
                    {
                        "row": row_num,
                        "data": validated_row,
                        "original": original,
                        "anchor_keys": row_anchor_keys,
                    },
                )
                planned_root_count += 1

            current_chunk += 1
            persist_job_progress(
                write_session=None,
                job=job,
                rows_total=artifact.total_rows,
                rows_processed=min(
                    artifact.root_row_count, current_chunk * artifact.current_batch_size
                ),
                rows_created=0,
                rows_updated=0,
                rows_skipped=result.skipped_count,
                rows_review=len(review_rows),
                current_chunk=current_chunk,
                chunks_total=root_chunks + child_chunks,
                phase="root_plan",
                bundle_mode=artifact.bundle_mode,
                progress=min(65, 35 + int((current_chunk / max(1, root_chunks)) * 30)),
                review_overflow_count_value=review_overflow_count(review_rows),
            )

        child_parent_field = (
            "client_id" if artifact.child_entity == ENTITY_TYPE_DEMANDE else "listing_id"
        )
        child_chunk_offset = current_chunk
        for child_chunk_index, entry_batch in enumerate(
            iter_jsonl_entry_batches(child_entries_path, artifact.current_batch_size),
            start=1,
        ):
            parent_entity = (
                ENTITY_TYPE_CLIENT
                if artifact.topology_side == "client_side"
                else ENTITY_TYPE_LISTING
            )
            prefetch_root_match_cache_fn(
                entity_type=parent_entity,
                rows=[entry_dict(entry, "data") for entry in entry_batch],
                session=read_session,
                agency_id=agency_id,
                cache=resolution_cache,
            )
            planned_rows: list[tuple[dict[str, object], dict[str, object], int, str]] = []
            anchor_ids: set[int] = set()
            for entry in entry_batch:
                row_data = entry_dict(entry, "data")
                anchor_id = resolve_child_anchor_fn(
                    topology_side=artifact.topology_side,
                    row_data=row_data,
                    session=read_session,
                    agency_id=agency_id,
                    local_anchor_map=existing_anchor_map,
                    cache=resolution_cache,
                )
                planned_anchor_key = ""
                if anchor_id <= 0:
                    for anchor_key in entry_str_list(entry, "root_anchor_keys"):
                        if anchor_key in existing_anchor_map:
                            anchor_id = int(existing_anchor_map.get(anchor_key, 0) or 0)
                            break
                        if anchor_key in planned_root_anchor_keys:
                            planned_anchor_key = anchor_key
                            break
                if anchor_id <= 0 and not planned_anchor_key:
                    planned_anchor_key = matching_anchor_key(row_data, planned_root_anchor_keys)
                planned_rows.append((entry, row_data, anchor_id, planned_anchor_key))
                if anchor_id > 0:
                    anchor_ids.add(anchor_id)

            prefetch_child_match_cache_fn(
                entity_type=artifact.child_entity,
                anchor_ids=anchor_ids,
                session=read_session,
                agency_id=agency_id,
                cache=resolution_cache,
            )

            for entry, row_data, anchor_id, planned_anchor_key in planned_rows:
                row_num = entry_row_num(entry)
                original = entry_dict(entry, "original")
                if anchor_id <= 0 and not planned_anchor_key:
                    remark = "Unable to resolve a same-agency parent anchor."
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
                                entity_type=artifact.child_entity,
                                topology_side=artifact.topology_side,
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
                # Unresolved planned-root children are validated without a synthetic parent id.
                if anchor_id > 0:
                    validated_input[child_parent_field] = anchor_id
                bundle_context = (
                    planned_root_contexts.get(planned_anchor_key) if planned_anchor_key else None
                )
                validated_input = apply_planning_recovery_fn(
                    row_data=validated_input,
                    original=original,
                    entity_type=artifact.child_entity,
                    column_types=column_types,
                    agency_memory=agency_memory,
                    bundle_context=bundle_context,
                )

                validated_row, row_errors = validate_row_fn(validated_input, artifact.child_entity)
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
                                entity_type=artifact.child_entity,
                                topology_side=artifact.topology_side,
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
                    resolution = resolve_existing_matches_fn(
                        entity_type=artifact.child_entity,
                        row_data=validated_row,
                        session=read_session,
                        agency_id=agency_id,
                        anchor_id=anchor_id,
                        cache=resolution_cache,
                    )
                    if resolution.candidate_matches:
                        if duplicate_strategy == DUPLICATE_STRATEGY_REVIEW and not skip_review_rows:
                            append_review_row_limited(
                                review_rows,
                                review_row_from_resolution(
                                    row_num=row_num,
                                    row_data=validated_row,
                                    original=original,
                                    entity_type=artifact.child_entity,
                                    topology_side=artifact.topology_side,
                                    resolution=resolution,
                                ),
                            )
                            result.skipped_count += 1
                        elif duplicate_strategy == DUPLICATE_STRATEGY_REVIEW:
                            errors.append(
                                blocked_duplicate_resolution_error_fn(
                                    row_num=row_num,
                                    resolution=resolution,
                                )
                            )
                            result.error_count += 1
                        else:
                            result.skipped_count += 1
                        continue

                validated_row["created_by_id"] = user_id
                if not planned_anchor_key:
                    validated_row[child_parent_field] = anchor_id
                else:
                    validated_row.pop(child_parent_field, None)

                write_jsonl_entry(
                    child_handle,
                    {
                        "row": row_num,
                        "data": validated_row,
                        "original": original,
                        "anchor_id": anchor_id,
                        "anchor_key": planned_anchor_key,
                    },
                )
                planned_child_count += 1

            persist_job_progress(
                write_session=None,
                job=job,
                rows_total=artifact.total_rows,
                rows_processed=artifact.root_row_count
                + min(artifact.child_row_count, child_chunk_index * artifact.current_batch_size),
                rows_created=0,
                rows_updated=0,
                rows_skipped=result.skipped_count,
                rows_review=len(review_rows),
                current_chunk=child_chunk_offset + child_chunk_index,
                chunks_total=root_chunks + child_chunks,
                phase="child_plan",
                bundle_mode=artifact.bundle_mode,
                progress=min(80, 65 + int((child_chunk_index / max(1, child_chunks)) * 15)),
                review_overflow_count_value=review_overflow_count(review_rows),
            )

    artifact.planned_root_entries_path = planned_root_entries_path
    artifact.planned_child_entries_path = planned_child_entries_path
    artifact.planned_root_row_count = planned_root_count
    artifact.planned_child_row_count = planned_child_count
    return artifact


__all__ = ["plan_same_side_bundle_import"]
