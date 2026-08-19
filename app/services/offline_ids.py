"""Temporary local ID allocation and reconciliation maps for offline creates."""

from __future__ import annotations

from pathlib import Path

from .offline_account_scope import (
    OfflineAccountScope,
    get_account_root,
    require_active_account_scope,
)
from .offline_store_utils import read_json, write_json_atomic

_ALLOCATOR_FILE = "allocator_state.json"
_TEMP_MAP_FILE = "temp_id_map.json"


def _allocator_path(scope: OfflineAccountScope) -> Path:
    return get_account_root(scope) / _ALLOCATOR_FILE


def _temp_map_path(scope: OfflineAccountScope) -> Path:
    return get_account_root(scope) / _TEMP_MAP_FILE


def allocate_temp_id(entity_type: str, *, scope: OfflineAccountScope | None = None) -> int:
    resolved = scope or require_active_account_scope()
    path = _allocator_path(resolved)
    data = read_json(path, {})
    if not isinstance(data, dict):
        data = {}
    current = int(data.get(entity_type) or 0)
    next_value = current - 1 if current <= -1 else -1
    data[entity_type] = next_value
    write_json_atomic(path, data)
    return next_value


def get_reconciliation_map(
    *, scope: OfflineAccountScope | None = None
) -> dict[str, dict[str, int]]:
    resolved = scope or require_active_account_scope()
    data = read_json(_temp_map_path(resolved), {})
    if not isinstance(data, dict):
        return {}
    result: dict[str, dict[str, int]] = {}
    for entity_type, mappings in data.items():
        if not isinstance(mappings, dict):
            continue
        parsed: dict[str, int] = {}
        for key, value in mappings.items():
            if isinstance(value, int) and value > 0:
                parsed[str(key)] = int(value)
        if parsed:
            result[str(entity_type)] = parsed
    return result


def resolve_reconciled_id(
    entity_type: str,
    local_id: int,
    *,
    scope: OfflineAccountScope | None = None,
) -> int | None:
    if local_id > 0:
        return int(local_id)
    mappings = get_reconciliation_map(scope=scope)
    return mappings.get(entity_type, {}).get(str(int(local_id)))


def record_reconciled_id(
    entity_type: str,
    local_id: int,
    server_id: int,
    *,
    scope: OfflineAccountScope | None = None,
) -> None:
    resolved = scope or require_active_account_scope()
    path = _temp_map_path(resolved)
    data = get_reconciliation_map(scope=resolved)
    entity_map = dict(data.get(entity_type, {}))
    entity_map[str(int(local_id))] = int(server_id)
    data[entity_type] = entity_map
    write_json_atomic(path, data)


__all__ = [
    "allocate_temp_id",
    "get_reconciliation_map",
    "record_reconciled_id",
    "resolve_reconciled_id",
]
