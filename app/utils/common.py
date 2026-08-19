"""Common formatting, parsing, and validation helpers (client-side)."""

from __future__ import annotations

import logging
import re
import unicodedata
from datetime import datetime

logger = logging.getLogger(__name__)

_SPECIAL_FOLD_MAP = str.maketrans({"\u0131": "i"})


def remove_diacritics(text: str) -> str:
    """Remove diacritical marks (accents) from text."""
    if not text:
        return ""
    nfkd = unicodedata.normalize("NFKD", text)
    stripped = "".join(ch for ch in nfkd if not unicodedata.combining(ch))
    return stripped.translate(_SPECIAL_FOLD_MAP)


def norm_text(text: str) -> str:
    """Normalize text: lowercase, strip, remove diacritics."""
    return remove_diacritics((text or "").strip().lower())


def display_wilaya(value: str | None) -> str:
    """Return canonical wilaya display name using API lookup when possible."""
    if not value:
        return ""
    text = str(value).strip()
    if not text:
        return ""

    # If already in display form ("Name - 16"), keep as is.
    if "-" in text and any(ch.isdigit() for ch in text):
        return text

    try:
        wilaya_id = int(text)
    except ValueError:
        wilaya_id = None

    try:
        from app.services.lookup_service import get_all_wilayas, get_wilaya_name

        if wilaya_id is not None:
            name = get_wilaya_name(wilaya_id)
            if name:
                for cached_id, cached_name, code in get_all_wilayas():
                    if cached_id == wilaya_id:
                        return _format_wilaya_label(cached_name, code)
                return name

        normalized = norm_text(text)
        for _, name, code in get_all_wilayas():
            if norm_text(name) == normalized:
                return _format_wilaya_label(name, code)
    except Exception:
        # Fall back to raw value if API lookups are unavailable.
        pass

    return text


def _format_wilaya_label(name: str, code: str) -> str:
    if code:
        return f"{name} - {code}"
    return name


def split_location_tokens(text: str) -> list[str]:
    """
    Split multi-location strings using explicit separators.

    NOTE: Commas are part of the canonical location format
    ("Commune, Wilaya - Code"), so we never split on commas.
    """
    if not text:
        return []
    if any(sep in text for sep in (";", "\n", "|")):
        parts = re.split(r"[;\n|]+", text)
    else:
        parts = [text]
    return [part.strip() for part in parts if part.strip()]


def split_locs(text: str) -> list[str]:
    """Split locations into normalized tokens for matching."""
    return [norm_text(item) for item in split_location_tokens(text)]


def phone_digits(text: str) -> str:
    """Extract only digits from phone number."""
    return re.sub(r"\D", "", (text or "").strip())


def fmt_int_group(value: float | None) -> str:
    """Format number with French-style grouping (space as thousand separator)."""
    if value is None:
        return ""
    try:
        return f"{int(float(value)):,}".replace(",", " ")
    except (TypeError, ValueError) as exc:
        logger.debug("fmt_int_group failed for %r: %s", value, exc)
        return ""


def coerce_number(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    text = text.replace(" ", "")
    match = re.search(r"-?\d+(?:[.,]\d+)?", text)
    if not match:
        return None
    raw = match.group(0)
    if "," in raw and "." in raw:
        raw = raw.replace(",", "")
    elif "," in raw and "." not in raw:
        parts = raw.split(",")
        if len(parts[-1]) == 3:
            raw = "".join(parts)
        else:
            raw = raw.replace(",", ".")
    try:
        return float(raw)
    except ValueError as exc:
        logger.debug("Failed to coerce number from %r: %s", value, exc)
        return None


def _coerce_number(value: object) -> float | None:
    """Backward-compatible alias for coerce_number."""
    return coerce_number(value)


def ensure_non_negative(value: object, field: str) -> object:
    """Raise ValueError if a numeric value is negative."""
    num = coerce_number(value)
    if num is not None and num < 0:
        raise ValueError(f"{field} cannot be negative.")
    return value


def ensure_min_le_max(
    min_value: object,
    max_value: object,
    min_field: str,
    max_field: str,
    zero_is_unset: bool = False,
) -> None:
    """Raise ValueError when a min value is greater than its max value."""
    min_num = coerce_number(min_value)
    max_num = coerce_number(max_value)
    if min_num is None or max_num is None:
        return
    if zero_is_unset and (min_num <= 0 or max_num <= 0):
        return
    if min_num > max_num:
        raise ValueError(f"{min_field} cannot be greater than {max_field}.")


def _unit_info(num: float) -> tuple[int, str, int]:
    abs_num = abs(num)
    if abs_num >= 1_000_000_000:
        return 1_000_000_000, "B", 9
    if abs_num >= 1_000_000:
        return 1_000_000, "M", 6
    if abs_num >= 1_000:
        return 1_000, "k", 3
    return 1, "", 0


def _format_compact_value(num: float, unit: int, suffix: str, digits: int) -> str:
    sign = "-" if num < 0 else ""
    total = int(round(abs(num)))
    main = total // unit
    remainder = total % unit
    if remainder == 0:
        return f"{sign}{main}{suffix}"
    frac = f"{remainder:0{digits}d}".rstrip("0")
    return f"{sign}{main}.{frac}{suffix}"


def fmt_money_short(value: object, currency: str = "") -> str:
    """Format money with compact units (k/M/B)."""
    num = coerce_number(value)
    if num is None:
        return ""
    unit, suffix, digits = _unit_info(num)
    if unit == 1:
        formatted = f"{num:,.0f}".replace(",", " ")
    else:
        formatted = _format_compact_value(num, unit, suffix, digits)
    return f"{formatted} {currency}".strip()


def fmt_money_range(min_value: object, max_value: object, currency: str = "") -> str:
    """Format a money range with shared units when possible."""
    min_num = coerce_number(min_value)
    max_num = coerce_number(max_value)
    if min_num is None or max_num is None:
        return ""
    min_unit, min_suffix, min_digits = _unit_info(min_num)
    max_unit, max_suffix, max_digits = _unit_info(max_num)
    if min_suffix and min_suffix == max_suffix and min_unit == max_unit:
        formatted = (
            f"{_format_compact_value(min_num, min_unit, min_suffix, min_digits)} - "
            f"{_format_compact_value(max_num, max_unit, max_suffix, max_digits)}"
        )
    else:
        formatted = f"{fmt_money_short(min_num)} - {fmt_money_short(max_num)}"
    return f"{formatted} {currency}".strip()


def format_datetime(dt_str: str | None, location: str | None = None) -> str:
    """Format ISO 8601 datetime string to human-readable format."""
    if not dt_str:
        return ""

    try:
        clean = dt_str.replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(clean)
        except ValueError:
            if "+" in clean:
                clean = clean.rsplit("+", 1)[0]
            elif clean.count("-") > 2:
                parts = clean.rsplit("-", 1)
                if ":" in parts[-1]:
                    clean = parts[0]
            dt = datetime.fromisoformat(clean)
        result = dt.strftime("%Y-%m-%d %H:%M")
        if location:
            location_parts = [part.strip() for part in location.split(",")]
            if len(location_parts) >= 2:
                filtered = ", ".join(location_parts[-2:])
                result += f" ({filtered})"
            elif location_parts:
                result += f" ({location_parts[0]})"
        return result
    except (TypeError, ValueError) as exc:
        logger.warning("format_datetime failed for %r: %s", dt_str, exc)
        return dt_str
