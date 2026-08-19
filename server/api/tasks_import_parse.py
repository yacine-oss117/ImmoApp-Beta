"""Parse-time orchestration for import Celery tasks."""

from __future__ import annotations

from pathlib import Path

from core.importer.detection import EntityTypeDetector
from server.imports.models import ImportJob
from server.services import tenant_resource_governor
from server.services.import_agency_profile import load_agency_profile_hints
from server.services.import_column_semantics import (
    build_semantic_evidence_rows,
    detected_columns_with_semantics,
)
from server.services.import_mapping import (
    build_column_types,
    canonicalize_column_mapping,
    suggest_column_mapping,
)
from server.services.import_mapping_gate import evaluate_manual_mapping_gate
from server.services.import_parsers import normalize_import_entity_type
from server.services.import_price_dialect import build_price_dialect_profiles
from server.services.import_sheet_intelligence import (
    choose_dominant_sheet,
    profile_import_sheets,
)
from server.services.import_type_inference import (
    infer_file_type,
    unsupported_child_only_import_message,
)
from server.services.storage import StorageError, download_to_temp

from .tasks_core import logger, task_context
from .tasks_import_helpers import (
    get_import_parser,
    load_import_service,
    load_import_user,
    mark_import_failed,
)


def _semantic_inference_inputs(
    *,
    detected_columns: list[dict[str, object]],
    sample_rows: list[dict[str, object]],
) -> tuple[list[str], list[dict[str, object]]]:
    semantic_headers: list[str] = []
    column_pairs: list[tuple[str, str]] = []
    seen_headers: set[str] = set()
    for column in detected_columns:
        header = str(column.get("header", "") or "").strip()
        detected_type = str(column.get("detected_type", "") or "").strip().lower()
        if not header or not detected_type or detected_type == "unknown":
            continue
        column_pairs.append((header, detected_type))
        if detected_type not in seen_headers:
            semantic_headers.append(detected_type)
            seen_headers.add(detected_type)
    projected_rows: list[dict[str, object]] = []
    for row in sample_rows:
        projected: dict[str, object] = {}
        for header, detected_type in column_pairs:
            if header in row and row.get(header) not in {None, ""}:
                projected[detected_type] = row.get(header)
        projected_rows.append(projected)
    return semantic_headers, projected_rows


def _semantic_evidence_inputs(
    *,
    detected_columns: list[dict[str, object]],
    sample_rows: list[dict[str, object]],
) -> tuple[list[dict[str, object]], list[str]]:
    evidence_rows, projection_conflicts = build_semantic_evidence_rows(
        detected_columns=[dict(item) for item in detected_columns],
        sample_rows=[dict(row) for row in sample_rows],
    )
    return [row.as_dict() for row in evidence_rows], list(projection_conflicts)


