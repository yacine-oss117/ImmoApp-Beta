"""Single-entity prepare flow."""

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
    agency_memory,
    append_prepare_dead_letter,
    duplicate_root_conflict_fields,
    merge_dead_letter_summary,
    normalized_review_fields_or_validation,
    selected_sheet_name,
)
from server.services.import_price_dialect import build_field_price_metadata
from server.services.import_progress_runtime import persist_job_progress
from server.services.import_recovery import apply_row_recovery
from server.services.import_review_policy import REVIEW_AMBIGUOUS
from server.services.import_review_row_runtime import manual_review_row
from server.services.import_review_runtime import (
    append_review_row_limited,
    review_overflow_count,
)
from server.services.import_root_key_index import remember_root_key
from server.services.import_rows import validate_row
from server.services.import_runtime_artifacts import write_jsonl_entry
from server.services.import_types import (
    ImportResult,
    PreparedImportArtifact,
    ReviewFieldPayload,
    ReviewRows,
)
from server.services.storage import download_to_temp


def _single_entity_topology_side(entity_type: str) -> str:
    return "client_side" if entity_type == "client" else "listing_side"


def _append_single_entity_review_row(
    *,
    review_rows: ReviewRows,
    row_num: int,
    raw_row: dict[str, Any],
    normalized: Any,
    entity_type: str,
    review_fields: list[ReviewFieldPayload] | None = None,
    remarks: list[str] | None = None,
    suggested_action: str = "",
    suggested_reasons: list[str] | None = None,
) -> None:
    append_review_row_limited(
        review_rows,
        manual_review_row(
            row_num=row_num,
            row_data=dict(normalized.data),
            original=dict(raw_row),
            entity_type=entity_type,
            topology_side=_single_entity_topology_side(entity_type),
            review_fields=review_fields or normalized_review_fields_or_validation(normalized),
            remarks=list(remarks if remarks is not None else normalized.remarks),
            suggested_action=suggested_action,
            suggested_reasons=list(suggested_reasons or []),
            recoverability_class=str(normalized.recoverability_class),
            recovered_fields=list(normalized.recovered_fields),
            recovery_candidates=list(normalized.recovery_candidates),
            blocking_reasons=list(normalized.blocking_reasons),
        ),
    )


def _handle_initial_review_requirement(
    *,
    normalized: Any,
    skip_review_rows: bool,
    review_rows: ReviewRows,
    result: ImportResult,
    row_num: int,
    raw_row: dict[str, Any],
    entity_type: str,
) -> bool:
    """Handle review requirements raised before any file-local dedup or duplicate policy logic."""
    if not normalized.needs_review or skip_review_rows:
        return False
    _append_single_entity_review_row(
        review_rows=review_rows,
        row_num=row_num,
        raw_row=raw_row,
        normalized=normalized,
        entity_type=entity_type,
    )
    result.skipped_count += 1
    return True


def _handle_post_dedup_review_requirement(
    *,
    normalized: Any,
    skip_review_rows: bool,
    review_rows: ReviewRows,
    result: ImportResult,
    row_num: int,
    raw_row: dict[str, Any],
    entity_type: str,
    job: ImportJob,
    dead_letter_rows: list[ImportDeadLetterRow],
) -> bool:
    """Handle review requirements that remain after dedup and duplicate policy evaluation."""
    if not normalized.needs_review:
        return False
    if not skip_review_rows:
        _append_single_entity_review_row(
            review_rows=review_rows,
            row_num=row_num,
            raw_row=raw_row,
            normalized=normalized,
            entity_type=entity_type,
        )
        result.skipped_count += 1
        return True
    result.errors.append(
        {
            "row": row_num,
            "errors": list(normalized.remarks or ["Review required during prepare."]),
        }
    )
    result.error_count += 1
    append_prepare_dead_letter(
        rows=dead_letter_rows,
        job=job,
        row_num=row_num,
        entity_type=entity_type,
        topology_side=_single_entity_topology_side(entity_type),
        raw_row=dict(raw_row),
        normalized_data=dict(normalized.data),
        recoverability_class=str(normalized.recoverability_class),
        recovered_fields=list(normalized.recovered_fields),
        recovery_candidates=list(normalized.recovery_candidates),
        blocking_reasons=list(normalized.blocking_reasons),
        disposition=ImportDeadLetterRow.Disposition.BLOCKING_DISCARDED,
        reason_codes=["prepare_review_blocked"],
        reason_messages=list(normalized.remarks or ["Review required during prepare."]),
    )
    return True


