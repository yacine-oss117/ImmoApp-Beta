"""Local projection overlay for pending offline entities and mutations."""

from __future__ import annotations

from dataclasses import is_dataclass
from pathlib import Path
from typing import Any, TypeVar, cast, overload

from app.models import Client, Contract, Demande, Listing, Offer, Visit

from .offline_account_scope import (
    OfflineAccountScope,
    get_account_root,
    get_active_account_scope,
    require_active_account_scope,
)
from .offline_store_utils import read_json, write_json_atomic
from .offline_types import OfflineProjectionRecord

_PROJECTION_FILE = "projection_snapshot.json"


_T = TypeVar("_T")

_MODEL_BY_ENTITY: dict[str, Any] = {
    "client": Client,
    "demande": Demande,
    "listing": Listing,
    "offer": Offer,
    "visit": Visit,
    "contract": Contract,
}


def _projection_path(scope: OfflineAccountScope) -> Path:
    return get_account_root(scope) / _PROJECTION_FILE


def _load_projection_map(scope: OfflineAccountScope) -> dict[str, dict[str, dict[str, object]]]:
    data = read_json(_projection_path(scope), {})
    if not isinstance(data, dict):
        return {}
    result: dict[str, dict[str, dict[str, object]]] = {}
    for entity_type, rows in data.items():
        if not isinstance(rows, dict):
            continue
        parsed_rows: dict[str, dict[str, object]] = {}
        for local_id, payload in rows.items():
            if isinstance(payload, dict):
                parsed_rows[str(local_id)] = payload
        result[str(entity_type)] = parsed_rows
    return result


def _write_projection_map(
    payload: dict[str, dict[str, dict[str, object]]],
    *,
    scope: OfflineAccountScope,
) -> None:
    write_json_atomic(_projection_path(scope), payload)


def list_projection_records(
    entity_type: str,
    *,
    scope: OfflineAccountScope | None = None,
) -> list[OfflineProjectionRecord]:
    resolved = scope or require_active_account_scope()
    payload = _load_projection_map(resolved).get(entity_type, {})
    items: list[OfflineProjectionRecord] = []
    for raw in payload.values():
        try:
            items.append(OfflineProjectionRecord.from_dict(raw))
        except ValueError:
            continue
    return items


def get_projection_record(
    entity_type: str,
    local_id: int,
    *,
    scope: OfflineAccountScope | None = None,
) -> OfflineProjectionRecord | None:
    resolved = scope or require_active_account_scope()
    payload = _load_projection_map(resolved).get(entity_type, {}).get(str(int(local_id)))
    if payload is None:
        return None
    try:
        return OfflineProjectionRecord.from_dict(payload)
    except ValueError:
        return None


def upsert_projection_record(
    record: OfflineProjectionRecord,
    *,
    scope: OfflineAccountScope | None = None,
) -> None:
    resolved = scope or require_active_account_scope()
    payload = _load_projection_map(resolved)
    entity_records = dict(payload.get(record.entity_type, {}))
    entity_records[str(int(record.local_id))] = record.to_dict()
    payload[record.entity_type] = entity_records
    _write_projection_map(payload, scope=resolved)


def remove_projection_record(
    entity_type: str,
    local_id: int,
    *,
    scope: OfflineAccountScope | None = None,
) -> None:
    resolved = scope or require_active_account_scope()
    payload = _load_projection_map(resolved)
    entity_records = dict(payload.get(entity_type, {}))
    entity_records.pop(str(int(local_id)), None)
    if entity_records:
        payload[entity_type] = entity_records
    else:
        payload.pop(entity_type, None)
    _write_projection_map(payload, scope=resolved)


def mark_projection_status(
    entity_type: str,
    local_id: int,
    *,
    sync_status: str,
    sync_error: str = "",
    is_local_only: bool | None = None,
    server_id: int | None = None,
    scope: OfflineAccountScope | None = None,
) -> None:
    record = get_projection_record(entity_type, local_id, scope=scope)
    if record is None:
        return
    updated = OfflineProjectionRecord(
        entity_type=record.entity_type,
        local_id=record.local_id,
        server_id=server_id if server_id is not None else record.server_id,
        data=dict(record.data),
        sync_status=sync_status,
        sync_error=sync_error,
        is_local_only=record.is_local_only if is_local_only is None else bool(is_local_only),
    )
    upsert_projection_record(updated, scope=scope)


def reconcile_projection_record(
    entity_type: str,
    temp_id: int,
    server_id: int,
    server_payload: dict[str, object],
    *,
    scope: OfflineAccountScope | None = None,
) -> None:
    resolved = scope or require_active_account_scope()
    remove_projection_record(entity_type, temp_id, scope=resolved)
    upsert_projection_record(
        OfflineProjectionRecord(
            entity_type=entity_type,  # type: ignore[arg-type]
            local_id=int(server_id),
            server_id=int(server_id),
            data=dict(server_payload),
            sync_status="synced",
            sync_error="",
            is_local_only=False,
        ),
        scope=resolved,
    )


_DEPENDENT_REFERENCE_FIELDS: dict[str, tuple[tuple[str, str], ...]] = {
    "client": (
        ("demande", "client_id"),
        ("visit", "client_id"),
        ("contract", "client_id"),
    ),
    "listing": (
        ("offer", "listing_id"),
        ("visit", "listing_id"),
        ("contract", "listing_id"),
    ),
    "contract": (("contract_article", "contract_id"),),
}