def run_import_parse_task(
    *,
    session_id: str,
    user_id: int,
    agency_id: int | None = None,
    schema: str | None = None,
    correlation_id: str | None = None,
) -> dict[str, object]:
    user = load_import_user(user_id)
    with task_context(
        schema,
        agency_id,
        actor_id=getattr(user, "id", None) if user else None,
        actor_role=str(getattr(user, "role", "") or None) if user else None,
        actor_is_owner=bool(getattr(user, "is_owner", False)) if user else False,
        correlation_id=correlation_id,
    ):
        try:
            service = load_import_service(user_id)
            if service is None:
                return {"session_id": session_id, "status": "failed", "error": "Invalid user"}

            job = service.get_job(session_id)
            if not job:
                return {"session_id": session_id, "status": "missing"}

            job.status = ImportJob.Status.PARSING
            job.progress = 0
            job.error_message = None
            job.save()

            if not job.source_path:
                return mark_import_failed(service, job, "Missing source file path")

            parser_entry = get_import_parser(job.filename)
            if not parser_entry:
                return mark_import_failed(service, job, "Unsupported file type")
            parser, file_type = parser_entry

            temp_path: Path | None = None
            try:
                temp_path = download_to_temp(job.source_path, suffix=Path(job.filename).suffix)
                agency_profile_hints = load_agency_profile_hints(int(job.agency.pk or 0))
                sheet_profiles = profile_import_sheets(
                    path=temp_path,
                    file_type=file_type,
                    agency_profile_hints=agency_profile_hints,
                )
                selected_sheet_name = choose_dominant_sheet(sheet_profiles)
                if selected_sheet_name and hasattr(parser, "sheet_name"):
                    parser.sheet_name = selected_sheet_name
                parsed = parser.parse(temp_path)
            except StorageError:
                logger.warning(
                    "import_parse_task could not read stored source for job %s",
                    job.id,
                    exc_info=True,
                )
                return mark_import_failed(
                    service,
                    job,
                    "We couldn’t read this file yet. Please try again or choose another file.",
                )
            except Exception:
                logger.exception("import_parse_task failed while parsing job %s", job.id)
                return mark_import_failed(
                    service,
                    job,
                    "We couldn’t read this file yet. Please try again or choose another file.",
                )
            finally:
                if temp_path:
                    try:
                        temp_path.unlink()
                    except OSError:
                        pass

            if not parsed.headers:
                return mark_import_failed(service, job, "File contains no headers")

            headers = parsed.headers
            data_rows = parsed.rows

            detected_columns, agency_profile_hints = detected_columns_with_semantics(
                headers=headers,
                sample_rows=[dict(row) for row in data_rows[:50]],
                agency_id=int(job.agency.pk or 0),
            )
            column_semantic_profiles = [
                {
                    "header": str(col.get("header", "") or ""),
                    "detected_type": str(col.get("detected_type", "unknown") or "unknown"),
                    "detected_role": str(col.get("detected_role", "unknown") or "unknown"),
                    "side_prior": str(col.get("side_prior", "unknown") or "unknown"),
                    "confidence": float(col.get("confidence", 0.0) or 0.0),
                    "reasons": list(col.get("reasons") or []),
                    "semantic_signals": dict(col.get("semantic_signals") or {}),
                    "neighbor_hints": list(col.get("neighbor_hints") or []),
                }
                for col in detected_columns
            ]

            entity_detector = EntityTypeDetector()
            entity_result = entity_detector.detect(headers)
            semantic_headers, semantic_sample_rows = _semantic_inference_inputs(
                detected_columns=detected_columns,
                sample_rows=[dict(row) for row in data_rows[:25]],
            )
            semantic_evidence_rows, semantic_projection_conflicts = _semantic_evidence_inputs(
                detected_columns=detected_columns,
                sample_rows=[dict(row) for row in data_rows[:25]],
            )
            inference = infer_file_type(
                headers=semantic_headers or headers,
                sample_rows=semantic_evidence_rows
                or semantic_sample_rows
                or [dict(row) for row in data_rows[:25]],
                ui_hint=(
                    normalize_import_entity_type(job.ui_entity_hint) if job.ui_entity_hint else None
                ),
            )
            final_inference = dict(inference.get("final_inference", {}) or {})
            auto_inference = dict(inference.get("auto_inference", {}) or {})
            price_dialect_profiles, price_dialect_summary = build_price_dialect_profiles(
                detected_columns=detected_columns,
                sample_rows=[dict(row) for row in data_rows[:50]],
                final_inference=final_inference,
                agency_id=int(job.agency.pk or 0),
            )
            final_inference["selected_sheet_name"] = selected_sheet_name
            if semantic_projection_conflicts:
                final_inference["semantic_projection_conflicts"] = semantic_projection_conflicts
                auto_inference["semantic_projection_conflicts"] = semantic_projection_conflicts
            unsupported_message = unsupported_child_only_import_message(final_inference)
            final_inference["import_supported"] = not bool(unsupported_message)
            if unsupported_message:
                final_inference["blocking_code"] = "IMPORT_CHILD_ONLY_UNSUPPORTED"
                final_inference["blocking_message"] = unsupported_message
            inference["final_inference"] = final_inference
            final_entity = normalize_import_entity_type(
                final_inference.get("detected_entity")
                or auto_inference.get("detected_entity")
                or entity_result.entity_type
            )
            bundle_mode = str(
                final_inference.get("bundle_mode", "single_entity") or "single_entity"
            )
            column_mapping = canonicalize_column_mapping(
                column_mapping=suggest_column_mapping(
                    detected_columns=detected_columns,
                    final_inference=final_inference,
                ),
                detected_columns=detected_columns,
                final_inference=final_inference,
            )
            column_types = build_column_types(
                detected_columns=detected_columns,
                column_mapping=column_mapping,
            )
            (
                manual_mapping_required,
                manual_mapping_reasons,
                manual_mapping_metrics,
            ) = evaluate_manual_mapping_gate(
                detected_columns=detected_columns,
                final_inference=final_inference,
                column_types=column_types,
                sheet_profiles=sheet_profiles,
            )
            inference["manual_mapping_required"] = manual_mapping_required
            inference["manual_mapping_reasons"] = manual_mapping_reasons
            inference["manual_mapping_metrics"] = manual_mapping_metrics
            inference["column_semantic_profiles"] = column_semantic_profiles
            inference["price_dialect_profiles"] = price_dialect_profiles
            inference["price_dialect_summary"] = price_dialect_summary
            inference["sheet_profiles"] = sheet_profiles
            inference["agency_profile_hints_used"] = agency_profile_hints
            inference["selected_sheet_name"] = selected_sheet_name

            job.detected_columns = detected_columns
            job.detected_entity = final_entity if bundle_mode != "mixed_blocked" else None
            job.column_mapping = column_mapping
            job.preview_rows = [dict(r) for r in data_rows[:5]]
            job.status = ImportJob.Status.READY
            job.progress = 100
            job.stage = ImportJob.Stage.MAPPING
            job.inference_summary = inference
            job.progress_detail = {
                "rows_total": parsed.row_count,
                "rows_processed": 0,
                "rows_created": 0,
                "rows_updated": 0,
                "rows_skipped": 0,
                "rows_review": 0,
                "current_chunk": 0,
                "chunks_total": 0,
                "bundle_mode": bundle_mode,
                "phase": "mapping",
            }
            job.result_summary = {
                "row_count": parsed.row_count,
                "confidence": entity_result.confidence,
                "detected_entity_auto": entity_result.entity_type,
                "entity_type_hint": final_inference.get("entity_type_hint"),
                "topology_side_hint": final_inference.get("topology_side_hint"),
                "bundle_mode": bundle_mode,
                "manual_mapping_required": manual_mapping_required,
                "manual_mapping_reasons": manual_mapping_reasons,
                "manual_mapping_metrics": manual_mapping_metrics,
                "selected_sheet_name": selected_sheet_name,
                "import_supported": not bool(unsupported_message),
                "blocking_code": ("IMPORT_CHILD_ONLY_UNSUPPORTED" if unsupported_message else ""),
                "blocking_message": unsupported_message or "",
            }
            job.save()
            return {
                "session_id": str(job.id),
                "status": "ready",
                "rows": len(data_rows),
                "preview_rows": job.preview_rows,
                "file_type": file_type,
                "detected_entity": job.detected_entity,
                "detected_columns": job.detected_columns,
                "column_mapping": job.column_mapping,
                "row_count": parsed.row_count,
                "inference_summary": job.inference_summary,
                "progress_detail": job.progress_detail,
                "manual_mapping_required": manual_mapping_required,
                "manual_mapping_reasons": manual_mapping_reasons,
                "sheet_profiles": sheet_profiles,
                "column_semantic_profiles": column_semantic_profiles,
                "price_dialect_profiles": price_dialect_profiles,
                "price_dialect_summary": price_dialect_summary,
                "agency_profile_hints_used": agency_profile_hints,
            }
        finally:
            if agency_id:
                tenant_resource_governor.note_work_completed(
                    budget_name="import_parse",
                    agency_id=int(agency_id),
                )


__all__ = [
    "_semantic_evidence_inputs",
    "_semantic_inference_inputs",
    "run_import_parse_task",
]
