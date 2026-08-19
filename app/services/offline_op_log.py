"""Account-scoped durable journal and reducer for offline mutations."""

from __future__ import annotations

import logging
import threading
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

from .offline_account_scope import (
    OfflineAccountScope,
    get_account_root,
    get_compatibility_scope,
    quarantine_legacy_api_queue_files,
    require_active_account_scope,
)
from .offline_conflicts import add_conflict
from .offline_ids import resolve_reconciled_id
from .offline_projection import remove_projection_record
from .offline_store_utils import (
    append_jsonl,
    load_json_with_quarantine,
    load_jsonl_with_quarantine,
    utc_now_iso,
    write_json_atomic,
)
from .offline_types import (
    OfflineConflict,
    OfflineEntityRef,
    OfflineEntityType,
    OfflineOperation,
)

_LOG_FILE = "op_log.jsonl"
_PENDING_FILE = "pending_snapshot.json"
_META_FILE = "meta.json"
_SCHEMA_VERSION = 1
_LOCK = threading.Lock()
_CORRUPT_BUCKET = "corrupt"
_QUEUE_COMPAT_READY_STATES = {"pending", "syncing", "blocked", "needs_review"}
_READY_PRIORITY = {"create": 0, "update": 1, "delete": 2, "action": 3}
logger = logging.getLogger(__name__)


class OfflineJournalCorrupt(RuntimeError):
    """Raised when the durable offline mutation journal is unreadable."""


def _resolve_scope(scope: OfflineAccountScope | None = None) -> OfflineAccountScope:
    return scope or get_compatibility_scope()


def _resolve_mutation_scope(scope: OfflineAccountScope | None = None) -> OfflineAccountScope:
    return scope or require_active_account_scope()


def _log_path(scope: OfflineAccountScope) -> Path:
    return get_account_root(scope) / _LOG_FILE


def _pending_path(scope: OfflineAccountScope) -> Path:
    return get_account_root(scope) / _PENDING_FILE


def _meta_path(scope: OfflineAccountScope) -> Path:
    return get_account_root(scope) / _META_FILE


def _ensure_meta(scope: OfflineAccountScope) -> None:
    path = _meta_path(scope)
    path_exists = path.exists()
    payload = load_json_with_quarantine(path, {}, bucket_name=_CORRUPT_BUCKET)
    if not isinstance(payload, dict):
        payload = {}
    changed = not path_exists
    if "schema_version" not in payload:
        payload["schema_version"] = _SCHEMA_VERSION
        changed = True
    if "last_sync_at" not in payload:
        payload["last_sync_at"] = ""
        changed = True
    if "compacted_at" not in payload:
        payload["compacted_at"] = ""
        changed = True
    if not changed:
        return
    try:
        write_json_atomic(path, payload)
    except OSError:
        # The metadata file is advisory only. Queue state comes from the
        # journal/snapshot, so a transient Windows file lock must not break
        # status refresh or offline queue access.
        logger.debug("Offline journal meta refresh skipped", exc_info=True)


def _mapping_dict(value: object) -> dict[str, object]:
    return {str(key): item for key, item in value.items()} if isinstance(value, Mapping) else {}


def _append_event(event: dict[str, Any], *, scope: OfflineAccountScope) -> None:
    append_jsonl(_log_path(scope), event)


def _read_pending_operations(scope: OfflineAccountScope) -> list[OfflineOperation]:
    pending_path = _pending_path(scope)
    if not pending_path.exists():
        return _rebuild_pending_from_log(scope)
    snapshot = load_json_with_quarantine(pending_path, [], bucket_name=_CORRUPT_BUCKET)
    if isinstance(snapshot, list):
        items: list[OfflineOperation] = []
        for entry in snapshot:
            try:
                op = OfflineOperation.from_dict(entry)
            except ValueError:
                continue
            if op.status in _QUEUE_COMPAT_READY_STATES:
                items.append(op)
        return items
    return _rebuild_pending_from_log(scope)


def _write_pending_operations(items: list[OfflineOperation], *, scope: OfflineAccountScope) -> None:
    write_json_atomic(_pending_path(scope), [item.to_dict() for item in items])


