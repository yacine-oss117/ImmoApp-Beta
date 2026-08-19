"""Import preview endpoint."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from rest_framework import status
from rest_framework.decorators import permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from core.importer.normalize_pipeline import NormalizationPipeline
from core.importer.security import import_security_limits
from server.api.api_view import api_view
from server.api.import_helpers import get_parser_for_file
from server.api.request_schemas import ImportPreviewSerializer
from server.api.route_registry import route
from server.api.validation import validate_payload
from server.api.view_helpers import error, safe_error_message, safe_forbidden_message
from server.immoapp_server.business_metrics_imports import record_import_status_signal
from server.imports.models import ImportJob
from server.services.import_agency_memory import (
    alias_domain_for_column_type,
    load_agency_alias_memory,
)
from server.services.import_decision import build_import_decision
from server.services.import_mapping import build_column_types, canonicalize_column_mapping
from server.services.import_mapping_palette import derive_mapping_palette
from server.services.import_parsers import normalize_import_entity_type
from server.services.import_price_dialect import build_field_price_metadata
from server.services.import_recoverability import recoverability_summary
from server.services.import_recovery import apply_row_recovery
from server.services.import_service import ImportPermissionError, ImportService
from server.services.import_type_inference import (
    infer_row_entity,
    unsupported_child_only_import_message,
)
from server.services.import_ui_summary import (
    accumulate_preview_summary_row,
    empty_attention_summary,
    empty_auto_fix_summary,
    empty_entity_counts,
)
from server.services.storage import StorageError, download_to_temp

logger = logging.getLogger(__name__)


def _optional_int(value: object) -> int | None:
    return value if isinstance(value, int) else None


def _normalize_column_mapping(value: object, fallback: object) -> dict[str, str]:
    candidates = [value, fallback, {}]
    for candidate in candidates:
        if isinstance(candidate, dict):
            return {str(key): str(item) for key, item in candidate.items()}
    return {}


def _preview_deferred_required_fields(
    *,
    bundle_mode: str,
    topology_side_hint: str,
    row_entity_type: str,
) -> set[str] | None:
    if bundle_mode != "same_side_bundle":
        return None
    if topology_side_hint == "client_side" and row_entity_type == "demande":
        return {"client_id"}
    if topology_side_hint == "listing_side" and row_entity_type == "offer":
        return {"listing_id"}
    return None


@route("import/preview/", order=130)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def import_preview(request: Request) -> Response:
    """Preview normalized data with column mapping."""
    try:
        service = ImportService(request.user)
    except ImportPermissionError as e:
        return error(safe_forbidden_message(e), status.HTTP_403_FORBIDDEN)

    payload, error_response = validate_payload(
        request.data if isinstance(request.data, dict) else {},
        ImportPreviewSerializer,
        partial=False,
    )
    if error_response:
        return error_response
    data = payload or {}
    session_id = data.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        return error("session_id required", status.HTTP_400_BAD_REQUEST)

    session = service.get_job(session_id)
    if not session:
        return error("Session not found or expired", status.HTTP_404_NOT_FOUND)

    if session.status not in {ImportJob.Status.READY, ImportJob.Status.COMPLETED}:
        if session.status == ImportJob.Status.PARSING:
            return error("Import is still parsing", status.HTTP_409_CONFLICT)
        return error("Import is not ready", status.HTTP_409_CONFLICT)

    inference_summary = dict(session.inference_summary or {})
    final_inference = dict(inference_summary.get("final_inference", {}) or {})
    column_mapping = canonicalize_column_mapping(
        column_mapping=_normalize_column_mapping(
            data.get("column_mapping"), session.column_mapping
        ),
        detected_columns=session.detected_columns or [],
        final_inference=final_inference,
    )
    skip_rows = _optional_int(data.get("skip_rows")) or 0
    limit = _optional_int(data.get("limit")) or import_security_limits().preview_limit_default
    selected_sheet_name = str(inference_summary.get("selected_sheet_name", "") or "")
    sheet_profiles = list(inference_summary.get("sheet_profiles", []) or [])
    column_semantic_profiles = list(inference_summary.get("column_semantic_profiles", []) or [])
    agency_profile_hints_used = dict(inference_summary.get("agency_profile_hints_used", {}) or {})
    entity_type_raw = data.get("entity_type")
    entity_type = normalize_import_entity_type(
        entity_type_raw
        if isinstance(entity_type_raw, str)
        else session.detected_entity or str(final_inference.get("detected_entity") or "")
    )
    unsupported_message = unsupported_child_only_import_message(
        {
            **final_inference,
            "detected_entity": final_inference.get("detected_entity") or entity_type,
        }
    )
    if unsupported_message:
        return error(unsupported_message, status.HTTP_409_CONFLICT)
    column_types = build_column_types(
        detected_columns=session.detected_columns or [],
        column_mapping=column_mapping,
    )
    field_price_metadata = build_field_price_metadata(
        agency_id=int(service.agency_id or 0),
        column_mapping=column_mapping,
        inference_summary=inference_summary,
    )
    agency_memory = load_agency_alias_memory(
        int(service.agency_id or 0),
        domains={
            domain
            for domain in (
                alias_domain_for_column_type(column_type) for column_type in column_types.values()
            )
            if domain
        },
    )

    if not session.source_path:
        return error("Stored file not found", status.HTTP_404_NOT_FOUND)

    parser_entry = get_parser_for_file(
        session.filename,
        sheet_name=selected_sheet_name or None,
    )
    if not parser_entry:
        return error("Unsupported file type", status.HTTP_400_BAD_REQUEST)

    parser, _ = parser_entry
    if hasattr(parser, "skip_rows"):
        parser.skip_rows = skip_rows

    preview_rows: list[dict[str, Any]] = []
    stats = {"valid": 0, "needs_review": 0, "duplicates": 0}
    normalization_summary = {
        "rows_total": int((session.result_summary or {}).get("row_count", 0) or 0),
        "rows_clean": 0,
        "rows_need_review": 0,
        "rows_invalid": 0,
    }
    preview_recoverability = recoverability_summary([])
    preview_entity_counts = empty_entity_counts()
    preview_auto_fix_summary = empty_auto_fix_summary()
    preview_attention_summary = empty_attention_summary()
    bundle_mode = str(final_inference.get("bundle_mode", "single_entity") or "single_entity")
    grouped_related_rows = 0
    seen_bundle_root_keys: set[str] = set()

    temp_path: Path | None = None
    try:
        temp_path = download_to_temp(session.source_path, suffix=Path(session.filename).suffix)
        it = parser.iter_dicts(temp_path)
        for i, raw_row in enumerate(it):
            row_num = i + 1

            original: dict[str, Any] = raw_row.copy()
            if column_mapping:
                mapped_row = {
                    field_name: raw_row[header_name]
                    for field_name, header_name in column_mapping.items()
                    if header_name in raw_row
                }
            else:
                mapped_row = original

            topology_side_hint = str(
                final_inference.get("topology_side_hint", "unknown") or "unknown"
            )
            row_inference = infer_row_entity(
                mapped_row,
                bundle_mode=bundle_mode,
                default_entity_type=entity_type,
                topology_side_hint=topology_side_hint,
            )
            row_entity_type = normalize_import_entity_type(row_inference.entity_type or entity_type)
            pipeline = NormalizationPipeline(
                entity_type=row_entity_type,
                column_types=column_types,
                field_metadata=field_price_metadata,
            )
            normalized = pipeline.normalize_row(mapped_row)
            normalized = apply_row_recovery(
                normalized=normalized,
                raw_row=mapped_row,
                entity_type=row_entity_type,
                column_types=column_types,
                memory=agency_memory,
                deferred_required_fields=_preview_deferred_required_fields(
                    bundle_mode=bundle_mode,
                    topology_side_hint=topology_side_hint,
                    row_entity_type=row_entity_type,
                ),
            )
            validated_row, row_errors = service.validate_row(normalized.data, row_entity_type)
            needs_review = normalized.needs_review or len(row_errors) > 0
            preview_row = {
                "row_num": row_num,
                "original": original,
                "normalized": validated_row,
                "entity_type": row_entity_type,
                "topology_side": row_inference.topology_side,
                "needs_review": needs_review,
                "errors": row_errors if needs_review else [],
                "review_fields": [
                    {
                        "field": rf.field_name,
                        "original": rf.original_value,
                        "normalized": rf.normalized_value,
                        "confidence": rf.confidence,
                        "remark": rf.remark,
                        "metadata": dict(rf.metadata or {}),
                    }
                    for rf in normalized.review_fields
                ],
                "remarks": normalized.remarks,
                "recoverability_class": normalized.recoverability_class,
                "recovered_fields": list(normalized.recovered_fields),
                "recovery_candidates": list(normalized.recovery_candidates),
                "blocking_reasons": list(normalized.blocking_reasons),
                "learning_signal_eligible": True,
                "duplicate_of": None,
            }
            grouped_related_rows += accumulate_preview_summary_row(
                preview_row,
                bundle_mode=bundle_mode,
                entity_counts=preview_entity_counts,
                auto_fix_summary=preview_auto_fix_summary,
                attention_summary=preview_attention_summary,
                seen_bundle_root_keys=seen_bundle_root_keys,
            )
            recoverability_key = str(
                preview_row.get("recoverability_class", "auto_recoverable") or "auto_recoverable"
            )
            preview_recoverability[recoverability_key] = (
                int(preview_recoverability.get(recoverability_key, 0) or 0) + 1
            )
            if len(preview_rows) < limit:
                preview_rows.append(preview_row)
            if needs_review:
                stats["needs_review"] += 1
                normalization_summary["rows_need_review"] += 1
                if row_errors:
                    normalization_summary["rows_invalid"] += 1
            else:
                stats["valid"] += 1
                normalization_summary["rows_clean"] += 1
    except (StorageError, ValueError) as exc:
        return error(safe_error_message(exc), status.HTTP_400_BAD_REQUEST)
    except OSError as exc:
        return error(safe_error_message(exc), status.HTTP_400_BAD_REQUEST)
    except Exception:
        logger.exception("Import preview failed")
        return error(
            "We couldn't check this file yet. Please try again.",
            status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
    finally:
        if temp_path:
            try:
                temp_path.unlink()
            except OSError:
                pass

    candidate_mappings = [
        {
            "header": str(col.get("header", "") or ""),
            "detected_type": str(col.get("detected_type", "unknown") or "unknown"),
            "suggested_mapping": str(col.get("detected_type", "unknown") or "unknown"),
            "confidence": float(col.get("confidence", 0.0) or 0.0),
        }
        for col in list(session.detected_columns or [])
    ]
    confidences: list[float] = []
    for item in candidate_mappings:
        confidence_raw = item.get("confidence")
        if isinstance(confidence_raw, (int, float)) and not isinstance(confidence_raw, bool):
            confidences.append(float(confidence_raw))
    mapping_confidence = round(sum(confidences) / len(confidences), 3) if confidences else 0.0
    decision = build_import_decision(
        final_inference=final_inference,
        detected_columns=session.detected_columns or [],
        column_mapping=column_mapping,
        detected_entity=entity_type,
        sheet_profiles=sheet_profiles,
        selected_sheet_name=selected_sheet_name,
        preview_rows=preview_rows,
        recoverability_summary=preview_recoverability,
        preview_attention_summary=preview_attention_summary,
    )
    mapping_palette = derive_mapping_palette(
        final_inference=final_inference,
        detected_columns=session.detected_columns or [],
        column_mapping=column_mapping,
        manual_mapping_required=decision.manual_mapping_required,
        detected_entity=entity_type,
        sheet_profiles=sheet_profiles,
        selected_sheet_name=selected_sheet_name,
    )
    mapping_palette_mode = str(decision.mapping_palette_mode or "entity_only")
    mapping_palette_reason = str(mapping_palette.get("mapping_palette_reason", "") or "")
    mapping_candidate_entities_raw = mapping_palette.get("mapping_candidate_entities", [])
    mapping_candidate_entities = (
        [str(value) for value in mapping_candidate_entities_raw]
        if isinstance(mapping_candidate_entities_raw, list)
        else []
    )
    if grouped_related_rows > 0:
        preview_auto_fix_summary["grouped_related_rows"] = grouped_related_rows
    stats["duplicates"] = int(preview_attention_summary.get("possible_duplicates", 0) or 0)
    session.inference_summary = {
        **dict(session.inference_summary or {}),
        "preview_normalization_summary": normalization_summary,
        "preview_recoverability_summary": preview_recoverability,
        "preview_entity_counts": preview_entity_counts,
        "preview_auto_fix_summary": preview_auto_fix_summary,
        "preview_attention_summary": preview_attention_summary,
        "manual_mapping_required": decision.manual_mapping_required,
        "manual_mapping_reasons": decision.manual_mapping_reasons,
        "manual_mapping_metrics": dict(decision.metrics or {}),
        "mapping_palette_mode": mapping_palette_mode,
        "mapping_palette_reason": mapping_palette_reason,
        "mapping_candidate_entities": mapping_candidate_entities,
        "import_decision": decision.as_dict(),
        "sheet_profiles": sheet_profiles,
        "column_semantic_profiles": column_semantic_profiles,
        "price_dialect_summary": dict(inference_summary.get("price_dialect_summary", {}) or {}),
        "price_dialect_profiles": list(inference_summary.get("price_dialect_profiles", []) or []),
        "agency_profile_hints_used": agency_profile_hints_used,
    }
    session.preview_rows = preview_rows
    session.column_mapping = column_mapping
    session.detected_entity = entity_type
    session.save(
        update_fields=[
            "preview_rows",
            "column_mapping",
            "detected_entity",
            "inference_summary",
            "updated_at",
        ]
    )
    record_import_status_signal(
        event="preview",
        mapping_palette_mode=mapping_palette_mode,
        manual_mapping_required=decision.manual_mapping_required,
        file_model_hint=str(final_inference.get("file_model_hint", "unknown") or "unknown"),
        dominant_side=str(final_inference.get("dominant_side", "unknown") or "unknown"),
        projection_conflict_count=len(
            list(final_inference.get("semantic_projection_conflicts", []) or [])
        ),
        row_outlier_review_count=int(final_inference.get("row_mixed_review_count", 0) or 0),
    )

    return Response(
        {
            "preview_rows": preview_rows,
            "stats": stats,
            "total_rows": (session.result_summary or {}).get("row_count", 0),
            "entity_type_hint": final_inference.get("entity_type_hint"),
            "entity_type_confidence": final_inference.get("confidence", 0.0),
            "topology_side_hint": final_inference.get("topology_side_hint"),
            "topology_confidence": final_inference.get("confidence", 0.0),
            "bundle_mode": final_inference.get("bundle_mode", "single_entity"),
            "file_model_hint": final_inference.get("file_model_hint", "unknown"),
            "dominant_side": final_inference.get("dominant_side", "unknown"),
            "dominant_side_confidence": final_inference.get("dominant_side_confidence", 0.0),
            "row_mixed_review_count": final_inference.get("row_mixed_review_count", 0),
            "semantic_projection_conflicts": list(
                final_inference.get("semantic_projection_conflicts", []) or []
            ),
            "inference_reasons": list(final_inference.get("reasons", []) or []),
            "ui_hint_used": bool(final_inference.get("ui_hint_used", False)),
            "candidate_mappings": candidate_mappings,
            "mapping_confidence": mapping_confidence,
            "mapping_palette_mode": mapping_palette_mode,
            "mapping_palette_reason": mapping_palette_reason,
            "mapping_candidate_entities": mapping_candidate_entities,
            "normalization_summary": normalization_summary,
            "manual_mapping_required": decision.manual_mapping_required,
            "manual_mapping_reasons": decision.manual_mapping_reasons,
            "recoverability_summary": preview_recoverability,
            "entity_counts": preview_entity_counts,
            "auto_fix_summary": preview_auto_fix_summary,
            "attention_summary": preview_attention_summary,
            "decision_outcome": decision.outcome,
            "decision_reason_codes": list(decision.reason_codes),
            "sheet_profiles": sheet_profiles,
            "column_semantic_profiles": column_semantic_profiles,
            "price_dialect_summary": dict(inference_summary.get("price_dialect_summary", {}) or {}),
            "agency_profile_hints_used": agency_profile_hints_used,
        }
    )
