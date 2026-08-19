"""Artifact-path and JSONL runtime helpers for importer execution."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, cast

from server.services.json_safe import json_safe_value


def require_path(path: Path | None, *, field_name: str) -> Path:
    if path is None:
        raise ValueError(f"Prepared import artifact is missing {field_name}.")
    return path


def write_jsonl_entry(handle: Any, payload: dict[str, Any]) -> None:
    handle.write(
        json.dumps(
            cast(dict[str, object], json_safe_value(payload)),
            ensure_ascii=True,
            separators=(",", ":"),
        )
    )
    handle.write("\n")


def entry_row_num(entry: Mapping[str, object]) -> int:
    raw_value = entry.get("row", 0)
    if isinstance(raw_value, bool):
        return int(raw_value)
    if isinstance(raw_value, int):
        return raw_value
    if isinstance(raw_value, str):
        try:
            return int(raw_value)
        except ValueError:
            return 0
    return 0


def entry_int(entry: Mapping[str, object], key: str) -> int:
    raw_value = entry.get(key, 0)
    if isinstance(raw_value, bool):
        return int(raw_value)
    if isinstance(raw_value, int):
        return raw_value
    if isinstance(raw_value, str):
        try:
            return int(raw_value)
        except ValueError:
            return 0
    return 0


def entry_dict(entry: Mapping[str, object], key: str) -> dict[str, Any]:
    raw_value = entry.get(key, {})
    if isinstance(raw_value, dict):
        return dict(raw_value)
    return {}


def entry_str(entry: Mapping[str, object], key: str) -> str:
    raw_value = entry.get(key, "")
    if isinstance(raw_value, str):
        return raw_value
    if raw_value is None:
        return ""
    return str(raw_value)


def entry_str_list(entry: Mapping[str, object], key: str) -> list[str]:
    raw_value = entry.get(key, [])
    if not isinstance(raw_value, list):
        return []
    return [str(item) for item in raw_value]


def iter_jsonl_entries(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            text = line.strip()
            if not text:
                continue
            value = json.loads(text)
            if isinstance(value, dict):
                yield value


def iter_jsonl_entry_batches(path: Path, batch_size: int) -> Any:
    effective_batch_size = max(1, int(batch_size))
    batch: list[dict[str, Any]] = []
    for entry in iter_jsonl_entries(path):
        batch.append(entry)
        if len(batch) >= effective_batch_size:
            yield batch
            batch = []
    if batch:
        yield batch


__all__ = [
    "entry_dict",
    "entry_int",
    "entry_row_num",
    "entry_str",
    "entry_str_list",
    "iter_jsonl_entries",
    "iter_jsonl_entry_batches",
    "require_path",
    "write_jsonl_entry",
]
