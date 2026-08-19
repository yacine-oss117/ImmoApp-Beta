"""File-wide deterministic root dedupe helpers for importer prepare."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from server.services.duplicate_checker import _normalize_phone_for_dedup


@dataclass(frozen=True)
class RootKeyDecision:
    key: str
    winner_row: int
    is_duplicate: bool


def root_phone_key(row_data: Mapping[str, Any]) -> str:
    phone = _normalize_phone_for_dedup(str(row_data.get("phone", "") or ""))
    if not phone or len(phone) < 9:
        return ""
    return f"phone:{phone}"


def remember_root_key(
    seen_keys: dict[str, int],
    *,
    row_data: Mapping[str, Any],
    row_num: int,
) -> RootKeyDecision:
    key = root_phone_key(row_data)
    if not key:
        return RootKeyDecision(key="", winner_row=0, is_duplicate=False)
    winner_row = int(seen_keys.get(key, 0) or 0)
    if winner_row > 0:
        return RootKeyDecision(key=key, winner_row=winner_row, is_duplicate=True)
    seen_keys[key] = int(row_num)
    return RootKeyDecision(key=key, winner_row=int(row_num), is_duplicate=False)


__all__ = [
    "RootKeyDecision",
    "remember_root_key",
    "root_phone_key",
]
