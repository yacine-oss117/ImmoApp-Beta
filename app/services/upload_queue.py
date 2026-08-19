"""Account-scoped local upload queue for offline-first media uploads."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core_app.paths import get_app_data_dir

from .offline_account_scope import (
    OfflineAccountScope,
    get_account_root,
    legacy_quarantine_root,
    require_active_account_scope,
)

_QUEUE_DIR = "upload_queue"
_INDEX_FILE = "upload_queue.json"
_TERMINAL_STATUSES = {"applied", "cancelled"}


def _resolve_scope(scope: OfflineAccountScope | None = None) -> OfflineAccountScope:
    return scope or require_active_account_scope()


def _legacy_queue_root() -> Path:
    return get_app_data_dir() / _QUEUE_DIR


def _quarantine_legacy_queue() -> None:
    root = _legacy_queue_root()
    if not root.exists():
        return
    quarantine_root = legacy_quarantine_root() / _QUEUE_DIR
    quarantine_root.mkdir(parents=True, exist_ok=True)
    target = quarantine_root / f"legacy_{uuid.uuid4().hex}"
    try:
        shutil.move(str(root), str(target))
    except OSError:
        return


def _queue_root(*, scope: OfflineAccountScope | None = None) -> Path:
    _quarantine_legacy_queue()
    root = get_account_root(_resolve_scope(scope)) / _QUEUE_DIR
    root.mkdir(parents=True, exist_ok=True)
    return root


def _index_path(*, scope: OfflineAccountScope | None = None) -> Path:
    return _queue_root(scope=scope) / _INDEX_FILE


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _file_sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _dedupe_key(
    kind: str,
    file_sha256: str,
    *,
    parent_entity_type: str = "",
    parent_local_id: int = 0,
    position: int = 0,
) -> str:
    if kind == "offer_photo":
        return (
            f"offer_photo:{parent_entity_type}:{int(parent_local_id)}:{int(position)}:{file_sha256}"
        )
    return f"{kind}:{file_sha256}"


def _normalize_item(payload: dict[str, Any]) -> dict[str, Any]:
    item = dict(payload)
    parent_local_id = item.get("parent_local_id")
    storage_id = item.get("storage_id")
    file_sha = str(item.get("file_sha256") or "")
    path = str(item.get("path") or "")
    if not file_sha and path and os.path.exists(path):
        try:
            file_sha = _file_sha256(path)
        except OSError:
            file_sha = ""
    item.setdefault("id", uuid.uuid4().hex)
    item.setdefault("kind", "generic")
    item.setdefault("filename", os.path.basename(path) if path else "")
    item.setdefault("created_at", _utc_now())
    item.setdefault("updated_at", str(item.get("created_at") or _utc_now()))
    item.setdefault("status", "pending")
    item.setdefault("attempts", int(item.get("attempts") or 0))
    item.setdefault("last_error", str(item.get("last_error") or ""))
    item.setdefault("entity_type", "agency_media")
    item.setdefault("parent_entity_type", str(item.get("parent_entity_type") or ""))
    item["parent_local_id"] = (
        int(parent_local_id)
        if isinstance(parent_local_id, (int, float, str)) and str(parent_local_id or "").strip()
        else None
    )
    item["position"] = int(item.get("position") or 0)
    item.setdefault("purpose", str(item.get("purpose") or item.get("kind") or ""))
    item["storage_id"] = str(storage_id) if storage_id else ""
    item["file_sha256"] = file_sha
    if not item.get("dedupe_key"):
        item["dedupe_key"] = _dedupe_key(
            str(item.get("kind") or ""),
            file_sha,
            parent_entity_type=str(item.get("parent_entity_type") or ""),
            parent_local_id=int(item["parent_local_id"] or 0),
            position=int(item.get("position") or 0),
        )
    return item


def _load_index(*, scope: OfflineAccountScope | None = None) -> list[dict[str, Any]]:
    path = _index_path(scope=scope)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    items: list[dict[str, Any]] = []
    for entry in data:
        if isinstance(entry, dict):
            items.append(_normalize_item(entry))
    return items


def _write_index(
    items: list[dict[str, Any]],
    *,
    scope: OfflineAccountScope | None = None,
) -> None:
    path = _index_path(scope=scope)
    normalized: list[dict[str, Any]] = []
    for item in items:
        next_item = _normalize_item(item)
        if str(next_item.get("status") or "") in _TERMINAL_STATUSES:
            continue
        normalized.append(next_item)
    path.write_text(json.dumps(normalized, indent=2, ensure_ascii=True), encoding="utf-8")


def _copy_source_to_queue(source_path: str, *, queue_id: str, scope: OfflineAccountScope) -> str:
    dest = _queue_root(scope=scope) / f"{queue_id}_{os.path.basename(source_path)}"
    shutil.copy2(source_path, dest)
    return str(dest)


def enqueue_media(
    kind: str,
    source_path: str,
    *,
    scope: OfflineAccountScope | None = None,
    parent_entity_type: str = "",
    parent_local_id: int | None = None,
    position: int = 0,
    purpose: str | None = None,
) -> str:
    """Queue a media upload while offline."""
    if not os.path.exists(source_path):
        raise FileNotFoundError(source_path)
    resolved_scope = _resolve_scope(scope)
    queue_id = uuid.uuid4().hex
    dest = _copy_source_to_queue(source_path, queue_id=queue_id, scope=resolved_scope)
    file_sha = _file_sha256(dest)
    item = {
        "id": queue_id,
        "kind": kind,
        "filename": os.path.basename(source_path),
        "path": str(dest),
        "created_at": _utc_now(),
        "updated_at": _utc_now(),
        "status": "blocked" if parent_entity_type and int(parent_local_id or 0) < 0 else "pending",
        "attempts": 0,
        "last_error": "",
        "entity_type": "offer_photo" if kind == "offer_photo" else "agency_media",
        "parent_entity_type": parent_entity_type,
        "parent_local_id": int(parent_local_id) if parent_local_id is not None else None,
        "position": int(position),
        "purpose": str(purpose or kind),
        "storage_id": "",
        "file_sha256": file_sha,
        "dedupe_key": _dedupe_key(
            kind,
            file_sha,
            parent_entity_type=parent_entity_type,
            parent_local_id=int(parent_local_id or 0),
            position=position,
        ),
    }
    items = _load_index(scope=resolved_scope)
    if kind == "offer_photo":
        existing = next(
            (
                current
                for current in items
                if str(current.get("dedupe_key") or "") == item["dedupe_key"]
                and str(current.get("status") or "pending") not in _TERMINAL_STATUSES
            ),
            None,
        )
        if existing is not None:
            try:
                Path(dest).unlink(missing_ok=True)
            except OSError:
                pass
            return str(existing.get("id") or "")
    items.append(item)
    _write_index(items, scope=resolved_scope)
    return queue_id


def enqueue_offer_photo_upload(
    offer_id: int,
    source_path: str,
    *,
    position: int = 0,
    scope: OfflineAccountScope | None = None,
) -> str:
    return enqueue_media(
        "offer_photo",
        source_path,
        scope=scope,
        parent_entity_type="offer",
        parent_local_id=int(offer_id),
        position=position,
        purpose="offer_photo",
    )


def list_media_uploads(*, scope: OfflineAccountScope | None = None) -> list[dict[str, Any]]:
    return _load_index(scope=scope)


def get_media_upload(
    queue_id: str, *, scope: OfflineAccountScope | None = None
) -> dict[str, Any] | None:
    for item in _load_index(scope=scope):
        if str(item.get("id") or "") == str(queue_id):
            return item
    return None


def pending_media_upload_count(*, scope: OfflineAccountScope | None = None) -> int:
    return len(_load_index(scope=scope))


def media_review_count(*, scope: OfflineAccountScope | None = None) -> int:
    return sum(
        1 for item in _load_index(scope=scope) if str(item.get("status") or "") == "needs_review"
    )


def mark_media_upload(
    queue_id: str,
    *,
    status: str | None = None,
    error: str | None = None,
    storage_id: str | None = None,
    parent_local_id: int | None = None,
    scope: OfflineAccountScope | None = None,
) -> None:
    resolved_scope = _resolve_scope(scope)
    items = _load_index(scope=resolved_scope)
    updated: list[dict[str, Any]] = []
    for item in items:
        if str(item.get("id") or "") != str(queue_id):
            updated.append(item)
            continue
        next_item = dict(item)
        if status is not None:
            next_item["status"] = str(status)
        if error is not None:
            next_item["last_error"] = str(error)
        if storage_id is not None:
            next_item["storage_id"] = str(storage_id)
        if parent_local_id is not None:
            next_item["parent_local_id"] = int(parent_local_id)
        next_item["updated_at"] = _utc_now()
        updated.append(next_item)
    _write_index(updated, scope=resolved_scope)


def note_media_upload_attempt(
    queue_id: str,
    error: str = "",
    *,
    scope: OfflineAccountScope | None = None,
) -> None:
    resolved_scope = _resolve_scope(scope)
    items = _load_index(scope=resolved_scope)
    updated: list[dict[str, Any]] = []
    for item in items:
        if str(item.get("id") or "") != str(queue_id):
            updated.append(item)
            continue
        next_item = dict(item)
        next_item["attempts"] = int(next_item.get("attempts") or 0) + 1
        next_item["last_error"] = str(error)
        next_item["updated_at"] = _utc_now()
        updated.append(next_item)
    _write_index(updated, scope=resolved_scope)


def retry_media_upload(queue_id: str, *, scope: OfflineAccountScope | None = None) -> None:
    item = get_media_upload(queue_id, scope=scope)
    if item is None:
        return
    unresolved_parent = (
        bool(item.get("parent_entity_type")) and int(item.get("parent_local_id") or 0) < 0
    )
    mark_media_upload(
        queue_id,
        status="blocked" if unresolved_parent else "pending",
        error="",
        scope=scope,
    )


def rewrite_media_parent_refs(
    parent_entity_type: str,
    old_local_id: int,
    new_server_id: int,
    *,
    scope: OfflineAccountScope | None = None,
) -> int:
    resolved_scope = _resolve_scope(scope)
    items = _load_index(scope=resolved_scope)
    changed = 0
    updated: list[dict[str, Any]] = []
    for item in items:
        if str(item.get("parent_entity_type") or "") != str(parent_entity_type):
            updated.append(item)
            continue
        current_parent = int(item.get("parent_local_id") or 0)
        if current_parent != int(old_local_id):
            updated.append(item)
            continue
        next_item = dict(item)
        next_item["parent_local_id"] = int(new_server_id)
        if str(next_item.get("status") or "") == "blocked":
            next_item["status"] = "pending"
            next_item["last_error"] = ""
        next_item["updated_at"] = _utc_now()
        updated.append(next_item)
        changed += 1
    _write_index(updated, scope=resolved_scope)
    return changed


def remove_media_upload(queue_id: str, *, scope: OfflineAccountScope | None = None) -> None:
    resolved_scope = _resolve_scope(scope)
    items = _load_index(scope=resolved_scope)
    remaining: list[dict[str, Any]] = []
    for item in items:
        if item.get("id") == queue_id:
            path = Path(str(item.get("path") or ""))
            try:
                if path.exists():
                    path.unlink()
            except OSError:
                pass
            continue
        remaining.append(item)
    _write_index(remaining, scope=resolved_scope)


def discard_media_upload(queue_id: str, *, scope: OfflineAccountScope | None = None) -> None:
    remove_media_upload(queue_id, scope=scope)


__all__ = [
    "discard_media_upload",
    "enqueue_media",
    "enqueue_offer_photo_upload",
    "get_media_upload",
    "list_media_uploads",
    "mark_media_upload",
    "media_review_count",
    "note_media_upload_attempt",
    "pending_media_upload_count",
    "remove_media_upload",
    "retry_media_upload",
    "rewrite_media_parent_refs",
]