def rewrite_projection_parent_refs(
    parent_entity_type: str,
    old_local_id: int,
    new_server_id: int,
    *,
    scope: OfflineAccountScope | None = None,
) -> int:
    resolved = scope or require_active_account_scope()
    changed = 0
    for entity_type, field_name in _DEPENDENT_REFERENCE_FIELDS.get(parent_entity_type, ()):
        for record in list_projection_records(entity_type, scope=resolved):
            raw_value = record.data.get(field_name)
            if not isinstance(raw_value, (int, float, str)):
                continue
            try:
                current_value = int(raw_value)
            except ValueError:
                continue
            if current_value != int(old_local_id):
                continue
            payload = dict(record.data)
            payload[field_name] = int(new_server_id)
            upsert_projection_record(
                OfflineProjectionRecord(
                    entity_type=record.entity_type,
                    local_id=record.local_id,
                    server_id=record.server_id,
                    data=payload,
                    sync_status=record.sync_status,
                    sync_error=record.sync_error,
                    is_local_only=record.is_local_only,
                ),
                scope=resolved,
            )
            changed += 1
    return changed


def _apply_sync_metadata(model: Any, record: OfflineProjectionRecord) -> Any:
    model.sync_status = record.sync_status or None
    model.sync_error = record.sync_error
    model.is_local_only = record.is_local_only
    return model


def _model_from_record(entity_type: str, record: OfflineProjectionRecord) -> Any:
    model_cls = _MODEL_BY_ENTITY.get(entity_type)
    if model_cls is None:
        return dict(record.data)
    payload = dict(record.data)
    payload.setdefault("id", int(record.server_id or record.local_id))
    model = model_cls.from_row(payload)
    return _apply_sync_metadata(model, record) if is_dataclass(model) else model


def _merge_model_with_record(item: _T, record: OfflineProjectionRecord) -> _T:
    if not is_dataclass(item):
        return item
    merged = dict(cast(Any, item).to_dict())
    merged.update(record.data)
    merged.setdefault("id", int(record.server_id or record.local_id))
    model_cls = _MODEL_BY_ENTITY.get(record.entity_type)
    if model_cls is None:
        return item
    rebuilt = model_cls.from_row(merged)
    return cast(_T, _apply_sync_metadata(rebuilt, record))


def overlay_model_list(
    entity_type: str,
    items: list[_T],
    *,
    scope: OfflineAccountScope | None = None,
) -> list[_T]:
    resolved_scope = scope or get_active_account_scope()
    if resolved_scope is None:
        return list(items)
    records = list_projection_records(entity_type, scope=resolved_scope)
    records_by_positive = {
        int(record.local_id): record
        for record in records
        if int(record.local_id) > 0 and record.sync_status != "pending_delete"
    }
    hidden_positive = {
        int(record.local_id)
        for record in records
        if int(record.local_id) > 0 and record.sync_status == "pending_delete"
    }
    merged: list[_T] = []
    seen_ids: set[int] = set()
    for item in items:
        item_id = int(getattr(item, "id", 0) or 0)
        seen_ids.add(item_id)
        if item_id in hidden_positive:
            continue
        record = records_by_positive.get(item_id)
        merged.append(_merge_model_with_record(item, record) if record else item)
    local_only: list[_T] = []
    for record in records:
        if int(record.local_id) >= 0:
            continue
        if record.sync_status == "pending_delete":
            continue
        local_only.append(cast(_T, _model_from_record(entity_type, record)))
    synced_positive: list[_T] = []
    for record in records:
        record_id = int(record.local_id)
        if record_id <= 0 or record_id in seen_ids:
            continue
        if record.sync_status != "synced":
            continue
        synced_positive.append(cast(_T, _model_from_record(entity_type, record)))
    return [*local_only, *synced_positive, *merged]


@overload
def overlay_model_detail(
    entity_type: str,
    local_id: int,
    item: None,
    *,
    scope: OfflineAccountScope | None = None,
) -> Any | None: ...


@overload
def overlay_model_detail(
    entity_type: str,
    local_id: int,
    item: _T,
    *,
    scope: OfflineAccountScope | None = None,
) -> _T | None: ...


def overlay_model_detail(
    entity_type: str,
    local_id: int,
    item: _T | None,
    *,
    scope: OfflineAccountScope | None = None,
) -> _T | None:
    resolved_scope = scope or get_active_account_scope()
    if resolved_scope is None:
        return item
    record = get_projection_record(entity_type, local_id, scope=resolved_scope)
    if record is None:
        return item
    if record.sync_status == "pending_delete":
        return None
    if int(local_id) < 0 or item is None:
        return cast(_T, _model_from_record(entity_type, record))
    return _merge_model_with_record(item, record)


def projection_record_count(*, scope: OfflineAccountScope | None = None) -> int:
    resolved = scope or require_active_account_scope()
    payload = _load_projection_map(resolved)
    return sum(len(rows) for rows in payload.values())


__all__ = [
    "OfflineProjectionRecord",
    "get_projection_record",
    "list_projection_records",
    "mark_projection_status",
    "overlay_model_detail",
    "overlay_model_list",
    "projection_record_count",
    "reconcile_projection_record",
    "remove_projection_record",
    "rewrite_projection_parent_refs",
    "upsert_projection_record",
]
