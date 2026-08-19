"""Durable dead-letter history for skipped/discarded importer rows."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any, Mapping

from core.data import import_learning_repository
from server.imports.models import ImportDeadLetterRow, ImportJob


def _list_of_str(values: object) -> list[str]:
    if not isinstance(values, list):
        return []
    return [str(value) for value in values if str(value or "").strip()]


def _list_of_dict(values: object) -> list[dict[str, Any]]:
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes, bytearray)):
        return []
    result: list[dict[str, Any]] = []
    for value in values:
        if isinstance(value, Mapping):
            result.append(dict(value))
    return result


def build_dead_letter_row(
    *,
    job: ImportJob | None = None,
    job_id: object | None = None,
    agency_id: int | None = None,
    row_ordinal: int,
    disposition: str,
    phase: str,
    actor_id: int | None = None,
    entity_type: str = "",
    topology_side: str = "",
    raw_data: Mapping[str, Any] | None = None,
    normalized_data: Mapping[str, Any] | None = None,
    recoverability_class: str = "",
    recovered_fields: object = None,
    recovery_candidates: object = None,
    blocking_reasons: object = None,
    reason_codes: object = None,
    reason_messages: object = None,
) -> ImportDeadLetterRow:
    resolved_job_id = getattr(job, "id", None) if job is not None else job_id
    resolved_agency_id = (
        int(getattr(job, "agency_id", 0) or 0) if job is not None else int(agency_id or 0)
    )
    return ImportDeadLetterRow(
        job_id=resolved_job_id,
        agency_id=resolved_agency_id,
        actor_id=actor_id,
        row_ordinal=int(row_ordinal),
        entity_type=str(entity_type or ""),
        topology_side=str(topology_side or ""),
        disposition=str(disposition),
        phase=str(phase or ""),
        reason_codes=_list_of_str(reason_codes),
        reason_messages=_list_of_str(reason_messages),
        raw_data=dict(raw_data or {}),
        normalized_data=dict(normalized_data or {}),
        recoverability_class=str(recoverability_class or ""),
        recovered_fields=_list_of_dict(recovered_fields),
        recovery_candidates=_list_of_dict(recovery_candidates),
        blocking_reasons=_list_of_str(blocking_reasons),
    )


def record_dead_letter_rows(rows: Iterable[ImportDeadLetterRow]) -> dict[str, int]:
    row_list = list(rows)
    import_learning_repository.bulk_create_dead_letter_rows(row_list)
    summary = {
        "auto_skipped": 0,
        "human_skipped": 0,
        "blocking_discarded": 0,
    }
    for row in row_list:
        if row.disposition in summary:
            summary[row.disposition] += 1
    return summary


__all__ = ["build_dead_letter_row", "record_dead_letter_rows"]