def _rebuild_pending_from_log(scope: OfflineAccountScope) -> list[OfflineOperation]:
    entries = load_jsonl_with_quarantine(_log_path(scope), bucket_name=_CORRUPT_BUCKET)
    active: dict[str, OfflineOperation] = {}
    for entry in entries:
        event_type = str(entry.get("event") or "")
        if event_type == "remove":
            active.pop(str(entry.get("op_id") or ""), None)
            continue
        raw_op = entry.get("op")
        try:
            op = OfflineOperation.from_dict(raw_op)
        except ValueError:
            continue
        if op.status in _QUEUE_COMPAT_READY_STATES:
            active[op.op_id] = op
        else:
            active.pop(op.op_id, None)
    items = sorted(active.values(), key=lambda item: (item.created_at, item.op_id))
    _write_pending_operations(items, scope=scope)
    return items


def _load_ops(scope: OfflineAccountScope) -> list[OfflineOperation]:
    _ensure_meta(scope)
    return _read_pending_operations(scope)


def _store_ops(items: list[OfflineOperation], *, scope: OfflineAccountScope) -> None:
    _write_pending_operations(items, scope=scope)


def _upsert_op(op: OfflineOperation, *, scope: OfflineAccountScope) -> OfflineOperation:
    items = [item for item in _load_ops(scope) if item.op_id != op.op_id]
    items.append(op)
    items.sort(key=lambda item: (item.created_at, item.op_id))
    _store_ops(items, scope=scope)
    _append_event({"event": "upsert", "at": utc_now_iso(), "op": op.to_dict()}, scope=scope)
    return op


def _remove_op(op_id: str, *, scope: OfflineAccountScope) -> None:
    items = [item for item in _load_ops(scope) if item.op_id != op_id]
    _store_ops(items, scope=scope)
    _append_event({"event": "remove", "at": utc_now_iso(), "op_id": op_id}, scope=scope)


def _find_create_for_entity(
    entity_type: str,
    local_id: int,
    *,
    scope: OfflineAccountScope,
) -> OfflineOperation | None:
    for item in _load_ops(scope):
        if (
            item.entity_type == entity_type
            and item.local_id == local_id
            and item.op_type == "create"
        ):
            return item
    return None


def _parent_is_resolved(ref: OfflineEntityRef, *, scope: OfflineAccountScope) -> bool:
    if ref.local_id > 0:
        return True
    return resolve_reconciled_id(ref.entity_type, ref.local_id, scope=scope) is not None


def _compute_initial_status(
    parent_refs: list[OfflineEntityRef], *, scope: OfflineAccountScope
) -> str:
    for ref in parent_refs:
        if not _parent_is_resolved(ref, scope=scope):
            return "blocked"
    return "pending"


def _normalize_operation(
    *,
    op: OfflineOperation,
    scope: OfflineAccountScope,
) -> OfflineOperation:
    status = op.status
    if (
        status == "blocked"
        and not op.last_error
        and op.parent_refs
        and all(_parent_is_resolved(ref, scope=scope) for ref in op.parent_refs)
    ):
        status = "pending"
    return OfflineOperation(
        op_id=op.op_id,
        account_key=op.account_key,
        entity_type=op.entity_type,
        op_type=op.op_type,
        local_id=op.local_id,
        payload=dict(op.payload),
        parent_refs=list(op.parent_refs),
        dedupe_key=op.dedupe_key,
        status=status,
        attempts=op.attempts,
        last_error=op.last_error,
        created_at=op.created_at,
        updated_at=op.updated_at or op.created_at,
    )


def list_operations(*, scope: OfflineAccountScope | None = None) -> list[OfflineOperation]:
    resolved = _resolve_scope(scope)
    return [_normalize_operation(op=op, scope=resolved) for op in _load_ops(resolved)]


def list_ready_operations(*, scope: OfflineAccountScope | None = None) -> list[OfflineOperation]:
    resolved = _resolve_scope(scope)
    items = []
    for op in list_operations(scope=resolved):
        if op.status != "pending":
            continue
        items.append(op)
    items.sort(
        key=lambda item: (_READY_PRIORITY.get(item.op_type, 99), item.created_at, item.op_id)
    )
    return items


def pending_operation_count(*, scope: OfflineAccountScope | None = None) -> int:
    return len(list_operations(scope=scope))


