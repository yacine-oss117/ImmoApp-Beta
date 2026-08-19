"""Conflict persistence for offline operations that require user review."""

from __future__ import annotations

from pathlib import Path

from .offline_account_scope import (
    OfflineAccountScope,
    get_account_root,
    require_active_account_scope,
)
from .offline_store_utils import read_json, utc_now_iso, write_json_atomic
from .offline_types import OfflineConflict

_CONFLICTS_FILE = "conflicts.json"


def _conflicts_path(scope: OfflineAccountScope) -> Path:
    return get_account_root(scope) / _CONFLICTS_FILE


def list_conflicts(*, scope: OfflineAccountScope | None = None) -> list[OfflineConflict]:
    resolved = scope or require_active_account_scope()
    raw = read_json(_conflicts_path(resolved), [])
    if not isinstance(raw, list):
        return []
    items: list[OfflineConflict] = []
    for entry in raw:
        try:
            items.append(OfflineConflict.from_dict(entry))
        except ValueError:
            continue
    return items


def write_conflicts(
    items: list[OfflineConflict],
    *,
    scope: OfflineAccountScope | None = None,
) -> None:
    resolved = scope or require_active_account_scope()
    write_json_atomic(_conflicts_path(resolved), [item.to_dict() for item in items])


def add_conflict(conflict: OfflineConflict, *, scope: OfflineAccountScope | None = None) -> None:
    resolved = scope or require_active_account_scope()
    items = [item for item in list_conflicts(scope=resolved) if item.op_id != conflict.op_id]
    if not conflict.created_at:
        conflict.created_at = utc_now_iso()
    items.append(conflict)
    write_conflicts(items, scope=resolved)


def remove_conflict(op_id: str, *, scope: OfflineAccountScope | None = None) -> None:
    resolved = scope or require_active_account_scope()
    items = [item for item in list_conflicts(scope=resolved) if item.op_id != op_id]
    write_conflicts(items, scope=resolved)


def needs_review_count(*, scope: OfflineAccountScope | None = None) -> int:
    return len(list_conflicts(scope=scope))


__all__ = [
    "OfflineConflict",
    "add_conflict",
    "list_conflicts",
    "needs_review_count",
    "remove_conflict",
    "write_conflicts",
]
