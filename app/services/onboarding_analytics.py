"""Local onboarding analytics and first-run state helpers."""

from __future__ import annotations

import json
import logging
import os
import re
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.core_app.paths import config_path, logs_dir

logger = logging.getLogger(__name__)

_STATE_FILE = "onboarding_state.json"
_EVENTS_FILE = "onboarding_events.jsonl"
_ENV_QUICK_START_ENABLED = "IMMOAPP_ENABLE_QUICK_START_CARD"
_ENV_ANALYTICS_DISABLED = "IMMOAPP_DISABLE_ONBOARDING_ANALYTICS"
_KEY_QUICK_START_SEEN = "quick_start_seen"
_KEY_ANALYTICS_ENABLED = "analytics_enabled"
_KEY_APP_LAUNCH_COUNT = "app_launch_count"
_KEY_NEXT_STEPS_DISMISSED = "next_steps_dismissed"
_SAFE_TEXT = re.compile(r"[^a-z0-9_.-]+")
_SAFE_METADATA_KEYS = frozenset({"reason", "mode", "channel", "variant"})
_EVENTS_LOCK = threading.Lock()
_MAX_EVENTS_LOG_BYTES = 1_000_000
_TRIM_KEEP_LINES = 4000


def _env_flag_enabled(name: str, *, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    return value in {"1", "true", "yes", "on"}


def _sanitize_text(value: object, *, default: str = "unknown") -> str:
    text = str(value or "").strip().lower()
    if not text:
        return default
    clean = _SAFE_TEXT.sub("_", text)
    if not clean:
        return default
    return clean[:64]


def _state_path() -> Path:
    return config_path(_STATE_FILE)


def _events_path() -> Path:
    path = logs_dir() / _EVENTS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _read_state() -> dict[str, Any]:
    path = _state_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.debug("Failed to read onboarding state file: %s", path, exc_info=True)
        return {}
    return data if isinstance(data, dict) else {}


def _write_state(data: dict[str, Any]) -> None:
    path = _state_path()
    tmp = path.with_suffix(".tmp")
    payload = json.dumps(data, indent=2, ensure_ascii=True)
    try:
        tmp.write_text(payload, encoding="utf-8")
        tmp.replace(path)
    except OSError:
        logger.warning("Failed to persist onboarding state", exc_info=True)


def is_quick_start_enabled() -> bool:
    """Return True when the quick-start chooser feature is enabled."""
    return _env_flag_enabled(_ENV_QUICK_START_ENABLED, default=True)


def has_seen_quick_start() -> bool:
    """Return True when the local client already showed the quick-start chooser."""
    state = _read_state()
    return bool(state.get(_KEY_QUICK_START_SEEN, False))


def mark_quick_start_seen(*, seen: bool = True) -> None:
    """Persist quick-start seen state."""
    state = _read_state()
    state[_KEY_QUICK_START_SEEN] = bool(seen)
    _write_state(state)


def reset_quick_start_seen() -> None:
    """Force the quick-start chooser to appear again."""
    mark_quick_start_seen(seen=False)


def should_show_quick_start() -> bool:
    """Return True for first-run quick-start display."""
    return is_quick_start_enabled() and not has_seen_quick_start()


def increment_app_launch_count() -> int:
    """Increment and return local app launch count."""
    state = _read_state()
    raw_count = state.get(_KEY_APP_LAUNCH_COUNT, 0)
    try:
        current = int(raw_count)
    except (TypeError, ValueError):
        current = 0
    current = max(0, current) + 1
    state[_KEY_APP_LAUNCH_COUNT] = current
    _write_state(state)
    return current


def get_app_launch_count() -> int:
    """Return local app launch count."""
    state = _read_state()
    raw_count = state.get(_KEY_APP_LAUNCH_COUNT, 0)
    try:
        return max(0, int(raw_count))
    except (TypeError, ValueError):
        return 0


def dismiss_next_steps_card(*, dismissed: bool = True) -> None:
    """Persist user preference for dashboard next-steps helper card."""
    state = _read_state()
    state[_KEY_NEXT_STEPS_DISMISSED] = bool(dismissed)
    _write_state(state)


def reset_next_steps_card() -> None:
    """Reset next-steps dismissal preference."""
    dismiss_next_steps_card(dismissed=False)


def should_show_next_steps_card(*, max_launches: int = 3) -> bool:
    """
    Return True when dashboard next-steps helper should be visible.

    The card appears on early launches unless explicitly dismissed.
    """
    state = _read_state()
    if bool(state.get(_KEY_NEXT_STEPS_DISMISSED, False)):
        return False
    launch_count = get_app_launch_count()
    return launch_count <= max(1, int(max_launches))


def is_onboarding_analytics_enabled() -> bool:
    """Return True when local onboarding analytics logging is enabled."""
    if _env_flag_enabled(_ENV_ANALYTICS_DISABLED, default=False):
        return False
    state = _read_state()
    if _KEY_ANALYTICS_ENABLED not in state:
        return True
    return bool(state.get(_KEY_ANALYTICS_ENABLED))


def set_onboarding_analytics_enabled(enabled: bool) -> None:
    """Persist opt-in/out value for onboarding analytics logging."""
    state = _read_state()
    state[_KEY_ANALYTICS_ENABLED] = bool(enabled)
    _write_state(state)


def record_onboarding_event(
    event: str,
    *,
    step: str = "",
    outcome: str = "",
    source: str = "client",
    metadata: dict[str, object] | None = None,
) -> None:
    """
    Append a local onboarding event log entry.

    This log intentionally excludes PII and only stores normalized labels.
    """
    if not is_onboarding_analytics_enabled():
        return
    entry: dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "event": _sanitize_text(event),
        "step": _sanitize_text(step, default=""),
        "outcome": _sanitize_text(outcome, default=""),
        "source": _sanitize_text(source),
    }
    if metadata:
        safe_meta: dict[str, str] = {}
        for raw_key, raw_value in metadata.items():
            key = _sanitize_text(raw_key, default="")
            if not key or key not in _SAFE_METADATA_KEYS:
                continue
            safe_meta[key] = _sanitize_text(raw_value, default="")
        if safe_meta:
            entry["meta"] = safe_meta
    line = json.dumps(entry, ensure_ascii=True, separators=(",", ":"))
    path = _events_path()
    try:
        with _EVENTS_LOCK:
            _trim_events_file_if_needed(path)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(line)
                handle.write("\n")
    except OSError:
        logger.debug("Failed to append onboarding event", exc_info=True)