def queue_create_operation(
    entity_type: str,
    local_id: int,
    *,
    payload: dict[str, object],
    parent_refs: list[OfflineEntityRef] | None = None,
    dedupe_key: str | None = None,
    op_id: str | None = None,
    scope: OfflineAccountScope | None = None,
) -> OfflineOperation:
    resolved = _resolve_mutation_scope(scope)
    now = utc_now_iso()
    op = OfflineOperation(
        op_id=str(op_id or uuid.uuid4().hex),
        account_key=resolved.account_key,
        entity_type=entity_type,  # type: ignore[arg-type]
        op_type="create",
        local_id=int(local_id),
        payload=dict(payload),
        parent_refs=list(parent_refs or []),
        dedupe_key=str(dedupe_key or ""),
        status=_compute_initial_status(list(parent_refs or []), scope=resolved),  # type: ignore[arg-type]
        attempts=0,
        last_error="",
        created_at=now,
        updated_at=now,
    )
    return _upsert_op(op, scope=resolved)


def queue_update_operation(
    entity_type: str,
    local_id: int,
    *,
    payload: dict[str, object],
    dedupe_key: str | None = None,
    op_id: str | None = None,
    scope: OfflineAccountScope | None = None,
) -> OfflineOperation | None:
    resolved = _resolve_mutation_scope(scope)
    create_op = _find_create_for_entity(entity_type, local_id, scope=resolved)
    if create_op is not None:
        merged_payload = dict(create_op.payload)
        merged_body = _mapping_dict(merged_payload.get("body"))
        merged_body.update(_mapping_dict(payload.get("body")) or dict(payload))
        merged_payload["body"] = merged_body
        create_op.payload = merged_payload
        create_op.updated_at = utc_now_iso()
        _upsert_op(create_op, scope=resolved)
        return create_op

    existing_update = None
    for item in _load_ops(resolved):
        if (
            item.entity_type == entity_type
            and item.local_id == local_id
            and item.op_type == "update"
        ):
            existing_update = item
            break
        if (
            item.entity_type == entity_type
            and item.local_id == local_id
            and item.op_type == "delete"
        ):
            add_conflict(
                OfflineConflict(
                    op_id=item.op_id,
                    entity_type=entity_type,
                    local_id=int(local_id),
                    reason_code="delete_then_update",
                    message="Cannot queue an update after a pending delete.",
                    server_payload=dict(payload),
                    created_at=utc_now_iso(),
                ),
                scope=resolved,
            )
            return None

    body = _mapping_dict(payload.get("body")) or dict(payload)
    if existing_update is not None:
        merged = dict(existing_update.payload)
        merged_body = _mapping_dict(merged.get("body"))
        merged_body.update(body)
        merged["body"] = merged_body
        existing_update.payload = merged
        existing_update.updated_at = utc_now_iso()
        return _upsert_op(existing_update, scope=resolved)

    now = utc_now_iso()
    op = OfflineOperation(
        op_id=str(op_id or uuid.uuid4().hex),
        account_key=resolved.account_key,
        entity_type=entity_type,  # type: ignore[arg-type]
        op_type="update",
        local_id=int(local_id),
        payload=dict(payload),
        parent_refs=[],
        dedupe_key=str(dedupe_key or ""),
        status="pending",
        created_at=now,
        updated_at=now,
    )
    return _upsert_op(op, scope=resolved)


def _cancel_dependent_temp_creates(
    entity_type: str,
    local_id: int,
    *,
    scope: OfflineAccountScope,
) -> None:
    target = OfflineEntityRef(
        entity_type=cast(OfflineEntityType, entity_type),
        local_id=int(local_id),
    )
    items = _load_ops(scope)
    for item in list(items):
        if item.op_type != "create":
            continue
        if not any(ref == target for ref in item.parent_refs):
            continue
        _remove_op(item.op_id, scope=scope)
        remove_projection_record(item.entity_type, item.local_id, scope=scope)
        _cancel_dependent_temp_creates(item.entity_type, item.local_id, scope=scope)


