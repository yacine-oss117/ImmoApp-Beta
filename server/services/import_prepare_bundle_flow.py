"""Same-side bundle prepare flow."""

from __future__ import annotations

import math
import tempfile
import time
from pathlib import Path
from typing import Any, cast

from core.importer.normalize_pipeline import NormalizationPipeline
from core.utils.memory_guard import adaptive_chunk_size
from server.imports.models import ImportDeadLetterRow, ImportJob
from server.services.import_constants import (
    DUPLICATE_STRATEGY_ALLOW_ALL,
    DUPLICATE_STRATEGY_REVIEW,
)
from server.services.import_dead_letter import record_dead_letter_rows
from server.services.import_execution_governor import profile_aware_chunk_ceiling
from server.services.import_mapping import build_column_types, merge_row_corrections
from server.services.import_parsers import parser_for_file_type
from server.services.import_prepare_common import (
    DownloadToTemp,
    InferRowEntityFn,
    agency_memory,
    append_prepare_dead_letter,
    bundle_child_payload,
    bundle_root_payload,
    bundle_row_has_root_identity,
    duplicate_root_conflict_fields,
    merge_dead_letter_summary,
    normalized_review_fields_or_validation,
    selected_sheet_name,
)
from server.services.import_price_dialect import build_field_price_metadata
from server.services.import_progress_runtime import persist_job_progress
from server.services.import_recovery import apply_row_recovery
from server.services.import_review_policy import REVIEW_AMBIGUOUS
from server.services.import_review_row_runtime import anchor_map_keys, manual_review_row
from server.services.import_review_runtime import (
    append_review_row_limited,
    review_overflow_count,
)
from server.services.import_root_key_index import remember_root_key
from server.services.import_runtime_artifacts import write_jsonl_entry
from server.services.import_type_inference import infer_row_entity
from server.services.import_types import (
    ImportResult,
    PreparedImportArtifact,
    ReviewFieldPayload,
    ReviewRows,
)
from server.services.storage import download_to_temp


