"""Offline mode state storage (service-safe, no Qt dependency)."""

from __future__ import annotations

import json
import os
from typing import Any

from app.core_app.paths import config_path

_STATE_FILE = "client_state.json"
_OFFLINE_KEY = "offline_mode"


def _read_state() -> dict[str, Any]:
    path = config_path(_STATE_FILE)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_state(data: dict[str, Any]) -> None:
    path = config_path(_STATE_FILE)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=True), encoding="utf-8")


def get_offline_mode() -> bool:
    """Return True if offline mode is enabled (env overrides)."""
    env = os.environ.get("IMMOAPP_OFFLINE")
    if env is not None:
        return str(env).strip().lower() in {"1", "true", "yes", "on"}
    data = _read_state()
    return bool(data.get(_OFFLINE_KEY, False))


def set_offline_mode(enabled: bool) -> None:
    """Persist offline mode flag."""
    data = _read_state()
    data[_OFFLINE_KEY] = bool(enabled)
    _write_state(data)


__all__ = ["get_offline_mode", "set_offline_mode"]
