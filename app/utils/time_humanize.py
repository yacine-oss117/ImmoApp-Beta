"""User-facing relative time formatting helpers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


def _parse_datetime(value: str | datetime | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).strip()
    if not text:
        return None
    clean = text.replace("Z", "+00:00")
    try:
        as_epoch = float(clean)
        return datetime.fromtimestamp(as_epoch, tz=timezone.utc)
    except ValueError:
        pass
    try:
        parsed = datetime.fromisoformat(clean)
    except ValueError:
        try:
            parsed = datetime.strptime(text, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def humanize_relative(value: str | datetime | None) -> str:
    dt = _parse_datetime(value)
    if dt is None:
        return ""
    now = datetime.now(timezone.utc)
    delta = now - dt
    if delta < timedelta(minutes=1):
        return "just now"
    if delta < timedelta(hours=1):
        minutes = max(1, int(delta.total_seconds() // 60))
        unit = "minute" if minutes == 1 else "minutes"
        return f"{minutes} {unit} ago"
    if delta < timedelta(days=1):
        hours = max(1, int(delta.total_seconds() // 3600))
        unit = "hour" if hours == 1 else "hours"
        return f"{hours} {unit} ago"
    if delta < timedelta(days=2):
        return dt.astimezone().strftime("Yesterday at %I:%M %p").lstrip("0")
    if delta < timedelta(days=7):
        days = int(delta.total_seconds() // 86400)
        unit = "day" if days == 1 else "days"
        return f"{days} {unit} ago"
    return dt.astimezone().strftime("%B %d")


def humanize_date_short(value: str | datetime | None) -> str:
    dt = _parse_datetime(value)
    if dt is None:
        return ""
    return dt.astimezone().strftime("%b %d, %I:%M %p").lstrip("0")


__all__ = ["humanize_date_short", "humanize_relative"]
