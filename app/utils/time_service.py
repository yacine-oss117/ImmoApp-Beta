"""Time and timezone helpers."""

from __future__ import annotations

import logging
import time as _time
from datetime import datetime, timezone

from PySide6.QtCore import QSettings

from app.constants import APP, ORG
from app.utils.time_service_helpers import (
    _fmt_city_region,
    _fmt_region_city,
    _get_ntp_epoch,
    _get_system_tz,
    _local_iana_tz,
    _normalize_iana_id,
    _read,
    _store_seed,
    zoneinfo,
)

logger = logging.getLogger(__name__)

__all__ = [
    "authoritative_now",
    "clear_manual_clock",
    "get_system_tz",
    "get_ntp_epoch",
    "maybe_resync_if_due",
    "apply_auto_tz_refresh_result",
    "refresh_auto_tz_if_due",
    "should_refresh_auto_tz",
    "set_manual_clock_from_local",
    "_local_iana_tz",
    "_fmt_city_region",
    "_fmt_region_city",
    "_normalize_iana_id",
]


def refresh_auto_tz_if_due(timeout: float = 5.0, force: bool = False) -> str:
    """
    Best-effort local timezone refresh; updates cache/tz_name when available.
    Returns a status string.
    """
    s = QSettings(ORG, APP)
    offline_mode = bool(_read(s, "time/offline_mode", False, bool))
    auto_tz = bool(_read(s, "time/auto_detect_tz", True, bool))
    if offline_mode or not auto_tz:
        return "skipped"

    last = float(_read(s, "cache/tz_refresh_mono", 0.0, float) or 0.0)
    nowm = _time.perf_counter()
    # refresh every 6 hours unless forced
    if not force and last and (nowm - last) < 6 * 3600:
        return "not_due"

    tz_try = _get_system_tz()
    if tz_try:
        s.setValue("cache/tz_name", tz_try)
        s.setValue("cache/tz_refresh_mono", float(nowm))
        s.setValue("cache/tz_refresh_status", "updated")
        return "updated"
    s.setValue("cache/tz_refresh_status", "fail")
    return "fail"


def should_refresh_auto_tz(force: bool = False) -> bool:
    """Return True when auto timezone refresh should run."""
    s = QSettings(ORG, APP)
    offline_mode = bool(_read(s, "time/offline_mode", False, bool))
    auto_tz = bool(_read(s, "time/auto_detect_tz", True, bool))
    if offline_mode or not auto_tz:
        return False

    last = float(_read(s, "cache/tz_refresh_mono", 0.0, float) or 0.0)
    nowm = _time.perf_counter()
    if not force and last and (nowm - last) < 6 * 3600:
        return False
    return True


def apply_auto_tz_refresh_result(tz_name: str | None, nowm: float | None = None) -> str:
    """Persist auto timezone refresh results to settings."""
    s = QSettings(ORG, APP)
    timestamp = float(nowm if nowm is not None else _time.perf_counter())
    if tz_name:
        s.setValue("cache/tz_name", tz_name)
        s.setValue("cache/tz_refresh_mono", timestamp)
        s.setValue("cache/tz_refresh_status", "updated")
        return "updated"
    s.setValue("cache/tz_refresh_status", "fail")
    return "fail"


def get_ntp_epoch() -> float | None:
    """Public wrapper around the NTP epoch fetcher."""
    return _get_ntp_epoch()


def get_system_tz() -> str | None:
    """Return the system timezone without network access."""
    return _get_system_tz()


