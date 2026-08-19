"""Persistent draft state for onboarding dialogs."""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.core_app.paths import config_dir

logger = logging.getLogger(__name__)

_FILE_NAME = "onboarding_drafts_v1.json"
_LOCK = threading.Lock()
REGISTER_DRAFT_KEY = "register_dialog"
ACTIVATE_DRAFT_KEY = "activate_dialog"
JOIN_TEAM_DRAFT_KEY = "join_team_dialog"
_RESUME_PRIORITY = (ACTIVATE_DRAFT_KEY, JOIN_TEAM_DRAFT_KEY, REGISTER_DRAFT_KEY)
_KNOWN_KEYS = (REGISTER_DRAFT_KEY, ACTIVATE_DRAFT_KEY, JOIN_TEAM_DRAFT_KEY)
_TTL_DAYS = max(1, int(os.environ.get("IMMOAPP_ONBOARDING_DRAFT_TTL_DAYS", "14")))


def _draft_path() -> Path:
    return config_dir() / _FILE_NAME


def load_onboarding_draft(key: str) -> dict[str, Any]:
    with _LOCK:
        data = _read_all()
        changed = _purge_expired_locked(data)
        payload = _entry_payload(data.get(str(key)))
        if payload is None:
            if changed:
                _write_all(data)
            return {}
        if changed:
            _write_all(data)
        return dict(payload)


def has_onboarding_draft(key: str) -> bool:
    payload = load_onboarding_draft(key)
    return bool(payload)


def resolve_resume_target() -> str | None:
    with _LOCK:
        data = _read_all()
        changed = _purge_expired_locked(data)
        if changed:
            _write_all(data)
    for key in _RESUME_PRIORITY:
        payload = _entry_payload(data.get(key))
        if isinstance(payload, dict) and payload:
            return key
    return None


def save_onboarding_draft(key: str, payload: dict[str, Any]) -> None:
    normalized = _normalize_payload(payload)
    with _LOCK:
        data = _read_all()
        _purge_expired_locked(data)
        data[str(key)] = {
            "payload": normalized,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        _write_all(data)


def clear_onboarding_draft(key: str) -> None:
    with _LOCK:
        data = _read_all()
        if str(key) not in data:
            return
        data.pop(str(key), None)
        _write_all(data)


def clear_all_onboarding_drafts() -> None:
    with _LOCK:
        data = _read_all()
        changed = False
        for key in _KNOWN_KEYS:
            if key in data:
                data.pop(key, None)
                changed = True
        if changed:
            _write_all(data)


def get_onboarding_draft_statuses() -> dict[str, dict[str, str | bool]]:
    with _LOCK:
        data = _read_all()
        changed = _purge_expired_locked(data)
        if changed:
            _write_all(data)

        statuses: dict[str, dict[str, str | bool]] = {}
        for key in _KNOWN_KEYS:
            entry = data.get(key)
            payload = _entry_payload(entry)
            raw_updated = _entry_updated_at(entry)
            statuses[key] = {
                "exists": bool(payload),
                "updated_at": raw_updated or "",
            }
        return statuses


def _normalize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in payload.items():
        if isinstance(v, (str, int, float, bool)) or v is None:
            out[str(k)] = v
    return out


def _entry_payload(entry: object) -> dict[str, Any] | None:
    if isinstance(entry, dict):
        payload = entry.get("payload")
        if isinstance(payload, dict):
            return dict(payload)
        if "payload" in entry or "updated_at" in entry:
            return None
        # Legacy format: payload stored at top level.
        if all(isinstance(k, str) for k in entry.keys()):
            return dict(entry)
    return None


def _entry_updated_at(entry: object) -> str:
    if not isinstance(entry, dict):
        return ""
    raw = entry.get("updated_at")
    if isinstance(raw, str):
        return raw.strip()
    return ""


def _parse_ts(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _is_expired(updated_at: datetime) -> bool:
    cutoff = datetime.now(timezone.utc) - timedelta(days=_TTL_DAYS)
    return updated_at < cutoff


def _purge_expired_locked(data: dict[str, dict[str, Any]]) -> bool:
    changed = False
    keys_to_remove: list[str] = []
    for key, entry in list(data.items()):
        payload = _entry_payload(entry)
        if payload is None:
            keys_to_remove.append(str(key))
            continue
        raw_updated = _entry_updated_at(entry)
        parsed = _parse_ts(raw_updated)
        if parsed is not None and _is_expired(parsed):
            keys_to_remove.append(str(key))
            continue
        # Legacy entry: upgrade in-memory shape to envelope.
        if parsed is None:
            data[str(key)] = {
                "payload": payload,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            changed = True
    for key in keys_to_remove:
        data.pop(key, None)
        changed = True
    return changed


def _read_all() -> dict[str, dict[str, Any]]:
    path = _draft_path()
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for k, value in raw.items():
        if isinstance(k, str) and isinstance(value, dict):
            out[k] = dict(value)
    return out


def _write_all(data: dict[str, dict[str, Any]]) -> None:
    path = _draft_path()
    tmp = path.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=True, indent=2), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        logger.warning("Failed to persist onboarding draft state", exc_info=True)


__all__ = [
    "ACTIVATE_DRAFT_KEY",
    "JOIN_TEAM_DRAFT_KEY",
    "REGISTER_DRAFT_KEY",
    "clear_all_onboarding_drafts",
    "clear_onboarding_draft",
    "get_onboarding_draft_statuses",
    "has_onboarding_draft",
    "load_onboarding_draft",
    "resolve_resume_target",
    "save_onboarding_draft",
]
