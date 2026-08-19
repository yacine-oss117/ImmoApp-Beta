"""Child-only planning flow."""

from __future__ import annotations

from typing import Any, cast

from server.imports.models import ImportJob
from server.pg.uow import get_uow
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
)
from server.services.import_progress_runtime import persist_job_progress
from server.services.import_review_row_runtime import (
    manual_review_row,
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
    iter_jsonl_entry_batches,
    require_path,
    write_jsonl_entry,
)
from server.services.import_types import ImportResult, PreparedImportArtifact, ReviewRows


def plan_child_only_import(
    *,
    job: ImportJob,
    user_id: int,
    entity_type: str,
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
    prepared_entries_path = require_path(
        artifact.prepared_entries_path,
        field_name="prepared_entries_path",
    )
    planned_entries_path = spool_dir / "planned_child_entries.jsonl"
    parent_field = "client_id" if entity_type == ENTITY_TYPE_DEMANDE else "listing_id"
    resolution_cache = IdentityResolutionCache()
    planned_count = 0
    agency_id = int(cast(Any, job).agency_id)
    current_chunk = 0
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
        planned_entries_path.open("w", encoding="utf-8") as planned_handle,
        get_uow().session(actor=f"import-plan:{job.id}") as read_session,
    ):
        for entry_batch in iter_jsonl_entry_batches(
            prepared_entries_path, artifact.current_batch_size
        ):
            prefetch_root_match_cache_fn(
                entity_type=(
                    ENTITY_TYPE_CLIENT
                    if artifact.topology_side == "client_side"
                    else ENTITY_TYPE_LISTING
                ),
                rows=[entry_dict(entry, "data") for entry in entry_batch],
                session=read_session,
                agency_id=agency_id,
                cache=resolution_cache,
            )
            planned_rows: list[tuple[dict[str, object], dict[str, object], int]] = []
            anchor_ids: set[int] = set()
            for entry in entry_batch:
                row_data = entry_dict(entry, "data")
                anchor_id = resolve_child_anchor_fn(
                    topology_side=artifact.topology_side,
                    row_data=row_data,
                    session=read_session,
                    agency_id=agency_id,
                    local_anchor_map=None,
                    cache=resolution_cache,
                )
                planned_rows.append((entry, row_data, anchor_id))
                if anchor_id > 0:
                    anchor_ids.add(anchor_id)

            prefetch_child_match_cache_fn(
                entity_type=entity_type,
                anchor_ids=anchor_ids,
                session=read_session,
                agency_id=agency_id,
                cache=resolution_cache,
            )

            for entry, row_data, anchor_id in planned_rows:
                row_num = entry_row_num(entry)
                original = entry_dict(entry, "original")
                if anchor_id <= 0:
                    remark = f"Unable to resolve a same-agency {parent_field} anchor."
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
                                entity_type=entity_type,
                                topology_side=artifact.topology_side,
                                review_fields=[
                                    {
                                        "field": parent_field,
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

                row_data[parent_field] = anchor_id
                row_data = apply_planning_recovery_fn(
                    row_data=row_data,
                    original=original,
                    entity_type=entity_type,
                    column_types=column_types,
                    agency_memory=agency_memory,
                )
                validated_row, row_errors = validate_row_fn(row_data, entity_type)
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
                                entity_type=entity_type,
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
                        entity_type=entity_type,
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
                                    entity_type=entity_type,
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
                write_jsonl_entry(
                    planned_handle,
                    {
                        "row": row_num,
                        "data": validated_row,
                        "original": original,
                    },
                )
                planned_count += 1

            current_chunk += 1
            persist_job_progress(
                write_session=None,
                job=job,
                rows_total=artifact.total_rows,
                rows_processed=min(
                    artifact.total_rows, current_chunk * artifact.current_batch_size
                ),
                rows_created=0,
                rows_updated=0,
                rows_skipped=result.skipped_count,
                rows_review=len(review_rows),
                current_chunk=current_chunk,
                chunks_total=artifact.chunks_total,
                phase="planning",
                bundle_mode=artifact.bundle_mode,
                progress=min(75, 35 + int((current_chunk / max(1, artifact.chunks_total)) * 40)),
                review_overflow_count_value=review_overflow_count(review_rows),
            )

    artifact.planned_entries_path = planned_entries_path
    artifact.planned_row_count = planned_count
    return artifact


__all__ = ["plan_child_only_import"]
