"""Shared load-policy helpers for direct and distributed importer loads."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable

from core.contracts.import_batch_refs import CreatedRowRef
from server.services.import_batch_write_refs import insert_batch_refs
from server.services.import_executor_helpers import insert_batch
from server.services.import_runtime_artifacts import entry_dict, entry_row_num, entry_str_list
from server.services.import_types import ImportLoadOutcome

_SOURCE_ORDINAL_KEY = "_source_ordinal"


@dataclass(frozen=True)
class TimedInsertResult:
    """Batch insert result with wall-clock DB time."""

    created_ids: list[int]
    db_duration: float


@dataclass(frozen=True)
class RootConflictIsolationResult:
    """Iterative unique-conflict isolation result for planned root loads."""

    created_rows: list[CreatedRowRef]
    skipped_count: int
    db_duration: float

    @property
    def created_ids(self) -> list[int]:
        return [int(row.created_id) for row in self.created_rows]


@dataclass(frozen=True)
class ChildAnchorClassification:
    """Load-time parent-anchor classification for planned child rows."""

    resolved_anchor_id: int
    kind: str
    user_error: str = ""
    internal_error: str = ""

    @property
    def is_resolved(self) -> bool:
        return self.kind == "resolved"


@dataclass(frozen=True)
class OrphanThresholdDecision:
    """Shared orphan-threshold evaluation used by direct and distributed loads."""

    orphan_count: int
    total_count: int
    orphan_ratio: float
    hard_fail: bool


@dataclass(frozen=True)
class ChildAnchorFailureRows:
    """User-facing and durable error rows for an unresolvable child anchor."""

    user_row_error: dict[str, Any]
    internal_row_error: dict[str, Any]


def exception_sqlstate(exc: Exception) -> str:
    sqlstate = str(getattr(exc, "sqlstate", "") or "").strip()
    if sqlstate:
        return sqlstate
    cause = getattr(exc, "__cause__", None)
    cause_sqlstate = str(getattr(cause, "sqlstate", "") or "").strip()
    if cause_sqlstate:
        return cause_sqlstate
    orig = getattr(exc, "orig", None)
    return str(getattr(orig, "sqlstate", "") or "").strip()


def is_unique_violation(exc: Exception) -> bool:
    return exception_sqlstate(exc) == "23505"


def _require_insert_cardinality(
    *,
    created_ids: list[int],
    expected_count: int,
    context: str,
) -> list[int]:
    normalized_ids = [int(value) for value in created_ids]
    if len(normalized_ids) != max(0, int(expected_count)):
        raise ValueError(
            f"{context} returned {len(normalized_ids)} ids for {int(expected_count)} input rows."
        )
    return normalized_ids


def _entry_source_ordinal(entry: dict[str, Any], fallback: int) -> int:
    raw_value = entry.get(_SOURCE_ORDINAL_KEY, fallback)
    if isinstance(raw_value, bool):
        return int(raw_value)
    if isinstance(raw_value, int):
        return raw_value
    if isinstance(raw_value, str):
        try:
            return int(raw_value)
        except ValueError:
            return int(fallback)
    return int(fallback)


def _batch_entry_source_ordinals(batch_entries: list[dict[str, Any]]) -> list[int]:
    return [_entry_source_ordinal(entry, index) for index, entry in enumerate(batch_entries)]


def _require_created_row_refs(
    *,
    created_rows: list[CreatedRowRef],
    expected_source_ordinals: list[int],
    context: str,
) -> list[CreatedRowRef]:
    normalized_rows = [
        CreatedRowRef(
            source_ordinal=int(row.source_ordinal),
            created_id=int(row.created_id),
        )
        for row in created_rows
    ]
    if len(normalized_rows) != len(expected_source_ordinals):
        raise ValueError(
            f"{context} returned {len(normalized_rows)} created-row refs for "
            f"{len(expected_source_ordinals)} input rows."
        )
    actual_ordinals = [row.source_ordinal for row in normalized_rows]
    if any(row.created_id <= 0 for row in normalized_rows):
        raise ValueError(f"{context} returned a non-positive created id.")
    if any(ordinal < 0 for ordinal in actual_ordinals):
        raise ValueError(f"{context} returned a negative source ordinal.")
    if len(set(actual_ordinals)) != len(actual_ordinals):
        raise ValueError(f"{context} returned duplicate source ordinals.")
    if len(set(expected_source_ordinals)) != len(expected_source_ordinals):
        raise ValueError(f"{context} expected unique source ordinals.")
    if set(actual_ordinals) != {int(value) for value in expected_source_ordinals}:
        raise ValueError(f"{context} returned source ordinals that did not match the input rows.")
    return sorted(normalized_rows, key=lambda row: row.source_ordinal)


def timed_insert_batch_rows(
    *,
    write_session: Any,
    entity_type: str,
    batch_rows: list[dict[str, Any]],
    load_outcome: ImportLoadOutcome,
    insert_batch_fn: Callable[..., list[int]] = insert_batch,
) -> TimedInsertResult:
    if not batch_rows:
        return TimedInsertResult(created_ids=[], db_duration=0.0)
    started_at = time.monotonic()
    batch_ids = insert_batch_fn(
        write_session=write_session,
        entity_type=entity_type,
        batch_rows=batch_rows,
        demande_ids=load_outcome.demande_ids,
        demande_client_ids=load_outcome.demande_client_ids,
        offer_ids=load_outcome.offer_ids,
        listing_wilaya_ids=load_outcome.listing_wilaya_ids,
    )
    return TimedInsertResult(
        created_ids=_require_insert_cardinality(
            created_ids=[int(value) for value in batch_ids],
            expected_count=len(batch_rows),
            context=f"{entity_type} batch insert",
        ),
        db_duration=time.monotonic() - started_at,
    )


def remember_created_anchor_keys(
    *,
    created_anchor_map: dict[str, int],
    batch_entries: list[dict[str, Any]],
    created_rows: list[CreatedRowRef],
) -> None:
    expected_source_ordinals = _batch_entry_source_ordinals(batch_entries)
    normalized_rows = _require_created_row_refs(
        created_rows=created_rows,
        expected_source_ordinals=expected_source_ordinals,
        context="Root anchor mapping",
    )
    entry_by_source_ordinal = {
        _entry_source_ordinal(entry, index): entry for index, entry in enumerate(batch_entries)
    }
    for created_row in normalized_rows:
        entry = entry_by_source_ordinal[int(created_row.source_ordinal)]
        for anchor_key in entry_str_list(entry, "anchor_keys"):
            created_anchor_map[anchor_key] = int(created_row.created_id)


def build_child_anchor_failure_rows(
    *,
    row_num: int,
    row_data: dict[str, Any],
    anchor_classification: ChildAnchorClassification,
) -> ChildAnchorFailureRows:
    return ChildAnchorFailureRows(
        user_row_error={
            "row": int(row_num),
            "errors": [str(anchor_classification.user_error or "")],
        },
        internal_row_error={
            "row": int(row_num),
            "errors": [str(anchor_classification.internal_error or "")],
            "data": dict(row_data),
        },
    )


def flush_root_entries_with_conflict_isolation(
    *,
    write_session: Any,
    entity_type: str,
    batch_entries: list[dict[str, Any]],
    load_outcome: ImportLoadOutcome,
    on_rows_inserted: Callable[[list[CreatedRowRef], list[dict[str, Any]]], None],
    append_leaf_error: Callable[[dict[str, Any]], None],
    insert_batch_fn: Callable[..., list[CreatedRowRef]] = insert_batch_refs,
) -> RootConflictIsolationResult:
    if not batch_entries:
        return RootConflictIsolationResult(created_rows=[], skipped_count=0, db_duration=0.0)

    indexed_batch_entries = [
        {**dict(entry), _SOURCE_ORDINAL_KEY: index} for index, entry in enumerate(batch_entries)
    ]
    worklist: list[list[dict[str, Any]]] = [indexed_batch_entries]
    created_rows: list[CreatedRowRef] = []
    skipped_count = 0
    total_db_duration = 0.0

    while worklist:
        current_batch = worklist.pop()
        started_at = time.monotonic()
        try:
            current_source_ordinals = _batch_entry_source_ordinals(current_batch)
            batch_rows = insert_batch_fn(
                write_session=write_session,
                entity_type=entity_type,
                batch_rows=[entry_dict(entry, "data") for entry in current_batch],
                source_ordinals=current_source_ordinals,
                demande_ids=load_outcome.demande_ids,
                demande_client_ids=load_outcome.demande_client_ids,
                offer_ids=load_outcome.offer_ids,
                listing_wilaya_ids=load_outcome.listing_wilaya_ids,
            )
            current_created_rows = _require_created_row_refs(
                created_rows=list(batch_rows),
                expected_source_ordinals=current_source_ordinals,
                context=f"{entity_type} root load insert",
            )
            on_rows_inserted(current_created_rows, current_batch)
            created_rows.extend(current_created_rows)
            total_db_duration += time.monotonic() - started_at
        except Exception as exc:
            attempt_duration = time.monotonic() - started_at
            total_db_duration += attempt_duration
            if not is_unique_violation(exc):
                raise
            if len(current_batch) <= 1:
                append_leaf_error(current_batch[0])
                skipped_count += 1
                continue
            split_index = max(1, len(current_batch) // 2)
            worklist.append(current_batch[split_index:])
            worklist.append(current_batch[:split_index])

    return RootConflictIsolationResult(
        created_rows=created_rows,
        skipped_count=skipped_count,
        db_duration=total_db_duration,
    )


def classify_child_anchor(
    *,
    original_anchor_id: int,
    resolved_anchor_id: int,
) -> ChildAnchorClassification:
    if resolved_anchor_id > 0:
        return ChildAnchorClassification(
            resolved_anchor_id=int(resolved_anchor_id),
            kind="resolved",
        )
    if original_anchor_id < 0:
        return ChildAnchorClassification(
            resolved_anchor_id=0,
            kind="ambiguous_parent",
            user_error="Planned child row had an ambiguous parent and was not anchored.",
            internal_error="A planned child row had an ambiguous parent and was not anchored.",
        )
    return ChildAnchorClassification(
        resolved_anchor_id=0,
        kind="orphan",
        user_error="Planned child row lost its parent anchor during load.",
        internal_error="Planned child row lost its parent anchor during load.",
    )


def evaluate_orphan_threshold(
    *,
    orphan_count: int,
    total_count: int,
    threshold: float = 0.1,
) -> OrphanThresholdDecision:
    safe_total = max(1, int(total_count or 0))
    ratio = max(0.0, float(orphan_count or 0) / safe_total)
    return OrphanThresholdDecision(
        orphan_count=max(0, int(orphan_count or 0)),
        total_count=safe_total,
        orphan_ratio=ratio,
        hard_fail=ratio > float(threshold),
    )


def build_root_conflict_error(
    *,
    entry: dict[str, Any],
    message: str,
) -> dict[str, Any]:
    return {
        "row": entry_row_num(entry),
        "errors": [message],
        "data": entry_dict(entry, "data"),
    }


__all__ = [
    "ChildAnchorClassification",
    "ChildAnchorFailureRows",
    "OrphanThresholdDecision",
    "RootConflictIsolationResult",
    "TimedInsertResult",
    "build_child_anchor_failure_rows",
    "build_root_conflict_error",
    "classify_child_anchor",
    "evaluate_orphan_threshold",
    "exception_sqlstate",
    "flush_root_entries_with_conflict_isolation",
    "is_unique_violation",
    "remember_created_anchor_keys",
    "timed_insert_batch_rows",
]
