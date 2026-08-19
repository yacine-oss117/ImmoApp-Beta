"""Low-level file helpers for offline sync persistence."""

from __future__ import annotations

import json
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

_ATOMIC_REPLACE_ATTEMPTS = 5
_ATOMIC_REPLACE_BACKOFF_SECONDS = 0.05


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default
    return data


def load_json_with_quarantine(path: Path, default: Any, *, bucket_name: str) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        quarantine_file(path, bucket_name=bucket_name)
        return default


def write_json_atomic(path: Path, data: Any) -> None:
    ensure_parent(path)
    tmp = path.with_suffix(f"{path.suffix}.tmp.{uuid4().hex[:12]}")
    try:
        encoded = json.dumps(data, indent=2, ensure_ascii=True)
        for attempt in range(1, _ATOMIC_REPLACE_ATTEMPTS + 1):
            try:
                tmp.write_text(encoded, encoding="utf-8")
                break
            except FileNotFoundError:
                if attempt >= _ATOMIC_REPLACE_ATTEMPTS:
                    raise
                ensure_parent(path)
                time.sleep(_ATOMIC_REPLACE_BACKOFF_SECONDS * attempt)
        for attempt in range(1, _ATOMIC_REPLACE_ATTEMPTS + 1):
            try:
                tmp.replace(path)
                return
            except PermissionError:
                if attempt >= _ATOMIC_REPLACE_ATTEMPTS:
                    raise
                time.sleep(_ATOMIC_REPLACE_BACKOFF_SECONDS * attempt)
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass


def append_jsonl(path: Path, data: dict[str, Any]) -> None:
    ensure_parent(path)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(data, ensure_ascii=True))
        handle.write("\n")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    items: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                text = line.strip()
                if not text:
                    continue
                parsed = json.loads(text)
                if isinstance(parsed, dict):
                    items.append(parsed)
    except (OSError, json.JSONDecodeError):
        return []
    return items


def load_jsonl_with_quarantine(path: Path, *, bucket_name: str) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        items: list[dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                text = line.strip()
                if not text:
                    continue
                parsed = json.loads(text)
                if isinstance(parsed, dict):
                    items.append(parsed)
        return items
    except (OSError, json.JSONDecodeError):
        quarantine_file(path, bucket_name=bucket_name)
        return []


def quarantine_file(path: Path, *, bucket_name: str) -> Path | None:
    if not path.exists():
        return None
    bucket = path.parent / bucket_name
    bucket.mkdir(parents=True, exist_ok=True)
    target = bucket / f"{path.stem}.{uuid4().hex}{path.suffix}"
    try:
        shutil.move(str(path), str(target))
    except OSError:
        return None
    return target


__all__ = [
    "append_jsonl",
    "ensure_parent",
    "quarantine_file",
    "read_json",
    "read_jsonl",
    "utc_now_iso",
    "write_json_atomic",
]
