"""Compatibility facade over the account-scoped offline operation journal."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .offline_account_scope import (
    OfflineAccountScope,
    get_account_root,
    get_compatibility_scope,
    require_active_account_scope,
)
from .offline_op_log import (
    clear_operation_store,
    get_operation,
    list_operations,
    note_operation_attempt,
    queue_generic_api_mutation,
    remove_operation,
)
from .offline_store_utils import read_json, utc_now_iso, write_json_atomic

_FAILED_FILE = "failed_mutations.json"
_MAX_FAILED_ITEMS = 50


def _resolve_scope(scope: OfflineAccountScope | None = None) -> OfflineAccountScope:
    return scope or get_compatibility_scope()


def _resolve_write_scope(scope: OfflineAccountScope | None = None) -> OfflineAccountScope:
    return scope or require_active_account_scope()


def _failed_path(scope: OfflineAccountScope) -> Path:
    return get_account_root(scope) / _FAILED_FILE


def _load_failed(scope: OfflineAccountScope) -> list[dict[str, Any]]:
    payload = read_json(_failed_path(scope), [])
    return list(payload) if isinstance(payload, list) else []


def _write_failed(items: list[dict[str, Any]], *, scope: OfflineAccountScope) -> None:
    write_json_atomic(_failed_path(scope), items)


def _compat_item_from_op(op: object) -> dict[str, Any] | None:
    payload = getattr(op, "payload", None)
    if getattr(op, "entity_type", "") != "generic" or not isinstance(payload, dict):
        return None
    return {
        "id": str(getattr(op, "op_id", "")),
        "method": str(payload.get("method") or "POST"),
        "path": str(payload.get("path") or ""),
        "json_body": dict(payload.get("body") or {}),
        "params": dict(payload.get("params") or {}),
        "headers": {str(k): str(v) for k, v in dict(payload.get("headers") or {}).items()},
        "dedupe_key": str(getattr(op, "dedupe_key", "")),
        "label": str(payload.get("label") or ""),
        "attempts": int(getattr(op, "attempts", 0) or 0),
        "last_error": str(getattr(op, "last_error", "")),
        "created_at": str(getattr(op, "created_at", "")),
        "updated_at": str(getattr(op, "updated_at", "")),
    }


def enqueue_api_mutation(
    method: str,
    path: str,
    *,
    json_body: dict[str, object] | None = None,
    params: dict[str, object] | None = None,
    headers: dict[str, str] | None = None,
    dedupe_key: str | None = None,
    label: str | None = None,
) -> str:
    resolved_scope = _resolve_write_scope()
    op = queue_generic_api_mutation(
        method,
        path,
        json_body=dict(json_body or {}),
        params=dict(params or {}),
        headers={str(k): str(v) for k, v in (headers or {}).items()},
        dedupe_key=dedupe_key,
        label=label,
        scope=resolved_scope,
    )
    return op.op_id


def list_pending_api_mutations(*, scope: OfflineAccountScope | None = None) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for op in list_operations(scope=_resolve_scope(scope)):
        compat = _compat_item_from_op(op)
        if compat is None:
            continue
        items.append(compat)
    return items


def pending_api_mutation_count(*, scope: OfflineAccountScope | None = None) -> int:
    return len(list_pending_api_mutations(scope=scope))


def remove_api_mutation(queue_id: str, *, scope: OfflineAccountScope | None = None) -> None:
    remove_operation(queue_id, scope=_resolve_scope(scope))


def note_api_mutation_attempt(
    queue_id: str, error_message: str, *, scope: OfflineAccountScope | None = None
) -> None:
    note_operation_attempt(queue_id, error_message, scope=_resolve_scope(scope))


def record_failed_api_mutation(
    item: dict[str, Any],
    error_message: str,
    *,
    scope: OfflineAccountScope | None = None,
) -> None:
    scope = _resolve_write_scope(scope)
    failed_item = dict(item)
    failed_item["failed_at"] = utc_now_iso()
    failed_item["last_error"] = str(error_message)
    items = _load_failed(scope)
    items.append(failed_item)
    if len(items) > _MAX_FAILED_ITEMS:
        items = items[-_MAX_FAILED_ITEMS:]
    _write_failed(items, scope=scope)


def list_failed_api_mutations(*, scope: OfflineAccountScope | None = None) -> list[dict[str, Any]]:
    return list(_load_failed(_resolve_scope(scope)))


def failed_api_mutation_count(*, scope: OfflineAccountScope | None = None) -> int:
    return len(_load_failed(_resolve_scope(scope)))


def clear_api_write_queue(*, scope: OfflineAccountScope | None = None) -> None:
    scope = _resolve_scope(scope)
    clear_operation_store(scope=scope)
    _write_failed([], scope=scope)


def get_pending_api_mutation(
    queue_id: str, *, scope: OfflineAccountScope | None = None
) -> dict[str, Any] | None:
    op = get_operation(queue_id, scope=_resolve_scope(scope))
    return _compat_item_from_op(op) if op is not None else None


__all__ = [
    "clear_api_write_queue",
    "enqueue_api_mutation",
    "failed_api_mutation_count",
    "get_pending_api_mutation",
    "list_failed_api_mutations",
    "list_pending_api_mutations",
    "note_api_mutation_attempt",
    "pending_api_mutation_count",
    "record_failed_api_mutation",
    "remove_api_mutation",
]