def get_onboarding_funnel_snapshot(*, lookback_days: int = 7) -> dict[str, int]:
    """
    Build a lightweight onboarding funnel summary from local event logs.

    Returned counters are best-effort and designed for UX insights, not billing.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, int(lookback_days)))
    counts: dict[str, int] = {
        "register_started": 0,
        "register_completed": 0,
        "register_abandoned": 0,
        "activate_started": 0,
        "activate_completed": 0,
        "activate_abandoned": 0,
        "join_started": 0,
        "join_completed": 0,
        "join_abandoned": 0,
        "resume_available": 0,
        "resume_opened": 0,
    }
    for event in _iter_recent_events(cutoff):
        if event == "register_dialog_opened":
            counts["register_started"] += 1
        elif event == "register_succeeded":
            counts["register_completed"] += 1
        elif event == "register_abandoned":
            counts["register_abandoned"] += 1
        elif event == "activate_dialog_opened":
            counts["activate_started"] += 1
        elif event == "activate_succeeded":
            counts["activate_completed"] += 1
        elif event == "activate_abandoned":
            counts["activate_abandoned"] += 1
        elif event == "join_dialog_opened":
            counts["join_started"] += 1
        elif event == "join_succeeded":
            counts["join_completed"] += 1
        elif event == "join_abandoned":
            counts["join_abandoned"] += 1
        elif event == "resume_setup_available":
            counts["resume_available"] += 1
        elif event == "resume_setup_opened":
            counts["resume_opened"] += 1
    counts["register_dropoff"] = max(0, counts["register_started"] - counts["register_completed"])
    counts["activate_dropoff"] = max(0, counts["activate_started"] - counts["activate_completed"])
    counts["join_dropoff"] = max(0, counts["join_started"] - counts["join_completed"])
    return counts


def _iter_recent_events(cutoff: datetime) -> list[str]:
    path = _events_path()
    if not path.exists():
        return []
    try:
        with _EVENTS_LOCK:
            lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out: list[str] = []
    for line in lines[-5000:]:
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if not isinstance(row, dict):
            continue
        raw_event = str(row.get("event") or "").strip().lower()
        raw_ts = str(row.get("ts") or "").strip()
        if not raw_event or not raw_ts:
            continue
        try:
            ts = datetime.fromisoformat(raw_ts)
        except ValueError:
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        else:
            ts = ts.astimezone(timezone.utc)
        if ts >= cutoff:
            out.append(raw_event)
    return out


def _trim_events_file_if_needed(path: Path) -> None:
    try:
        if not path.exists():
            return
        if path.stat().st_size <= _MAX_EVENTS_LOG_BYTES:
            return
        lines = path.read_text(encoding="utf-8").splitlines()
        if len(lines) <= _TRIM_KEEP_LINES:
            return
        trimmed = "\n".join(lines[-_TRIM_KEEP_LINES:]) + "\n"
        path.write_text(trimmed, encoding="utf-8")
    except OSError:
        logger.debug("Failed to trim onboarding events file", exc_info=True)


__all__ = [
    "dismiss_next_steps_card",
    "get_onboarding_funnel_snapshot",
    "get_app_launch_count",
    "has_seen_quick_start",
    "increment_app_launch_count",
    "is_onboarding_analytics_enabled",
    "is_quick_start_enabled",
    "mark_quick_start_seen",
    "record_onboarding_event",
    "reset_next_steps_card",
    "reset_quick_start_seen",
    "set_onboarding_analytics_enabled",
    "should_show_next_steps_card",
    "should_show_quick_start",
]