def prepare_single_entity_import(
    *,
    job: ImportJob,
    user_id: int,
    entity_type: str,
    skip_rows: int,
    skip_review_rows: bool,
    duplicate_strategy: str,
    corrections: dict[str, dict[str, Any]] | None,
    review_rows: ReviewRows,
    result: ImportResult,
    download_to_temp_fn: DownloadToTemp = download_to_temp,
) -> PreparedImportArtifact:
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
    pipeline = NormalizationPipeline(
        entity_type=entity_type,
        column_types=column_types,
        field_metadata=field_price_metadata,
    )
    phone_dedup_enabled = entity_type in {"client", "listing"}
    seen_root_keys: dict[str, int] = {}
    seen_root_contexts: dict[str, dict[str, Any]] = {}
    parser: Any = parser_for_file_type(
        job.file_type,
        skip_rows=skip_rows,
        sheet_name=selected_sheet_name(job),
    )
    temp_path = download_to_temp_fn(job.source_path, suffix=Path(job.filename).suffix)
    spool_dir = Path(tempfile.mkdtemp(prefix="immoapp-import-root-"))
    prepared_entries_path = spool_dir / "prepared_root_entries.jsonl"
    total_rows = int(job.result_summary.get("row_count", 0) or 0)
    min_batch = 50
    max_batch = 3000
    current_batch_size = adaptive_chunk_size(
        floor=min_batch,
        ceiling=profile_aware_chunk_ceiling(max_batch),
    )
    chunks_total = max(1, math.ceil(total_rows / max(1, current_batch_size))) if total_rows else 0
    last_progress_update = 0.0
    last_progress_row = 0
    progress_step = 100
    progress_interval = 1.0
    dead_letter_rows: list[ImportDeadLetterRow] = []

    with prepared_entries_path.open("w", encoding="utf-8") as prepared_handle:
        for i, raw_row in enumerate(parser.iter_dicts(temp_path)):
            row_num = i + 1
            raw_row = merge_row_corrections(
                raw_row=raw_row,
                row_index=row_num,
                corrections=corrections,
            )

            mapped_row: dict[str, Any] = {}
            for field_name, header_name in column_mapping.items():
                if header_name in raw_row:
                    mapped_row[field_name] = raw_row[header_name]

            normalized = pipeline.normalize_row(mapped_row)
            normalized = apply_row_recovery(
                normalized=normalized,
                raw_row=mapped_row,
                entity_type=entity_type,
                column_types=column_types,
                memory=agency_memory_value,
            )
            if _handle_initial_review_requirement(
                normalized=normalized,
                skip_review_rows=skip_review_rows,
                review_rows=review_rows,
                result=result,
                row_num=row_num,
                raw_row=dict(raw_row),
                entity_type=entity_type,
            ):
                continue

            if phone_dedup_enabled and duplicate_strategy != DUPLICATE_STRATEGY_ALLOW_ALL:
                decision = remember_root_key(
                    seen_keys=seen_root_keys,
                    row_data=normalized.data,
                    row_num=row_num,
                )
                if decision.is_duplicate:
                    base_remark = f"Duplicate phone in this file; first matching row is {decision.winner_row}."
                    winner_context = seen_root_contexts.get(str(decision.key or ""), {})
                    conflict_fields = duplicate_root_conflict_fields(
                        winner_context,
                        dict(normalized.data),
                    )
                    if conflict_fields:
                        remark = (
                            f"{base_remark} Conflicting root fields: "
                            f"{', '.join(conflict_fields)}."
                        )
                        if duplicate_strategy == DUPLICATE_STRATEGY_REVIEW and not skip_review_rows:
                            _append_single_entity_review_row(
                                review_rows=review_rows,
                                row_num=row_num,
                                raw_row=dict(raw_row),
                                normalized=normalized,
                                entity_type=entity_type,
                                review_fields=[
                                    cast(
                                        ReviewFieldPayload,
                                        {
                                            "field": "phone",
                                            "original": str(normalized.data.get("phone", "") or ""),
                                            "normalized": decision.key,
                                            "confidence": 1.0,
                                            "remark": remark,
                                        },
                                    )
                                ],
                                remarks=[remark],
                                suggested_action=REVIEW_AMBIGUOUS,
                                suggested_reasons=[remark],
                            )
                            result.skipped_count += 1
                        else:
                            result.errors.append({"row": row_num, "errors": [remark]})
                            result.error_count += 1
                            append_prepare_dead_letter(
                                rows=dead_letter_rows,
                                job=job,
                                row_num=row_num,
                                entity_type=entity_type,
                                topology_side=(
                                    "client_side" if entity_type == "client" else "listing_side"
                                ),
                                raw_row=dict(raw_row),
                                normalized_data=dict(normalized.data),
                                recoverability_class=str(normalized.recoverability_class),
                                recovered_fields=list(normalized.recovered_fields),
                                recovery_candidates=list(normalized.recovery_candidates),
                                blocking_reasons=list(normalized.blocking_reasons),
                                disposition=ImportDeadLetterRow.Disposition.BLOCKING_DISCARDED,
                                reason_codes=["prepare_duplicate_root_conflict"],
                                reason_messages=[remark],
                            )
                    else:
                        remark = (
                            f"Repeated contact grouped under first matching row "
                            f"{decision.winner_row}."
                        )
                        append_prepare_dead_letter(
                            rows=dead_letter_rows,
                            job=job,
                            row_num=row_num,
                            entity_type=entity_type,
                            topology_side=(
                                "client_side" if entity_type == "client" else "listing_side"
                            ),
                            raw_row=dict(raw_row),
                            normalized_data=dict(normalized.data),
                            recoverability_class=str(normalized.recoverability_class),
                            recovered_fields=list(normalized.recovered_fields),
                            recovery_candidates=list(normalized.recovery_candidates),
                            blocking_reasons=list(normalized.blocking_reasons),
                            disposition=ImportDeadLetterRow.Disposition.AUTO_SKIPPED,
                            reason_codes=["prepare_duplicate_root_key"],
                            reason_messages=[remark],
                        )
                        result.skipped_count += 1
                    continue
                if decision.key:
                    seen_root_contexts[str(decision.key)] = dict(normalized.data)

            if _handle_post_dedup_review_requirement(
                normalized=normalized,
                skip_review_rows=skip_review_rows,
                review_rows=review_rows,
                result=result,
                row_num=row_num,
                raw_row=dict(raw_row),
                entity_type=entity_type,
                job=job,
                dead_letter_rows=dead_letter_rows,
            ):
                continue

            validated_row, row_errors = validate_row(normalized.data, entity_type)
            if row_errors:
                if not skip_review_rows:
                    append_review_row_limited(
                        review_rows,
                        manual_review_row(
                            row_num=row_num,
                            row_data=dict(normalized.data),
                            original=dict(raw_row),
                            entity_type=entity_type,
                            topology_side=(
                                "client_side" if entity_type == "client" else "listing_side"
                            ),
                            review_fields=[
                                cast(
                                    ReviewFieldPayload,
                                    {
                                        "field": "validation",
                                        "original": "",
                                        "normalized": "",
                                        "confidence": 0.0,
                                        "remark": "; ".join(row_errors),
                                    },
                                )
                            ],
                            remarks=row_errors,
                            recoverability_class=str(normalized.recoverability_class),
                            recovered_fields=list(normalized.recovered_fields),
                            recovery_candidates=list(normalized.recovery_candidates),
                            blocking_reasons=list(normalized.blocking_reasons),
                        ),
                    )
                    result.skipped_count += 1
                    continue
                result.errors.append({"row": row_num, "errors": row_errors})
                result.error_count += 1
                append_prepare_dead_letter(
                    rows=dead_letter_rows,
                    job=job,
                    row_num=row_num,
                    entity_type=entity_type,
                    topology_side=("client_side" if entity_type == "client" else "listing_side"),
                    raw_row=dict(raw_row),
                    normalized_data=dict(normalized.data),
                    recoverability_class=str(normalized.recoverability_class),
                    recovered_fields=list(normalized.recovered_fields),
                    recovery_candidates=list(normalized.recovery_candidates),
                    blocking_reasons=list(normalized.blocking_reasons),
                    disposition=ImportDeadLetterRow.Disposition.BLOCKING_DISCARDED,
                    reason_codes=["prepare_validation_failed"],
                    reason_messages=list(row_errors),
                )
                continue

            validated_row["created_by_id"] = user_id
            write_jsonl_entry(
                prepared_handle,
                {
                    "row": row_num,
                    "data": validated_row,
                    "original": dict(raw_row),
                },
            )

            current_count = row_num
            now = time.monotonic()
            should_update_progress = total_rows > 0 and current_count == total_rows
            if (current_count - last_progress_row) >= progress_step:
                should_update_progress = True
            if (now - last_progress_update) >= progress_interval:
                should_update_progress = True
            if should_update_progress:
                progress = 0 if total_rows <= 0 else min(35, int((current_count / total_rows) * 35))
                persist_job_progress(
                    write_session=None,
                    job=job,
                    rows_total=total_rows,
                    rows_processed=current_count,
                    rows_created=0,
                    rows_updated=0,
                    rows_skipped=result.skipped_count,
                    rows_review=len(review_rows),
                    current_chunk=max(0, math.ceil(current_count / max(1, current_batch_size))),
                    chunks_total=chunks_total,
                    phase="normalizing",
                    bundle_mode="single_entity",
                    progress=progress,
                    review_overflow_count_value=review_overflow_count(review_rows),
                )
                last_progress_update = now
                last_progress_row = current_count

    merge_dead_letter_summary(result, record_dead_letter_rows(dead_letter_rows))

    return PreparedImportArtifact(
        bundle_mode="single_entity",
        total_rows=total_rows,
        current_batch_size=current_batch_size,
        chunks_total=chunks_total,
        temp_path=temp_path,
        spool_dir=spool_dir,
        prepared_entries_path=prepared_entries_path,
        entity_type=entity_type,
    )


__all__ = ["prepare_single_entity_import"]