# ---------------- Core: authoritative_now ----------------
# Emits: note = 'flags: tz={auto|local|system|manual|fail}; time={auto|local|system|manual|fail}'
def authoritative_now(allow_network: bool = True) -> tuple[datetime, str]:
    """Return the current time and a status note after evaluating all clock sources."""
    s = QSettings(ORG, APP)

    # toggles
    use_ntp = bool(_read(s, "time/use_ntp", True, bool))
    ntp_local_ok = bool(_read(s, "time/use_ntp_local", True, bool))
    auto_tz = bool(_read(s, "time/auto_detect_tz", True, bool))
    force_manual_tz = bool(_read(s, "time/force_manual_tz", False, bool))
    offline_mode = bool(_read(s, "time/offline_mode", False, bool))
    allow_network = allow_network and (not offline_mode)

    manual_tz_raw = (_read(s, "time/manual_tz", "", str) or "").strip()
    manual_tz = _normalize_iana_id(manual_tz_raw) or manual_tz_raw
    if manual_tz != manual_tz_raw:
        s.setValue("time/manual_tz", manual_tz)

    manual_clock_enabled = bool(_read(s, "time/manual_clock_enabled", False, bool))

    # time seeds
    seed_epoch = int(_read(s, "cache/ntp_seed_epoch", 0, int) or 0)
    seed_mono = float(_read(s, "cache/ntp_seed_mono", 0.0, float) or 0.0)
    seed_origin = (_read(s, "cache/ntp_seed_origin", "unknown", str) or "unknown").lower()

    man_epoch = int(_read(s, "cache/manual_clock_epoch", 0, int) or 0)
    man_mono = float(_read(s, "cache/manual_seed_mono", 0.0, float) or 0.0)

    # ---- TIME: auto -> local -> system -> manual ----
    time_flag = "fail"
    utc_now: float | None = None

    if use_ntp:
        if seed_epoch > 0 and seed_mono > 0.0 and seed_origin == "ntp":
            utc_now = float(seed_epoch) + (_time.perf_counter() - float(seed_mono))
            time_flag = "auto"
        elif allow_network:
            ep = _get_ntp_epoch()
            if ep:
                _store_seed(s, ep, origin="ntp")
                utc_now = float(ep)
                time_flag = "auto"

    if utc_now is None and ntp_local_ok and (seed_epoch > 0 and seed_mono > 0.0):
        utc_now = float(seed_epoch) + (_time.perf_counter() - float(seed_mono))
        time_flag = "local"

    if utc_now is None:
        try:
            utc_now = datetime.now(timezone.utc).timestamp()
            _store_seed(s, utc_now, origin="system")
            time_flag = "system"
        except (OSError, RuntimeError, ValueError):
            logger.warning("System time seed failed", exc_info=True)
            utc_now = None

    if utc_now is None and manual_clock_enabled and (man_epoch > 0 and man_mono > 0.0):
        utc_now = float(man_epoch) + (_time.perf_counter() - float(man_mono))
        time_flag = "manual"

    if utc_now is None:
        utc_now = _time.time()
        time_flag = "fail"

    dt_utc = datetime.fromtimestamp(utc_now, tz=timezone.utc)

    # ---- TZ: auto -> local -> system -> manual, with explicit override
    tz_flag = "fail"
    local_dt: datetime | None = None

    if force_manual_tz and manual_tz and zoneinfo is not None:
        try:
            local_dt = dt_utc.astimezone(zoneinfo.ZoneInfo(manual_tz))
            tz_flag = "manual"
        except (RuntimeError, ValueError):
            logger.warning("Manual timezone conversion failed", exc_info=True)
            local_dt = None

    if local_dt is None and auto_tz:
        tz_name = (_read(s, "cache/tz_name", "", str) or "").strip()
        if not tz_name and allow_network:
            tz_try = _get_system_tz()
            if tz_try:
                tz_name = tz_try
                s.setValue("cache/tz_name", tz_name)
        if tz_name and zoneinfo is not None:
            try:
                local_dt = dt_utc.astimezone(zoneinfo.ZoneInfo(tz_name))
                tz_flag = "auto"
            except (RuntimeError, ValueError):
                logger.warning("Time service fallback", exc_info=True)

    if local_dt is None:
        try:
            local_dt = dt_utc.astimezone()
            key = getattr(local_dt.tzinfo, "key", None)
            if key and tz_flag == "fail":
                tz_flag = "local"
        except (RuntimeError, ValueError):
            logger.warning("Local timezone conversion failed", exc_info=True)
            local_dt = None

    if local_dt is None:
        try:
            local_dt = dt_utc.astimezone()
            if tz_flag == "fail":
                tz_flag = "system"
        except (RuntimeError, ValueError):
            logger.warning("System timezone conversion failed", exc_info=True)
            local_dt = None

    if local_dt is None and manual_tz and zoneinfo is not None:
        try:
            local_dt = dt_utc.astimezone(zoneinfo.ZoneInfo(manual_tz))
            tz_flag = "manual"
        except (RuntimeError, ValueError):
            logger.warning("Time service fallback", exc_info=True)

    if local_dt is None:
        local_dt = dt_utc
        if tz_flag == "fail":
            tz_flag = "system"

    note = f"flags: tz={tz_flag}; time={time_flag}"
    return local_dt, note


def maybe_resync_if_due(allow_network: bool = True) -> str:
    """Trigger a network time re-synchronization if the configured interval has passed."""
    s = QSettings(ORG, APP)
    offline_mode = bool(_read(s, "time/offline_mode", False, bool))
    if offline_mode:
        return "offline"
    use_ntp = bool(_read(s, "time/use_ntp", True, bool))
    if not use_ntp:
        return "disabled_ntp"
    enabled = bool(_read(s, "time/ntp_resync_enabled", True, bool))
    if not enabled:
        return "disabled"
    if not allow_network:
        return "skipped_network"
    hours = int(_read(s, "time/ntp_resync_hours", 3, int) or 3)
    due_sec = max(1, hours) * 3600
    last = float(_read(s, "cache/resync_last_mono", 0.0, float) or 0.0)
    last_fail = float(_read(s, "cache/resync_last_fail", 0.0, float) or 0.0)
    nowm = _time.perf_counter()
    # Avoid hammering NTP servers after a failure; quick retry after a short pause.
    FAIL_BACKOFF_SEC = 300.0
    if last_fail and (nowm - last_fail) < FAIL_BACKOFF_SEC:
        return "fail_backoff"
    if last and (nowm - last) < due_sec:
        return "not_due"
    ep = _get_ntp_epoch()
    if not ep:
        s.setValue("cache/resync_last_fail", float(nowm))
        return "ntp_fail"
    s.setValue("cache/resync_last_mono", float(nowm))
    s.setValue("cache/resync_last_fail", 0.0)
    _store_seed(s, ep, origin="ntp", mono=nowm)
    return "snap"


def set_manual_clock_from_local(dt_local_iso: str) -> None:
    """Manually override the system clock for debugging or testing purposes."""
    s = QSettings(ORG, APP)
    try:
        from datetime import datetime as _dt

        naive = _dt.strptime(dt_local_iso.strip(), "%Y-%m-%d %H:%M:%S")
        local = naive.astimezone()
        epoch = local.astimezone(timezone.utc).timestamp()
        s.setValue("cache/manual_clock_epoch", int(epoch))
        s.setValue("cache/manual_seed_mono", float(_time.perf_counter()))
    except (ValueError, RuntimeError):
        logger.warning("Manual clock parse failed", exc_info=True)
        s.setValue("cache/manual_clock_epoch", 0)
        s.setValue("cache/manual_seed_mono", 0.0)


def clear_manual_clock() -> None:
    """Reset the clock to automatic/system mode, removing any manual overrides."""
    s = QSettings(ORG, APP)
    s.setValue("cache/manual_clock_epoch", 0)
    s.setValue("cache/manual_seed_mono", 0.0)
