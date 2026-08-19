"""Shared load-phase counting semantics for direct and distributed import paths."""

from __future__ import annotations

from dataclasses import dataclass

from server.services.import_types import ImportResult


@dataclass(frozen=True)
class LoadCountDelta:
    skipped_count: int = 0
    error_count: int = 0


def child_anchor_failure_delta() -> LoadCountDelta:
    """Lost child-parent anchors are load errors, not deliberate skips."""
    return LoadCountDelta(error_count=1)


def root_conflict_failure_delta(*, failure_count: int) -> LoadCountDelta:
    """Conflict-isolated root rows that no longer load safely are load errors only."""
    return LoadCountDelta(error_count=max(0, int(failure_count or 0)))


def apply_load_count_delta(result: ImportResult, *, delta: LoadCountDelta) -> None:
    result.skipped_count += int(delta.skipped_count or 0)
    result.error_count += int(delta.error_count or 0)


__all__ = [
    "LoadCountDelta",
    "apply_load_count_delta",
    "child_anchor_failure_delta",
    "root_conflict_failure_delta",
]