def queue_delete_operation(
    entity_type: str,
    local_id: int,
    *,
    payload: dict[str, object] | None = None,
    dedupe_key: str | None = None,
    op_id: str | None = None,
    scope: OfflineAccountScope | None = None,
) -> OfflineOperation | None:
    resolved = _resolve_mutation_scope(scope)
    create_op = _find_create_for_entity(entity_type, local_id, scope=resolved)
    if create_op is not None:
        _remove_op(create_op.op_id, scope=resolved)
        remove_projection_record(entity_type, local_id, scope=resolved)
        _cancel_dependent_temp_creates(entity_type, local_id, scope=resolved)
        return None

    removed_ids: list[str] = []
    items = []
    for item in _load_ops(resolved):
        if (
            item.entity_type == entity_type
            and item.local_id == local_id
            and item.op_type == "update"
        ):
            removed_ids.append(item.op_id)
            continue
        items.append(item)
    _store_ops(items, scope=resolved)
    now = utc_now_iso()
    for removed_id in removed_ids:
        _append_event({"event": "remove", "at": now, "op_id": removed_id}, scope=resolved)

    op = OfflineOperation(
        op_id=str(op_id or uuid.uuid4().hex),
        account_key=resolved.account_key,
        entity_type=entity_type,  # type: ignore[arg-type]
        op_type="delete",
        local_id=int(local_id),
        payload=dict(payload or {}),
        parent_refs=[],
        dedupe_key=str(dedupe_key or ""),
        status="pending",
        created_at=now,
        updated_at=now,
    )
    return _upsert_op(op, scope=resolved)


def queue_action_operation(
    entity_type: str,
    local_id: int,
    *,
    payload: dict[str, object],
    dedupe_key: str | None = None,
    op_id: str | None = None,
    scope: OfflineAccountScope | None = None,
) -> OfflineOperation:
    resolved = _resolve_mutation_scope(scope)
    now = utc_now_iso()
    op = OfflineOperation(
        op_id=str(op_id or uuid.uuid4().hex),
        account_key=resolved.account_key,
        entity_type=entity_type,  # type: ignore[arg-type]
        op_type="action",
        local_id=int(local_id),
        payload=dict(payload),
        parent_refs=[],
        dedupe_key=str(dedupe_key or ""),
        status="pending",
        created_at=now,
        updated_at=now,
    )
    return _upsert_op(op, scope=resolved)


def queue_generic_api_mutation(
    method: str,
    path: str,
    *,
    json_body: dict[str, object] | None = None,
    params: dict[str, object] | None = None,
    headers: dict[str, str] | None = None,
    dedupe_key: str | None = None,
    label: str | None = None,
    op_id: str | None = None,
    scope: OfflineAccountScope | None = None,
) -> OfflineOperation:
    resolved = _resolve_mutation_scope(scope)
    quarantine_legacy_api_queue_files()
    normalized_dedupe = str(dedupe_key or "")
    if normalized_dedupe:
        removed_ids: list[str] = []
        items = []
        for item in _load_ops(resolved):
            if item.dedupe_key == normalized_dedupe:
                removed_ids.append(item.op_id)
                continue
            items.append(item)
        _store_ops(items, scope=resolved)
        now = utc_now_iso()
        for removed_id in removed_ids:
            _append_event({"event": "remove", "at": now, "op_id": removed_id}, scope=resolved)
    op_type = "action"
    normalized_method = str(method or "POST").upper()
    if normalized_method == "PUT":
        op_type = "update"
    elif normalized_method == "DELETE":
        op_type = "delete"
    elif normalized_method == "POST":
        op_type = "action"
    now = utc_now_iso()
    op = OfflineOperation(
        op_id=str(op_id or uuid.uuid4().hex),
        account_key=resolved.account_key,
        entity_type="generic",
        op_type=op_type,  # type: ignore[arg-type]
        local_id=0,
        payload={
            "method": normalized_method,
            "path": str(path),
            "body": _mapping_dict(json_body),
            "params": _mapping_dict(params),
            "headers": {str(k): str(v) for k, v in (headers or {}).items()},
            "label": str(label or ""),
        },
        parent_refs=[],
        dedupe_key=normalized_dedupe,
        status="pending",
        created_at=now,
        updated_at=now,
    )
    return _upsert_op(op, scope=resolved)


