"""UI capability probing with offline cache fallback."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from app.core_app.paths import get_app_data_dir
from app.services.audit_repository import count_audit_logs
from app.services.security_repository import permissions_matrix
from app.utils.qt_async import run_background_result

logger = logging.getLogger(__name__)

_CACHE_VERSION = 1
_CACHE_FILE = "ui_capabilities_cache_v1.json"
_memory_cache: dict[str, UiCapabilities] = {}


@dataclass(frozen=True)
class UiCapabilities:
    can_manage_team: bool = False
    can_view_activity: bool = False
    can_view_security: bool = False
    can_open_admin_tools: bool = False


def capabilities_cache_path() -> Path:
    path = get_app_data_dir() / "cache" / _CACHE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def normalize_account_key(
    *,
    api_base: str | None,
    username: str | None = None,
    agency_id: int | None = None,
    user_id: int | None = None,
) -> str:
    base = (api_base or "").strip().lower().rstrip("/")
    if isinstance(agency_id, int) and agency_id > 0 and isinstance(user_id, int) and user_id > 0:
        return f"{base}|{agency_id}|{user_id}"
    user = (username or "").strip().lower()
    return f"{base}|{user}"


def load_capabilities(account_key: str) -> UiCapabilities:
    if account_key in _memory_cache:
        return _memory_cache[account_key]
    cached = _load_cached(account_key)
    _memory_cache[account_key] = cached
    return cached


def refresh_capabilities_async(
    account_key: str,
    callback: Callable[[UiCapabilities], None] | None = None,
) -> None:
    def _work() -> UiCapabilities:
        return _probe_capabilities()

    def _on_success(capabilities: UiCapabilities) -> None:
        _memory_cache[account_key] = capabilities
        _store_cached(account_key, capabilities)
        if callback is not None:
            callback(capabilities)

    def _on_error(exc: Exception) -> None:
        logger.debug("UI capability probe failed: %s", exc)
        fallback = load_capabilities(account_key)
        if callback is not None:
            callback(fallback)

    run_background_result(_work, _on_success, _on_error)


def clear_memory_capabilities(account_key: str) -> None:
    _memory_cache.pop(account_key, None)


def _probe_capabilities() -> UiCapabilities:
    can_manage_team = _try_probe(_probe_manage_team)
    can_view_activity = _try_probe(_probe_activity)
    can_view_security = _try_probe(_probe_security)
    can_open_admin_tools = can_manage_team and can_view_activity and can_view_security
    return UiCapabilities(
        can_manage_team=can_manage_team,
        can_view_activity=can_view_activity,
        can_view_security=can_view_security,
        can_open_admin_tools=can_open_admin_tools,
    )


def _probe_manage_team() -> bool:
    # The permissions matrix endpoint is manager-gated and sufficient for
    # capability detection without forcing an extra /users probe.
    _ = permissions_matrix()
    return True


def _probe_activity() -> bool:
    _ = count_audit_logs()
    return True


def _probe_security() -> bool:
    _ = permissions_matrix()
    return True


def _try_probe(func: Callable[[], bool]) -> bool:
    try:
        return bool(func())
    except Exception:
        return False


def _load_cached(account_key: str) -> UiCapabilities:
    data = _read_cache_file()
    if not data:
        return UiCapabilities()
    entries = data.get("entries")
    if not isinstance(entries, dict):
        return UiCapabilities()
    raw = entries.get(account_key)
    if not isinstance(raw, dict):
        return UiCapabilities()
    return UiCapabilities(
        can_manage_team=bool(raw.get("can_manage_team")),
        can_view_activity=bool(raw.get("can_view_activity")),
        can_view_security=bool(raw.get("can_view_security")),
        can_open_admin_tools=bool(raw.get("can_open_admin_tools")),
    )


def _store_cached(account_key: str, capabilities: UiCapabilities) -> None:
    path = capabilities_cache_path()
    data = _read_cache_file() or {"version": _CACHE_VERSION, "updated_at": 0.0, "entries": {}}
    entries = data.get("entries")
    if not isinstance(entries, dict):
        entries = {}
    entries[account_key] = asdict(capabilities)
    data["entries"] = entries
    data["version"] = _CACHE_VERSION
    data["updated_at"] = time.time()

    tmp_path = path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(data, indent=2, ensure_ascii=True), encoding="utf-8")
    tmp_path.replace(path)


def _read_cache_file() -> dict[str, Any] | None:
    path = capabilities_cache_path()
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict):
        return None
    return raw


__all__ = [
    "UiCapabilities",
    "capabilities_cache_path",
    "clear_memory_capabilities",
    "load_capabilities",
    "normalize_account_key",
    "refresh_capabilities_async",
]
