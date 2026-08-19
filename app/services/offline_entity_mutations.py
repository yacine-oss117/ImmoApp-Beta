"""Shared offline-aware mutation helpers for typed business entities."""

from __future__ import annotations

import logging
import os
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

from . import api_client as api_module
from .api_client import MutationDispatchResult
from .api_client_errors import ApiError
from .api_client_utils import as_dict
from .api_types import ParamsDict, ParamValue
from .offline_account_scope import (
    OfflineAccountScope,
    require_active_account_scope,
)
from .offline_ids import allocate_temp_id
from .offline_op_log import (
    queue_create_operation,
    queue_delete_operation,
    queue_update_operation,
)
from .offline_projection import (
    OfflineProjectionRecord,
    get_projection_record,
    mark_projection_status,
    remove_projection_record,
    upsert_projection_record,
)
from .offline_runtime import offline_creates_enabled
from .offline_types import OfflineEntityRef, OfflineEntityType, OfflineOperation

_RETRYABLE_STATUS_CODES = {408, 425, 429, 500, 502, 503, 504}
_E2E_DEBUG_MODE = os.environ.get("IMMOAPP_E2E_TEST_MODE", "").strip() == "1"
logger = logging.getLogger(__name__)


def _params_dict(value: Mapping[str, object] | None) -> ParamsDict:
    if value is None:
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


def _payload_id(payload: Mapping[str, object]) -> int:
    raw_id = payload.get("id")
    return int(raw_id) if isinstance(raw_id, (int, float, str)) else 0


@dataclass(frozen=True)
class OfflineCreateRequest:
    entity_type: OfflineEntityType
    request_body: dict[str, object]
    projection_data: dict[str, object]
    path: str | None = None
    path_template: str | None = None
    path_refs: dict[str, OfflineEntityRef] | None = None
    body_refs: dict[str, OfflineEntityRef] | None = None
    label: str = ""


def _resolve_scope(scope: OfflineAccountScope | None = None) -> OfflineAccountScope:
    return scope or require_active_account_scope()


def _idempotency_key(scope: OfflineAccountScope, entity_type: str, op_id: str) -> str:
    return f"offline:{scope.account_key}:{entity_type}:{op_id}"


def _is_retryable_error(exc: Exception) -> bool:
    if isinstance(exc, ApiError):
        return int(exc.status_code) in _RETRYABLE_STATUS_CODES
    return isinstance(exc, RuntimeError)


def _collect_parent_refs(
    path_refs: Mapping[str, OfflineEntityRef] | None,
    body_refs: Mapping[str, OfflineEntityRef] | None,
) -> list[OfflineEntityRef]:
    seen: set[tuple[str, int]] = set()
    refs: list[OfflineEntityRef] = []
    for mapping in (path_refs or {}, body_refs or {}):
        for ref in mapping.values():
            key = (ref.entity_type, int(ref.local_id))
            if key in seen:
                continue
            seen.add(key)
            refs.append(ref)
    return refs


def _resolved_parent_id(
    ref: OfflineEntityRef,
    *,
    scope: OfflineAccountScope,
) -> int | None:
    if ref.local_id > 0:
        return int(ref.local_id)
    from .offline_ids import resolve_reconciled_id

    return resolve_reconciled_id(ref.entity_type, ref.local_id, scope=scope)


def _resolve_path(
    path_template: str,
    path_refs: Mapping[str, OfflineEntityRef],
    *,
    scope: OfflineAccountScope,
) -> str:
    path = str(path_template)
    for key, ref in path_refs.items():
        resolved = _resolved_parent_id(ref, scope=scope)
        if resolved is None:
            raise RuntimeError(f"Unresolved parent reference for path field {key}")
        path = path.replace("{" + str(key) + "}", str(resolved))
    return path


def _resolve_body(
    body: Mapping[str, object],
    body_refs: Mapping[str, OfflineEntityRef],
    *,
    scope: OfflineAccountScope,
) -> dict[str, object]:
    resolved_body = dict(body)
    for key, ref in body_refs.items():
        resolved = _resolved_parent_id(ref, scope=scope)
        if resolved is None:
            raise RuntimeError(f"Unresolved parent reference for body field {key}")
        resolved_body[str(key)] = int(resolved)
    return resolved_body