def refresh_blocked_operations(*, scope: OfflineAccountScope | None = None) -> int:
    resolved = _resolve_scope(scope)
    items = _load_ops(resolved)
    changed = 0
    updated_items: list[OfflineOperation] = []
    changed_ops: list[OfflineOperation] = []
    for item in items:
        updated = _normalize_operation(op=item, scope=resolved)
        if updated.status != item.status:
            changed += 1
            changed_ops.append(updated)
        updated_items.append(updated)
    if changed:
        _store_ops(updated_items, scope=resolved)
        now = utc_now_iso()
        for changed_op in changed_ops:
            _append_event(
                {"event": "upsert", "at": now, "op": changed_op.to_dict()}, scope=resolved
            )
    return changed


def note_operation_attempt(
    op_id: str, error_message: str, *, scope: OfflineAccountScope | None = None
) -> None:
    resolved = _resolve_scope(scope)
    items = _load_ops(resolved)
    updated_items: list[OfflineOperation] = []
    now = utc_now_iso()
    changed_op: OfflineOperation | None = None
    for item in items:
        if item.op_id != op_id:
            updated_items.append(item)
            continue
        item.attempts = int(item.attempts or 0) + 1
        item.last_error = str(error_message)
        item.updated_at = now
        changed_op = item
        updated_items.append(item)
    _store_ops(updated_items, scope=resolved)
    if changed_op is not None:
        _append_event({"event": "upsert", "at": now, "op": changed_op.to_dict()}, scope=resolved)


def update_operation_status(
    op_id: str,
    status: str,
    *,
    last_error: str = "",
    scope: OfflineAccountScope | None = None,
) -> OfflineOperation | None:
    resolved = _resolve_scope(scope)
    items = _load_ops(resolved)
    updated_items: list[OfflineOperation] = []
    updated: OfflineOperation | None = None
    now = utc_now_iso()
    for item in items:
        if item.op_id != op_id:
            updated_items.append(item)
            continue
        item.status = status  # type: ignore[assignment]
        item.last_error = str(last_error)
        item.updated_at = now
        updated = item
        if status in {"applied", "cancelled"}:
            continue
        updated_items.append(item)
    _store_ops(updated_items, scope=resolved)
    if updated is not None:
        _append_event({"event": "upsert", "at": now, "op": updated.to_dict()}, scope=resolved)
        if status in {"applied", "cancelled"}:
            _append_event({"event": "remove", "at": now, "op_id": op_id}, scope=resolved)
    return updated


def remove_operation(op_id: str, *, scope: OfflineAccountScope | None = None) -> None:
    resolved = _resolve_scope(scope)
    _remove_op(op_id, scope=resolved)


def discard_operation(op_id: str, *, scope: OfflineAccountScope | None = None) -> None:
    resolved = _resolve_scope(scope)
    op = get_operation(op_id, scope=resolved)
    if op is None:
        return
    _remove_op(op_id, scope=resolved)
    if op.entity_type != "generic":
        remove_projection_record(op.entity_type, op.local_id, scope=resolved)
    if op.op_type == "create" and op.local_id < 0 and op.entity_type != "generic":
        _cancel_dependent_temp_creates(op.entity_type, op.local_id, scope=resolved)
    refresh_blocked_operations(scope=resolved)


def get_operation(
    op_id: str, *, scope: OfflineAccountScope | None = None
) -> OfflineOperation | None:
    resolved = _resolve_scope(scope)
    for item in _load_ops(resolved):
        if item.op_id == op_id:
            return item
    return None


def clear_operation_store(*, scope: OfflineAccountScope | None = None) -> None:
    resolved = _resolve_scope(scope)
    _store_ops([], scope=resolved)
    ensure_path = _log_path(resolved)
    ensure_path.parent.mkdir(parents=True, exist_ok=True)
    ensure_path.write_text("", encoding="utf-8")


__all__ = [
    "OfflineJournalCorrupt",
    "clear_operation_store",
    "discard_operation",
    "get_operation",
    "list_operations",
    "list_ready_operations",
    "note_operation_attempt",
    "pending_operation_count",
    "queue_action_operation",
    "queue_create_operation",
    "queue_delete_operation",
    "queue_generic_api_mutation",
    "queue_update_operation",
    "refresh_blocked_operations",
    "remove_operation",
    "update_operation_status",
]
