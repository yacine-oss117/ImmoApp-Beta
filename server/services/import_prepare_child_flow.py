"""Child-only prepare flow."""

from __future__ import annotations

import math
import tempfile
import time
from pathlib import Path
from typing import Any

from core.importer.normalize_pipeline import NormalizationPipeline
from core.utils.memory_guard import adaptive_chunk_size
from server.imports.models import ImportDeadLetterRow, ImportJob
from server.services.import_dead_letter import record_dead_letter_rows
from server.services.import_execution_governor import profile_aware_chunk_ceiling
from server.services.import_mapping import build_column_types, merge_row_corrections
from server.services.import_parsers import parser_for_file_type
from server.services.import_prepare_common import (
    DownloadToTemp,
    agency_memory,
    append_prepare_dead_letter,
    merge_dead_letter_summary,
    normalized_review_fields_or_validation,
    selected_sheet_name,
)
from server.services.import_price_dialect import build_field_price_metadata
from server.services.import_progress_runtime import persist_job_progress
from server.services.import_recovery import apply_row_recovery
from server.services.import_review_row_runtime import manual_review_row
from server.services.import_review_runtime import (
    append_review_row_limited,
    review_overflow_count,
)
from server.services.import_runtime_artifacts import write_jsonl_entry
from server.services.import_types import ImportResult, PreparedImportArtifact, ReviewRows
from server.services.storage import download_to_temp


def prepare_child_only_import(
    *,
    job: ImportJob,
    entity_type: str,
    skip_rows: int,
    skip_review_rows: bool,
    corrections: dict[str, dict[str, Any]] | None,
    review_rows: ReviewRows,
    result: ImportResult,
    download_to_temp_fn: DownloadToTemp = download_to_temp,
) -> PreparedImportArtifact:
    total_rows = int((job.result_summary or {}).get("row_count") or 0)
    topology_side = "client_side" if entity_type == "demande" else "listing_side"
    column_types = build_column_types(
        detected_columns=job.detected_columns or [],
        column_mapping=job.column_mapping or {},
    )
    agency_memory_value = agency_memory(job, column_types)
    field_price_metadata = build_field_price_metadata(
        agency_id=int(getattr(job, "agency_id", 0) or 0),
        column_mapping=dict(job.column_mapping or {}),
        inference_summary=dict(job.inference_summary or {}),
    )
    pipeline = NormalizationPipeline(
        entity_type=entity_type,
        column_types=column_types,
        field_metadata=field_price_metadata,
    )
    parser: Any = parser_for_file_type(
        job.file_type,
        skip_rows=skip_rows,
        sheet_name=selected_sheet_name(job),
    )
    temp_path = download_to_temp_fn(job.source_path, suffix=Path(job.filename).suffix)
    spool_dir = Path(tempfile.mkdtemp(prefix="immoapp-import-child-"))
    prepared_entries_path = spool_dir / "prepared_child_entries.jsonl"
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
            mapped_row = {
                field_name: raw_row[header_name]
                for field_name, header_name in (job.column_mapping or {}).items()
                if header_name in raw_row
            }
            normalized = pipeline.normalize_row(mapped_row)
            normalized = apply_row_recovery(
                normalized=normalized,
                raw_row=mapped_row,
                entity_type=entity_type,
                column_types=column_types,
                memory=agency_memory_value,
                deferred_required_fields=(
                    {"client_id"} if entity_type == "demande" else {"listing_id"}
                ),
            )
            if normalized.needs_review:
                if skip_review_rows:
                    result.errors.append({"row": row_num, "errors": list(normalized.remarks)})
                    result.error_count += 1
                    append_prepare_dead_letter(
                        rows=dead_letter_rows,
                        job=job,
                        row_num=row_num,
                        entity_type=entity_type,
                        topology_side=topology_side,
                        raw_row=dict(raw_row),
                        normalized_data=dict(normalized.data),
                        recoverability_class=str(normalized.recoverability_class),
                        recovered_fields=list(normalized.recovered_fields),
                        recovery_candidates=list(normalized.recovery_candidates),
                        blocking_reasons=list(normalized.blocking_reasons),
                        disposition=ImportDeadLetterRow.Disposition.BLOCKING_DISCARDED,
                        reason_codes=["prepare_review_blocked"],
                        reason_messages=list(
                            normalized.remarks or ["Review required during prepare."]
                        ),
                    )
                else:
                    append_review_row_limited(
                        review_rows,
                        manual_review_row(
                            row_num=row_num,
                            row_data=dict(normalized.data),
                            original=dict(raw_row),
                            entity_type=entity_type,
                            topology_side=topology_side,
                            review_fields=normalized_review_fields_or_validation(normalized),
                            remarks=list(normalized.remarks or ["Review required"]),
                            recoverability_class=str(normalized.recoverability_class),
                            recovered_fields=list(normalized.recovered_fields),
                            recovery_candidates=list(normalized.recovery_candidates),
                            blocking_reasons=list(normalized.blocking_reasons),
                        ),
                    )
                    result.skipped_count += 1
                continue

            write_jsonl_entry(
                prepared_handle,
                {
                    "row": row_num,
                    "data": dict(normalized.data),
                    "original": dict(raw_row),
                },
            )

            current_count = row_num
            now = time.monotonic()
            should_update_progress = current_count == total_rows
            if (current_count - last_progress_row) >= progress_step:
                should_update_progress = True
            if (now - last_progress_update) >= progress_interval:
                should_update_progress = True
            if should_update_progress:
                normalize_progress = (
                    0 if total_rows <= 0 else min(35, int((current_count / total_rows) * 35))
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
                        chunks_total,
                        max(0, math.ceil(current_count / max(1, current_batch_size))),
                    ),
                    chunks_total=chunks_total,
                    phase="normalizing",
                    bundle_mode="single_entity",
                    progress=normalize_progress,
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
        topology_side=topology_side,
    )


__all__ = ["prepare_child_only_import"]