def _create_projection(
    entity_type: OfflineEntityType,
    local_id: int,
    data: Mapping[str, object],
    *,
    sync_status: str,
    scope: OfflineAccountScope,
) -> None:
    payload = dict(data)
    payload.setdefault("id", int(local_id))
    upsert_projection_record(
        OfflineProjectionRecord(
            entity_type=entity_type,
            local_id=int(local_id),
            server_id=None,
            data=payload,
            sync_status=sync_status,
            sync_error="",
            is_local_only=True,
        ),
        scope=scope,
    )


def _queue_create(
    request: OfflineCreateRequest,
    *,
    op_id: str,
    scope: OfflineAccountScope,
) -> int:
    temp_id = allocate_temp_id(request.entity_type, scope=scope)
    idempotency_key = _idempotency_key(scope, request.entity_type, op_id)
    path_refs = request.path_refs or {}
    body_refs = request.body_refs or {}
    payload: dict[str, object] = {
        "method": "POST",
        "path": str(request.path or ""),
        "path_template": str(request.path_template or ""),
        "path_refs": {key: ref.to_dict() for key, ref in path_refs.items()},
        "body": dict(request.request_body),
        "body_refs": {key: ref.to_dict() for key, ref in body_refs.items()},
        "headers": {"Idempotency-Key": idempotency_key},
        "label": request.label,
    }
    parent_refs = _collect_parent_refs(path_refs, body_refs)
    op = queue_create_operation(
        request.entity_type,
        temp_id,
        payload=payload,
        parent_refs=parent_refs,
        dedupe_key=idempotency_key,
        op_id=op_id,
        scope=scope,
    )
    _create_projection(
        request.entity_type,
        temp_id,
        request.projection_data,
        sync_status=op.status,
        scope=scope,
    )
    return temp_id


def create_entity(
    request: OfflineCreateRequest,
    *,
    scope: OfflineAccountScope | None = None,
) -> int:
    resolved_scope = _resolve_scope(scope)
    if not offline_creates_enabled():
        path = (
            _resolve_path(request.path_template, request.path_refs or {}, scope=resolved_scope)
            if request.path_template
            else str(request.path or "")
        )
        body = _resolve_body(request.request_body, request.body_refs or {}, scope=resolved_scope)
        payload = as_dict(api_module.api_post(path, body))
        created_id = _payload_id(payload)
        if _E2E_DEBUG_MODE:
            logger.info(
                "E2E create_entity immediate result entity=%s path=%s created_id=%s payload=%s",
                request.entity_type,
                path,
                created_id,
                payload,
            )
        return created_id

    op_id = uuid.uuid4().hex
    if any(
        _resolved_parent_id(ref, scope=resolved_scope) is None
        for ref in _collect_parent_refs(request.path_refs, request.body_refs)
    ):
        queued_id = _queue_create(request, op_id=op_id, scope=resolved_scope)
        if _E2E_DEBUG_MODE:
            logger.info(
                "E2E create_entity queued unresolved parents entity=%s queued_id=%s",
                request.entity_type,
                queued_id,
            )
        return queued_id

    path = (
        _resolve_path(request.path_template, request.path_refs or {}, scope=resolved_scope)
        if request.path_template
        else str(request.path or "")
    )
    body = _resolve_body(request.request_body, request.body_refs or {}, scope=resolved_scope)
    idempotency_key = _idempotency_key(resolved_scope, request.entity_type, op_id)
    try:
        payload = as_dict(
            api_module._send_request(
                "POST",
                path,
                json_body=body,
                headers={"Idempotency-Key": idempotency_key},
                enforce_offline_guard=True,
            )
        )
    except Exception as exc:
        if not _is_retryable_error(exc):
            raise
        queued_id = _queue_create(request, op_id=op_id, scope=resolved_scope)
        if _E2E_DEBUG_MODE:
            logger.warning(
                "E2E create_entity queued after retryable error entity=%s path=%s queued_id=%s error=%s",
                request.entity_type,
                path,
                queued_id,
                exc,
            )
        return queued_id
    created_id = _payload_id(payload)
    if _E2E_DEBUG_MODE:
        logger.info(
            "E2E create_entity offline-enabled result entity=%s path=%s created_id=%s payload=%s",
            request.entity_type,
            path,
            created_id,
            payload,
        )
    return created_id


