"""Dependency-aware replay and reconciliation for offline operations."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import cast

from .api_client_errors import ApiError
from .api_client_utils import as_dict
from .api_types import ParamsDict, ParamValue
from .offline_account_scope import OfflineAccountScope, require_active_account_scope
from .offline_conflicts import OfflineConflict, add_conflict, remove_conflict
from .offline_ids import record_reconciled_id, resolve_reconciled_id
from .offline_op_log import (
    list_operations,
    list_ready_operations,
    note_operation_attempt,
    pending_operation_count,
    refresh_blocked_operations,
    update_operation_status,
)
from .offline_projection import (
    get_projection_record,
    mark_projection_status,
    reconcile_projection_record,
    remove_projection_record,
    rewrite_projection_parent_refs,
)
from .offline_types import OfflineEntityRef, OfflineOperation
from .upload_queue import rewrite_media_parent_refs

logger = logging.getLogger(__name__)

_RETRYABLE_STATUS_CODES = {408, 425, 429, 500, 502, 503, 504}


def _resolve_scope(scope: OfflineAccountScope | None = None) -> OfflineAccountScope:
    return scope or require_active_account_scope()


def _mapping_dict(value: object) -> dict[str, object]:
    return {str(key): item for key, item in value.items()} if isinstance(value, Mapping) else {}


def _request_params_dict(value: object) -> ParamsDict:
    if not isinstance(value, Mapping):
        return {}
    params: dict[str, ParamValue] = {}
    for key, item in value.items():
        if isinstance(item, (str, bytes, int, float)) or item is None:
            params[str(key)] = item
        elif isinstance(item, list) and all(
            isinstance(entry, (str, bytes, int, float)) for entry in item
        ):
            params[str(key)] = list(item)
    return params


def _is_retryable_error(exc: Exception) -> bool:
    if isinstance(exc, ApiError):
        return int(exc.status_code) in _RETRYABLE_STATUS_CODES
    return isinstance(exc, RuntimeError)


def _set_projection_status(
    op: OfflineOperation,
    status: str,
    *,
    scope: OfflineAccountScope,
    error: str = "",
) -> None:
    if op.entity_type == "generic":
        return
    record = get_projection_record(op.entity_type, op.local_id, scope=scope)
    if record is None:
        return
    mark_projection_status(
        op.entity_type,
        op.local_id,
        sync_status=status,
        sync_error=error,
        scope=scope,
    )


def _sync_create_projection_statuses(*, scope: OfflineAccountScope) -> None:
    for op in list_operations(scope=scope):
        if op.op_type != "create" or op.entity_type == "generic":
            continue
        if op.local_id >= 0:
            continue
        record = get_projection_record(op.entity_type, op.local_id, scope=scope)
        if record is None:
            continue
        desired = op.status
        if record.sync_status != desired or record.sync_error != op.last_error:
            mark_projection_status(
                op.entity_type,
                op.local_id,
                sync_status=desired,
                sync_error=op.last_error,
                scope=scope,
            )


def _resolved_parent_id(ref: OfflineEntityRef, *, scope: OfflineAccountScope) -> int | None:
    if ref.local_id > 0:
        return int(ref.local_id)
    return resolve_reconciled_id(ref.entity_type, ref.local_id, scope=scope)


def _resolve_path_template(
    path_template: str,
    path_refs: Mapping[str, object],
    *,
    scope: OfflineAccountScope,
) -> str:
    path = str(path_template)
    for key, raw_ref in path_refs.items():
        ref = OfflineEntityRef.from_dict(raw_ref)
        resolved = _resolved_parent_id(ref, scope=scope)
        if resolved is None:
            raise RuntimeError(f"Unresolved parent reference for path field {key}")
        path = path.replace("{" + str(key) + "}", str(resolved))
    return path


def _resolve_body_refs(
    body: dict[str, object],
    body_refs: Mapping[str, object],
    *,
    scope: OfflineAccountScope,
) -> dict[str, object]:
    resolved_body = dict(body)
    for key, raw_ref in body_refs.items():
        ref = OfflineEntityRef.from_dict(raw_ref)
        resolved = _resolved_parent_id(ref, scope=scope)
        if resolved is None:
            raise RuntimeError(f"Unresolved parent reference for body field {key}")
        resolved_body[str(key)] = int(resolved)
    return resolved_body


def _resolve_request_payload(
    op: OfflineOperation,
    *,
    scope: OfflineAccountScope,
) -> tuple[str, str, dict[str, object], ParamsDict, dict[str, str]]:
    payload = dict(op.payload)
    method = str(payload.get("method") or "POST").upper()
    if payload.get("path_template"):
        path = _resolve_path_template(
            str(payload.get("path_template") or ""),
            cast(Mapping[str, object], payload.get("path_refs") or {}),
            scope=scope,
        )
    else:
        path = str(payload.get("path") or "")
    body = _mapping_dict(payload.get("body"))
    body = _resolve_body_refs(
        body, cast(Mapping[str, object], payload.get("body_refs") or {}), scope=scope
    )
    params = _request_params_dict(payload.get("params"))
    headers = {str(k): str(v) for k, v in _mapping_dict(payload.get("headers")).items()}
    return method, path, body, params, headers


def _create_conflict(
    op: OfflineOperation,
    reason: str,
    message: str,
    *,
    scope: OfflineAccountScope,
    server_payload: dict[str, object] | None = None,
) -> None:
    add_conflict(
        OfflineConflict(
            op_id=op.op_id,
            entity_type=op.entity_type,
            local_id=op.local_id,
            reason_code=reason,
            message=message,
            server_payload=server_payload,
        ),
        scope=scope,
    )


def _apply_create_success(
    op: OfflineOperation,
    response_payload: dict[str, object],
    request_body: dict[str, object],
    *,
    scope: OfflineAccountScope,
) -> None:
    raw_created_id = response_payload.get("id")
    created_id = int(raw_created_id) if isinstance(raw_created_id, (int, float, str)) else 0
    if created_id <= 0:
        raise ValueError("Create response missing canonical id.")
    item = response_payload.get("item")
    server_payload = dict(item) if isinstance(item, dict) else dict(request_body)
    server_payload.setdefault("id", created_id)
    record_reconciled_id(op.entity_type, op.local_id, created_id, scope=scope)
    reconcile_projection_record(
        op.entity_type, op.local_id, created_id, server_payload, scope=scope
    )
    rewrite_projection_parent_refs(op.entity_type, op.local_id, created_id, scope=scope)
    rewrite_media_parent_refs(op.entity_type, op.local_id, created_id, scope=scope)
    update_operation_status(op.op_id, "applied", scope=scope)
    remove_conflict(op.op_id, scope=scope)
    refresh_blocked_operations(scope=scope)
    _sync_create_projection_statuses(scope=scope)


def _handle_retryable_failure(
    op: OfflineOperation, exc: Exception, *, scope: OfflineAccountScope
) -> None:
    note_operation_attempt(op.op_id, str(exc), scope=scope)
    update_operation_status(op.op_id, "pending", last_error=str(exc), scope=scope)
    _set_projection_status(op, "pending", scope=scope, error=str(exc))


def _handle_auth_block(op: OfflineOperation, exc: ApiError, *, scope: OfflineAccountScope) -> None:
    update_operation_status(op.op_id, "blocked", last_error="auth_required", scope=scope)
    _set_projection_status(op, "blocked", scope=scope, error=str(exc))


def _handle_review_failure(
    op: OfflineOperation, exc: Exception, *, scope: OfflineAccountScope
) -> None:
    update_operation_status(op.op_id, "needs_review", last_error=str(exc), scope=scope)
    _set_projection_status(op, "needs_review", scope=scope, error=str(exc))
    _create_conflict(op, "sync_review_required", str(exc), scope=scope)


def _handle_generic_permanent_failure(
    op: OfflineOperation, exc: Exception, *, scope: OfflineAccountScope
) -> None:
    from .api_write_queue import record_failed_api_mutation

    compat_item = {
        "id": op.op_id,
        "method": str(op.payload.get("method") or "POST"),
        "path": str(op.payload.get("path") or ""),
        "json_body": _mapping_dict(op.payload.get("body")),
        "params": _mapping_dict(op.payload.get("params")),
        "headers": {str(k): str(v) for k, v in _mapping_dict(op.payload.get("headers")).items()},
        "dedupe_key": op.dedupe_key,
        "label": str(op.payload.get("label") or ""),
    }
    record_failed_api_mutation(compat_item, str(exc), scope=scope)
    update_operation_status(op.op_id, "cancelled", last_error=str(exc), scope=scope)


def _replay_operation(op: OfflineOperation, *, scope: OfflineAccountScope) -> str:
    from . import api_client as api_module

    method, path, body, params, headers = _resolve_request_payload(op, scope=scope)
    update_operation_status(op.op_id, "syncing", scope=scope)
    _set_projection_status(op, "syncing", scope=scope)
    try:
        payload = api_module._send_request(
            method,
            path,
            params=params,
            json_body=body,
            headers=headers,
            enforce_offline_guard=False,
        )
    except ApiError as exc:
        if exc.status_code in (401, 403):
            _handle_auth_block(op, exc, scope=scope)
            return "blocked"
        if _is_retryable_error(exc):
            _handle_retryable_failure(op, exc, scope=scope)
            return "retryable"
        if op.entity_type == "generic":
            _handle_generic_permanent_failure(op, exc, scope=scope)
            return "discarded"
        _handle_review_failure(op, exc, scope=scope)
        return "needs_review"
    except RuntimeError as exc:
        _handle_retryable_failure(op, exc, scope=scope)
        return "retryable"
    except Exception as exc:
        if op.entity_type == "generic":
            _handle_generic_permanent_failure(op, exc, scope=scope)
            return "discarded"
        _handle_review_failure(op, exc, scope=scope)
        return "needs_review"

    if op.op_type == "create" and op.entity_type != "generic":
        payload_dict = as_dict(payload)
        try:
            _apply_create_success(op, payload_dict, body, scope=scope)
        except Exception as exc:
            _handle_review_failure(op, exc, scope=scope)
            return "needs_review"
        return "flushed"

    update_operation_status(op.op_id, "applied", scope=scope)
    remove_conflict(op.op_id, scope=scope)
    if op.op_type == "delete" and op.entity_type != "generic":
        remove_projection_record(op.entity_type, op.local_id, scope=scope)
    else:
        _set_projection_status(op, "synced", scope=scope)
    return "flushed"


def replay_offline_operations(
    limit: int = 50, *, scope: OfflineAccountScope | None = None
) -> dict[str, int]:
    resolved = _resolve_scope(scope)
    refresh_blocked_operations(scope=resolved)
    _sync_create_projection_statuses(scope=resolved)
    results = {
        "flushed": 0,
        "discarded": 0,
        "blocked": 0,
        "needs_review": 0,
        "retryable": 0,
    }
    for op in list_ready_operations(scope=resolved)[: max(1, int(limit))]:
        outcome = _replay_operation(op, scope=resolved)
        if outcome in results:
            results[outcome] += 1
        if outcome == "retryable":
            break
    refresh_blocked_operations(scope=resolved)
    _sync_create_projection_statuses(scope=resolved)
    results["pending"] = pending_operation_count(scope=resolved)
    results["failed_permanent"] = results["discarded"]
    return results


__all__ = ["replay_offline_operations"]
