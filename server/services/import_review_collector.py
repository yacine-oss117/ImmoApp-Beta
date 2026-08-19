"""Spool-backed collection of unresolved import review items."""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from typing import Any, Iterator, Self

from server.services.json_safe import json_safe_value


class ImportReviewCollector:
    """Collect review items without keeping the full set in memory.

    Cleanup releases the backing spool resources but preserves in-memory metrics so callers can
    still read final counts and overflow diagnostics after execution finishes.
    """

    def __init__(
        self,
        *,
        max_items_emergency: int,
        diagnostic_limit: int = 50,
    ) -> None:
        self._max_items_emergency = max(1, int(max_items_emergency or 1))
        self._diagnostic_limit = max(1, int(diagnostic_limit or 1))
        self._temp_dir = Path(tempfile.mkdtemp(prefix="immoapp-review-collector-"))
        self._spool_path = self._temp_dir / "review_rows.jsonl"
        self._handle = self._spool_path.open("w", encoding="utf-8")
        self._count = 0
        self._diagnostic_sample: list[dict[str, Any]] = []
        self._artifact_manifest_ids: list[int] = []
        self.overflow_count = 0
        self._cleaned_up = False

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.cleanup()

    @property
    def spool_path(self) -> Path:
        return self._spool_path

    def add_review_item(
        self,
        *,
        row_ordinal: int,
        entity_type: str,
        topology_side: str,
        root_identity_snapshot: dict[str, Any] | None,
        payload: dict[str, Any],
    ) -> bool:
        row_payload = dict(payload)
        row_payload.setdefault("row", int(row_ordinal))
        row_payload.setdefault("entity_type", str(entity_type or ""))
        row_payload.setdefault("topology_side", str(topology_side or ""))
        if root_identity_snapshot:
            row_payload.setdefault("root_identity_snapshot", dict(root_identity_snapshot))
        return self.append(row_payload)

    def append(self, review_row: dict[str, Any]) -> bool:
        self._ensure_mutable("append")
        safe_row = self._safe_row(review_row)
        if self._count >= self._max_items_emergency:
            self.overflow_count += 1
            if len(self._diagnostic_sample) < self._diagnostic_limit:
                self._diagnostic_sample.append(dict(safe_row))
            return False
        if len(self._diagnostic_sample) < self._diagnostic_limit:
            self._diagnostic_sample.append(dict(safe_row))
        self._handle.write(json.dumps(safe_row, ensure_ascii=True, separators=(",", ":")) + "\n")
        self._count += 1
        return True

    def extend(self, rows: Iterator[dict[str, Any]] | list[dict[str, Any]]) -> None:
        self._ensure_mutable("extend")
        for row in rows:
            self.append(dict(row))

    def flush(self) -> None:
        self._ensure_spool_available("flush")
        if not self._handle.closed:
            self._handle.flush()

    def item_count(self) -> int:
        return int(self._count)

    def emergency_overflowed(self) -> bool:
        return self.emergency_overflow_count() > 0

    def emergency_overflow_count(self) -> int:
        return max(0, int(self.overflow_count or 0))

    def diagnostic_sample(self) -> list[dict[str, Any]]:
        return [dict(row) for row in self._diagnostic_sample]

    def artifact_manifest_ids(self) -> list[int]:
        return [int(value) for value in self._artifact_manifest_ids]

    def remember_artifact_manifest_id(self, manifest_id: int) -> None:
        self._ensure_mutable("remember_artifact_manifest_id")
        resolved = int(manifest_id or 0)
        if resolved > 0:
            self._artifact_manifest_ids.append(resolved)

    def close(self) -> None:
        if not self._handle.closed:
            self._handle.close()

    def cleanup(self) -> None:
        if self._cleaned_up:
            return
        self.close()
        shutil.rmtree(self._temp_dir, ignore_errors=True)
        self._cleaned_up = True

    def to_list(self, *, limit: int | None = None) -> list[dict[str, Any]]:
        self._ensure_spool_available("to_list")
        rows: list[dict[str, Any]] = []
        for index, row in enumerate(self):
            if limit is not None and index >= max(0, int(limit)):
                break
            rows.append(dict(row))
        return rows

    def __len__(self) -> int:
        return int(self._count)

    def __bool__(self) -> bool:
        return self._count > 0

    def __iter__(self) -> Iterator[dict[str, Any]]:
        self._ensure_spool_available("__iter__")
        self.flush()
        if not self._spool_path.exists():
            return iter(())
        return self._iter_rows()

    def _iter_rows(self) -> Iterator[dict[str, Any]]:
        with self._spool_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                text = line.strip()
                if not text:
                    continue
                value = json.loads(text)
                if isinstance(value, dict):
                    yield {str(key): item for key, item in value.items()}

    def __getitem__(self, index: int | slice) -> Any:
        self._ensure_spool_available("__getitem__")
        if isinstance(index, slice):
            start, stop, step = index.indices(len(self))
            result: list[dict[str, Any]] = []
            for row_index, row in enumerate(self):
                if row_index < start:
                    continue
                if row_index >= stop:
                    break
                if (row_index - start) % step == 0:
                    result.append(dict(row))
            return result
        resolved_index = int(index)
        if resolved_index < 0:
            resolved_index = len(self) + resolved_index
        if resolved_index < 0:
            raise IndexError(index)
        for row_index, row in enumerate(self):
            if row_index == resolved_index:
                return dict(row)
        raise IndexError(index)

    def _safe_row(self, review_row: dict[str, Any]) -> dict[str, Any]:
        value = json_safe_value(dict(review_row))
        if isinstance(value, dict):
            return {str(key): item for key, item in value.items()}
        return {}

    def _ensure_mutable(self, operation: str) -> None:
        if self._cleaned_up:
            raise RuntimeError(
                f"ImportReviewCollector does not support {operation} after cleanup()."
            )

    def _ensure_spool_available(self, operation: str) -> None:
        if self._cleaned_up:
            raise RuntimeError(
                f"ImportReviewCollector does not support {operation} after cleanup()."
            )


__all__ = ["ImportReviewCollector"]
