"""Shared helpers for time_service that keep the public API concise."""

from __future__ import annotations

import logging
import time as _time
from types import ModuleType
from typing import TypeVar, cast

import ntplib
from PySide6.QtCore import QSettings

logger = logging.getLogger(__name__)

zoneinfo: ModuleType | None
try:
    import zoneinfo as _zoneinfo
except ImportError:
    logger.warning("zoneinfo import failed", exc_info=True)
    zoneinfo = None
else:
    zoneinfo = _zoneinfo


def _normalize_iana_id(s: str) -> str | None:
    """Convert loose user input into a likely IANA tz id."""
    if not s:
        return None
    raw = s.strip().replace("\\", "/").replace(" ", "_")
    parts = [p for p in raw.split("/") if p]
    if len(parts) < 2:
        return None
    region = parts[0].strip()
    city = "/".join(parts[1:])

    def title_underscore(x: str) -> str:
        """Capitalize each part of an underscore-separated string."""
        return "_".join([w.capitalize() for w in x.split("_") if w])

    candidate = f"{region.capitalize()}/{title_underscore(city)}"
    try:
        allzones = zoneinfo.available_timezones() if zoneinfo else set()
    except (RuntimeError, OSError, ValueError):
        logger.warning("zoneinfo listing failed", exc_info=True)
        allzones = set()
    if candidate in allzones:
        return candidate
    region_tc = title_underscore(region)
    candidate2 = f"{region_tc}/{title_underscore(city)}"
    if candidate2 in allzones:
        return candidate2
    return None


def _fmt_city_region(tzid: str) -> str:
    if not tzid:
        return ""
    parts = tzid.split("/", 1)
    if len(parts) == 2:
        region, city = parts[0], parts[1]
        city = city.replace("_", " ")
        region = region.replace("_", " ")
        return f"{city} | {region}"
    return tzid.replace("_", " ")


def _fmt_region_city(tzid: str) -> str:
    return (tzid or "").strip()


def _local_iana_tz() -> str | None:
    try:
        import tzlocal

        try:
            name = tzlocal.get_localzone_name()
            if isinstance(name, str) and name:
                return name
        except (AttributeError, OSError, RuntimeError):
            logger.warning("Time service fallback", exc_info=True)
        try:
            z = tzlocal.get_localzone()
            for attr in ("key", "zone", "zonefile"):
                v = getattr(z, attr, None)
                if isinstance(v, str) and v:
                    return v
            s = str(z)
            if s and "/" in s:
                return s
        except (AttributeError, OSError, RuntimeError):
            logger.warning("Time service fallback", exc_info=True)
    except (ImportError, AttributeError, OSError, RuntimeError):
        logger.warning("Time service fallback", exc_info=True)
    try:
        import datetime as _dt

        dt = _dt.datetime.now().astimezone()
        key = getattr(dt.tzinfo, "key", None)
        if isinstance(key, str) and key:
            return key
        zone = getattr(dt.tzinfo, "zone", None)
        if isinstance(zone, str) and zone:
            return zone
    except (AttributeError, OSError, RuntimeError):
        logger.warning("Time service fallback", exc_info=True)
    return None


def _get_ntp_epoch(timeout: float = 1.5) -> float | None:
    try:
        c = ntplib.NTPClient()
        r = c.request("pool.ntp.org", version=3, timeout=timeout)
        return float(r.tx_time)
    except (ntplib.NTPException, OSError, RuntimeError, ValueError):
        logger.info("NTP request unavailable; using cached or system time fallback.")
        logger.debug("NTP request failure details", exc_info=True)
        return None


def _get_system_tz() -> str | None:
    """Return the system timezone without network access."""
    return _local_iana_tz()


T = TypeVar("T")


def _read(s: QSettings, key: str, default: T, type_: type[T] | None = None) -> T:
    try:
        if type_ is not None:
            return cast(T, s.value(key, default, type=type_))
        return cast(T, s.value(key, default))
    except (RuntimeError, TypeError, ValueError):
        logger.warning("Settings read failed for %s", key, exc_info=True)
        return default


def _store_seed(s: QSettings, epoch_utc: float, origin: str, mono: float | None = None) -> None:
    s.setValue("cache/ntp_seed_epoch", int(epoch_utc))
    s.setValue("cache/ntp_seed_mono", float(_time.perf_counter() if mono is None else mono))
    s.setValue("cache/ntp_seed_origin", str(origin))