def _ensure_projection_for_real_entity(
    entity_type: OfflineEntityType,
    local_id: int,
    data: Mapping[str, object],
    *,
    sync_status: str,
    scope: OfflineAccountScope,
) -> None:
    existing = get_projection_record(entity_type, local_id, scope=scope)
    merged = dict(existing.data) if existing is not None else {}
    merged.update(dict(data))
    merged.setdefault("id", int(local_id))
    upsert_projection_record(
        OfflineProjectionRecord(
            entity_type=entity_type,
            local_id=int(local_id),
            server_id=int(local_id),
            data=merged,
            sync_status=sync_status,
            sync_error="",
            is_local_only=False,
        ),
        scope=scope,
    )


def update_entity(
    entity_type: OfflineEntityType,
    local_id: int,
    path: str,
    body: Mapping[str, object],
    *,
    dedupe_key: str,
    label: str,
    scope: OfflineAccountScope | None = None,
) -> MutationDispatchResult:
    resolved_scope = _resolve_scope(scope)
    if local_id < 0:
        op = queue_update_operation(
            entity_type,
            local_id,
            payload={
                "method": "PUT",
                "path": path,
                "body": dict(body),
                "label": label,
            },
            dedupe_key=dedupe_key,
            scope=resolved_scope,
        )
        record = get_projection_record(entity_type, local_id, scope=resolved_scope)
        merged: dict[str, object] = (
            dict(record.data) if record is not None else {"id": int(local_id)}
        )
        merged.update(dict(body))
        _create_projection(
            entity_type,
            local_id,
            merged,
            sync_status=(op.status if isinstance(op, OfflineOperation) else "pending"),
            scope=resolved_scope,
        )
        return MutationDispatchResult(
            payload=None, queued=True, queue_id=(op.op_id if op else None)
        )

    try:
        payload_out = api_module._send_request(
            "PUT",
            path,
            json_body=dict(body),
            enforce_offline_guard=True,
        )
    except Exception as exc:
        if not _is_retryable_error(exc):
            raise
        op = queue_update_operation(
            entity_type,
            local_id,
            payload={
                "method": "PUT",
                "path": path,
                "body": dict(body),
                "label": label,
            },
            dedupe_key=dedupe_key,
            scope=resolved_scope,
        )
        _ensure_projection_for_real_entity(
            entity_type,
            local_id,
            body,
            sync_status="pending",
            scope=resolved_scope,
        )
        return MutationDispatchResult(
            payload=None, queued=True, queue_id=(op.op_id if op else None)
        )
    remove_projection_record(entity_type, local_id, scope=resolved_scope)
    return MutationDispatchResult(payload=payload_out, queued=False, queue_id=None)


def delete_entity(
    entity_type: OfflineEntityType,
    local_id: int,
    path: str,
    *,
    params: Mapping[str, object] | None = None,
    dedupe_key: str,
    label: str,
    scope: OfflineAccountScope | None = None,
) -> MutationDispatchResult:
    resolved_scope = _resolve_scope(scope)
    if local_id < 0:
        op = queue_delete_operation(
            entity_type,
            local_id,
            payload={
                "method": "DELETE",
                "path": path,
                "params": cast(dict[str, object], _params_dict(params)),
                "label": label,
            },
            dedupe_key=dedupe_key,
            scope=resolved_scope,
        )
        return MutationDispatchResult(
            payload=None, queued=True, queue_id=(op.op_id if op else None)
        )

    try:
        payload_out = api_module._send_request(
            "DELETE",
            path,
            params=_params_dict(params),
            enforce_offline_guard=True,
        )
    except Exception as exc:
        if not _is_retryable_error(exc):
            raise
        op = queue_delete_operation(
            entity_type,
            local_id,
            payload={
                "method": "DELETE",
                "path": path,
                "params": cast(dict[str, object], _params_dict(params)),
                "label": label,
            },
            dedupe_key=dedupe_key,
            scope=resolved_scope,
        )
        _ensure_projection_for_real_entity(
            entity_type,
            local_id,
            {"id": int(local_id)},
            sync_status="pending_delete",
            scope=resolved_scope,
        )
        mark_projection_status(
            entity_type,
            local_id,
            sync_status="pending_delete",
            is_local_only=False,
            scope=resolved_scope,
        )
        return MutationDispatchResult(
            payload=None, queued=True, queue_id=(op.op_id if op else None)
        )
    remove_projection_record(entity_type, local_id, scope=resolved_scope)
    return MutationDispatchResult(payload=payload_out, queued=False, queue_id=None)


__all__ = [
    "OfflineCreateRequest",
    "create_entity",
    "delete_entity",
    "update_entity",
]