def prepare_same_side_bundle_import(
    *,
    job: ImportJob,
    root_entity: str,
    child_entity: str,
    topology_side: str,
    skip_rows: int,
    skip_review_rows: bool,
    duplicate_strategy: str,
    corrections: dict[str, dict[str, Any]] | None,
    review_rows: ReviewRows,
    result: ImportResult,
    download_to_temp_fn: DownloadToTemp = download_to_temp,
    infer_row_entity_fn: InferRowEntityFn = infer_row_entity,
) -> PreparedImportArtifact:
    total_rows = int((job.result_summary or {}).get("row_count") or 0)
    column_mapping = job.column_mapping or {}
    column_types = build_column_types(
        detected_columns=job.detected_columns or [],
        column_mapping=column_mapping,
    )
    agency_memory_value = agency_memory(job, column_types)
    field_price_metadata = build_field_price_metadata(
        agency_id=int(getattr(job, "agency_id", 0) or 0),
        column_mapping=dict(column_mapping or {}),
        inference_summary=dict(job.inference_summary or {}),
    )
    parser: Any = parser_for_file_type(
        job.file_type,
        skip_rows=skip_rows,
        sheet_name=selected_sheet_name(job),
    )
    temp_path = download_to_temp_fn(job.source_path, suffix=Path(job.filename).suffix)
    spool_dir = Path(tempfile.mkdtemp(prefix="immoapp-import-bundle-"))
    root_entries_path = spool_dir / "root_entries.jsonl"
    child_entries_path = spool_dir / "child_entries.jsonl"
    root_pipeline = NormalizationPipeline(
        entity_type=root_entity,
        column_types=column_types,
        field_metadata=field_price_metadata,
    )
    child_pipeline = NormalizationPipeline(
        entity_type=child_entity,
        column_types=column_types,
        field_metadata=field_price_metadata,
    )
    root_row_count = 0
    child_row_count = 0
    seen_root_keys: dict[str, int] = {}
    seen_root_contexts: dict[str, dict[str, Any]] = {}
    min_batch = 50
    max_batch = 3000
    current_batch_size = adaptive_chunk_size(
        floor=min_batch,
        ceiling=profile_aware_chunk_ceiling(max_batch),
    )
    parse_chunks_total = (
        max(1, math.ceil(total_rows / max(1, current_batch_size))) if total_rows else 0
    )
    last_progress_update = 0.0
    last_progress_row = 0
    progress_step = 100
    progress_interval = 1.0
    dead_letter_rows: list[ImportDeadLetterRow] = []

    with (
        root_entries_path.open("w", encoding="utf-8") as root_handle,
        child_entries_path.open("w", encoding="utf-8") as child_handle,
    ):
        for i, raw_row in enumerate(parser.iter_dicts(temp_path)):
            row_num = i + 1
            raw_row = merge_row_corrections(
                raw_row=raw_row,
                row_index=row_num,
                corrections=corrections,
            )
            mapped_row = {
                field_name: raw_row[header_name]
                for field_name, header_name in column_mapping.items()
                if header_name in raw_row
            }
            row_inference = infer_row_entity_fn(
                mapped_row,
                bundle_mode="same_side_bundle",
                default_entity_type=root_entity,
                topology_side_hint=topology_side,
            )
            row_entity_type = str(row_inference.entity_type or "").strip().lower()
            if row_entity_type not in {root_entity, child_entity}:
                reason_messages = list(
                    row_inference.reasons or ["Unable to infer row entity type during prepare."]
                )
                if skip_review_rows:
                    result.errors.append({"row": row_num, "errors": reason_messages})
                    result.error_count += 1
                    append_prepare_dead_letter(
                        rows=dead_letter_rows,
                        job=job,
                        row_num=row_num,
                        entity_type=root_entity,
                        topology_side=topology_side,
                        raw_row=dict(raw_row),
                        normalized_data=dict(mapped_row),
                        recoverability_class="blocking",
                        recovered_fields=[],
                        recovery_candidates=[],
                        blocking_reasons=[],
                        disposition=ImportDeadLetterRow.Disposition.BLOCKING_DISCARDED,
                        reason_codes=[
                            "prepare_unclassified_row",
                            *list(row_inference.reason_codes),
                        ],
                        reason_messages=reason_messages,
                    )
                else:
                    append_review_row_limited(
                        review_rows,
                        manual_review_row(
                            row_num=row_num,
                            row_data=dict(mapped_row),
                            original=dict(raw_row),
                            entity_type=root_entity,
                            topology_side=topology_side,
                            review_fields=[
                                cast(
                                    ReviewFieldPayload,
                                    {
                                        "field": "entity_type",
                                        "original": "",
                                        "normalized": str(row_inference.entity_type or ""),
                                        "confidence": float(row_inference.confidence or 0.0),
                                        "remark": (
                                            "Row could not be classified into the allowed "
                                            "same-side bundle."
                                        ),
                                    },
                                )
                            ],
                            remarks=list(
                                row_inference.reasons or ["Unable to infer row entity type"]
                            ),
                        ),
                    )
                    result.skipped_count += 1
                continue

            row_has_root_identity = bundle_row_has_root_identity(mapped_row)
            emit_root_entry = row_entity_type == root_entity or row_has_root_identity
            emit_child_entry = row_entity_type == child_entity
            bundle_root_anchor_keys = anchor_map_keys(bundle_root_payload(mapped_row))

            if emit_root_entry:
                root_payload = bundle_root_payload(mapped_row)
                root_normalized = root_pipeline.normalize_row(root_payload)
                root_normalized = apply_row_recovery(
                    normalized=root_normalized,
                    raw_row=root_payload,
                    entity_type=root_entity,
                    column_types=column_types,
                    memory=agency_memory_value,
                )
                if root_normalized.needs_review:
                    if skip_review_rows:
                        result.errors.append(
                            {"row": row_num, "errors": list(root_normalized.remarks)}
                        )
                        result.error_count += 1
                        append_prepare_dead_letter(
                            rows=dead_letter_rows,
                            job=job,
                            row_num=row_num,
                            entity_type=root_entity,
                            topology_side=topology_side,
                            raw_row=dict(raw_row),
                            normalized_data=dict(root_normalized.data),
                            recoverability_class=str(root_normalized.recoverability_class),
                            recovered_fields=list(root_normalized.recovered_fields),
                            recovery_candidates=list(root_normalized.recovery_candidates),
                            blocking_reasons=list(root_normalized.blocking_reasons),
                            disposition=ImportDeadLetterRow.Disposition.BLOCKING_DISCARDED,
                            reason_codes=["prepare_review_blocked"],
                            reason_messages=list(
                                root_normalized.remarks or ["Review required during prepare."]
                            ),
                        )
                    else:
                        append_review_row_limited(
                            review_rows,
                            manual_review_row(
                                row_num=row_num,
                                row_data=dict(root_normalized.data),
                                original=dict(raw_row),
                                entity_type=root_entity,
                                topology_side=topology_side,
                                review_fields=normalized_review_fields_or_validation(
                                    root_normalized
                                ),
                                remarks=list(root_normalized.remarks or ["Review required"]),
                                recoverability_class=str(root_normalized.recoverability_class),
                                recovered_fields=list(root_normalized.recovered_fields),
                                recovery_candidates=list(root_normalized.recovery_candidates),
                                blocking_reasons=list(root_normalized.blocking_reasons),
                            ),
                        )
                        result.skipped_count += 1
                    continue

                bundle_root_anchor_keys = anchor_map_keys(dict(root_normalized.data))
                root_entry = {
                    "row": row_num,
                    "data": dict(root_normalized.data),
                    "original": dict(raw_row),
                    "entity_type": root_entity,
                }
                root_skipped = False
                if duplicate_strategy != DUPLICATE_STRATEGY_ALLOW_ALL:
                    root_key = remember_root_key(
                        seen_root_keys,
                        row_data=root_normalized.data,
                        row_num=row_num,
                    )
                    if root_key.is_duplicate:
                        base_remark = (
                            "Duplicate root key in this file; first matching row is "
                            f"{root_key.winner_row}."
                        )
                        winner_context = seen_root_contexts.get(str(root_key.key or ""), {})
                        conflict_fields = duplicate_root_conflict_fields(
                            winner_context,
                            dict(root_normalized.data),
                        )
                        if conflict_fields:
                            remark = (
                                f"{base_remark} Conflicting root fields: "
                                f"{', '.join(conflict_fields)}."
                            )
                        else:
                            remark = (
                                f"Repeated root identity grouped under first matching row "
                                f"{root_key.winner_row}."
                            )
                        if (
                            conflict_fields
                            and duplicate_strategy == DUPLICATE_STRATEGY_REVIEW
                            and not skip_review_rows
                        ):
                            append_review_row_limited(
                                review_rows,
                                manual_review_row(
                                    row_num=row_num,
                                    row_data=dict(root_normalized.data),
                                    original=dict(raw_row),
                                    entity_type=root_entity,
                                    topology_side=topology_side,
                                    review_fields=[
                                        cast(
                                            ReviewFieldPayload,
                                            {
                                                "field": "phone",
                                                "original": str(
                                                    root_normalized.data.get("phone", "") or ""
                                                ),
                                                "normalized": str(root_key.key or ""),
                                                "confidence": 1.0,
                                                "remark": remark,
                                            },
                                        )
                                    ],
                                    remarks=[remark],
                                    suggested_action=REVIEW_AMBIGUOUS,
                                    suggested_reasons=[remark],
                                ),
                            )
                            result.skipped_count += 1
                            continue
                        if conflict_fields and duplicate_strategy == DUPLICATE_STRATEGY_REVIEW:
                            result.errors.append({"row": row_num, "errors": [remark]})
                            result.error_count += 1
                            append_prepare_dead_letter(
                                rows=dead_letter_rows,
                                job=job,
                                row_num=row_num,
                                entity_type=root_entity,
                                topology_side=topology_side,
                                raw_row=dict(raw_row),
                                normalized_data=dict(root_normalized.data),
                                recoverability_class=str(root_normalized.recoverability_class),
                                recovered_fields=list(root_normalized.recovered_fields),
                                recovery_candidates=list(root_normalized.recovery_candidates),
                                blocking_reasons=list(root_normalized.blocking_reasons),
                                disposition=ImportDeadLetterRow.Disposition.BLOCKING_DISCARDED,
                                reason_codes=["prepare_duplicate_root_conflict"],
                                reason_messages=[remark],
                            )
                            continue
                        result.skipped_count += 1
                        append_prepare_dead_letter(
                            rows=dead_letter_rows,
                            job=job,
                            row_num=row_num,
                            entity_type=root_entity,
                            topology_side=topology_side,
                            raw_row=dict(raw_row),
                            normalized_data=dict(root_normalized.data),
                            recoverability_class=str(root_normalized.recoverability_class),
                            recovered_fields=list(root_normalized.recovered_fields),
                            recovery_candidates=list(root_normalized.recovery_candidates),
                            blocking_reasons=list(root_normalized.blocking_reasons),
                            disposition=ImportDeadLetterRow.Disposition.AUTO_SKIPPED,
                            reason_codes=["prepare_duplicate_root_key"],
                            reason_messages=[remark],
                        )
                        root_skipped = True
                    if root_key.key and not root_skipped:
                        seen_root_contexts[str(root_key.key)] = dict(root_normalized.data)
                if not root_skipped:
                    write_jsonl_entry(root_handle, root_entry)
                    root_row_count += 1

            if emit_child_entry:
                child_payload = bundle_child_payload(
                    mapped_row,
                    topology_side=topology_side,
                )
                child_normalized = child_pipeline.normalize_row(child_payload)
                child_normalized = apply_row_recovery(
                    normalized=child_normalized,
                    raw_row=child_payload,
                    entity_type=child_entity,
                    column_types=column_types,
                    memory=agency_memory_value,
                    deferred_required_fields=(
                        {"client_id"}
                        if child_entity == "demande"
                        else ({"listing_id"} if child_entity == "offer" else None)
                    ),
                )
                if child_normalized.needs_review:
                    if skip_review_rows:
                        result.errors.append(
                            {"row": row_num, "errors": list(child_normalized.remarks)}
                        )
                        result.error_count += 1
                        append_prepare_dead_letter(
                            rows=dead_letter_rows,
                            job=job,
                            row_num=row_num,
                            entity_type=child_entity,
                            topology_side=topology_side,
                            raw_row=dict(raw_row),
                            normalized_data=dict(child_normalized.data),
                            recoverability_class=str(child_normalized.recoverability_class),
                            recovered_fields=list(child_normalized.recovered_fields),
                            recovery_candidates=list(child_normalized.recovery_candidates),
                            blocking_reasons=list(child_normalized.blocking_reasons),
                            disposition=ImportDeadLetterRow.Disposition.BLOCKING_DISCARDED,
                            reason_codes=["prepare_review_blocked"],
                            reason_messages=list(
                                child_normalized.remarks or ["Review required during prepare."]
                            ),
                        )
                    else:
                        append_review_row_limited(
                            review_rows,
                            manual_review_row(
                                row_num=row_num,
                                row_data=dict(child_normalized.data),
                                original=dict(raw_row),
                                entity_type=child_entity,
                                topology_side=topology_side,
                                review_fields=normalized_review_fields_or_validation(
                                    child_normalized
                                ),
                                remarks=list(child_normalized.remarks or ["Review required"]),
                                recoverability_class=str(child_normalized.recoverability_class),
                                recovered_fields=list(child_normalized.recovered_fields),
                                recovery_candidates=list(child_normalized.recovery_candidates),
                                blocking_reasons=list(child_normalized.blocking_reasons),
                            ),
                        )
                        result.skipped_count += 1
                    continue

                write_jsonl_entry(
                    child_handle,
                    {
                        "row": row_num,
                        "data": dict(child_normalized.data),
                        "original": dict(raw_row),
                        "entity_type": child_entity,
                        "root_anchor_keys": bundle_root_anchor_keys,
                    },
                )
                child_row_count += 1

            current_count = row_num
            now = time.monotonic()
            should_update_progress = current_count == total_rows
            if (current_count - last_progress_row) >= progress_step:
                should_update_progress = True
            if (now - last_progress_update) >= progress_interval:
                should_update_progress = True
            if should_update_progress:
                parse_progress = (
                    0 if total_rows <= 0 else min(40, int((current_count / total_rows) * 40))
                )
                persist_job_progress(
                    write_session=None,
                    job=job,
                    rows_total=total_rows,
                    rows_processed=current_count,
                    rows_created=0,
                    rows_updated=0,
                    rows_skipped=result.skipped_count,
                    rows_review=len(review_rows),
                    current_chunk=min(
                        parse_chunks_total,
                        max(0, math.ceil(current_count / max(1, current_batch_size))),
                    ),
                    chunks_total=parse_chunks_total,
                    phase="classifying",
                    bundle_mode="same_side_bundle",
                    progress=parse_progress,
                    review_overflow_count_value=review_overflow_count(review_rows),
                )
                last_progress_update = now
                last_progress_row = current_count

    merge_dead_letter_summary(result, record_dead_letter_rows(dead_letter_rows))

    total_chunks = (
        max(1, math.ceil(root_row_count / max(1, current_batch_size))) if root_row_count else 0
    ) + (max(1, math.ceil(child_row_count / max(1, current_batch_size))) if child_row_count else 0)
    return PreparedImportArtifact(
        bundle_mode="same_side_bundle",
        total_rows=total_rows,
        current_batch_size=current_batch_size,
        chunks_total=total_chunks,
        temp_path=temp_path,
        spool_dir=spool_dir,
        root_entries_path=root_entries_path,
        child_entries_path=child_entries_path,
        topology_side=topology_side,
        root_entity=root_entity,
        child_entity=child_entity,
        root_row_count=root_row_count,
        child_row_count=child_row_count,
    )


__all__ = ["prepare_same_side_bundle_import"]
