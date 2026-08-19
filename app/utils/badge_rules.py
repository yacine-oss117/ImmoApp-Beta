"""Rules for badge and label formatting."""

from __future__ import annotations

import re


def _normalize(flag: str, kind: str) -> str:
    f = (flag or "").strip().lower()
    if kind == "tz":
        if f in ("ipwho.is", "ipwhois", "ipwho"):
            return "auto"
    if kind == "time":
        if f in ("ntp", "ntp_seed", "seed", "network"):
            return "auto"
    if f in ("auto", "local", "system", "manual", "fail"):
        return f
    return "fail"


def _parse_flags(note: str) -> tuple[str, str]:
    n = (note or "").lower()
    tz_m = re.search(r"tz\s*=\s*([a-z_.]+)", n)
    tm_m = re.search(r"time\s*=\s*([a-z_.]+)", n)
    tz_raw = tz_m.group(1) if tz_m else "fail"
    tm_raw = tm_m.group(1) if tm_m else "fail"
    tz = _normalize(tz_raw, "tz")
    tm = _normalize(tm_raw, "time")
    return tz, tm


# Colors:
# GREEN  : tz=auto AND time=auto
# ORANGE : exactly one is auto (and none is 'fail' or 'manual')
# RED    : if any is 'fail' OR any is 'manual' OR neither is auto
def badge_state(note: str) -> str:
    """Evaluate a status note to determine the color of the sync indicator badge."""
    tz, tm = _parse_flags(note)
    is_auto_tz = tz == "auto"
    is_auto_tm = tm == "auto"
    if is_auto_tz and is_auto_tm:
        return "green"
    if (
        (is_auto_tz ^ is_auto_tm)
        and (tz not in ("fail", "manual"))
        and (tm not in ("fail", "manual"))
    ):
        return "orange"
    return "red"
