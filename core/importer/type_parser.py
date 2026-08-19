"""
Centralized Type Parser for importing raw string data.

This module is responsible for safely converting raw strings (from CSV/Excel/ODS)
into Python native types (int, float, bool, date) during the import process.

Differentiation from TYPE_CHECKING:
- TYPE_CHECKING is for static analysis (mypy/IDE) to check code structure *before* running.
- This TypeParser is for *runtime* conversion of actual data values processing.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime
from decimal import Decimal

from core.importer.normalizers.text_utils import convert_arabic_digits

logger = logging.getLogger(__name__)

# Compile regex for performance
_BOOL_TRUE_RE = re.compile(r"^(yes|true|1|on|oui|y|t)$", re.IGNORECASE)
_BOOL_FALSE_RE = re.compile(r"^(no|false|0|off|non|n|f)$", re.IGNORECASE)
_INT_CLEAN_RE = re.compile(r"[^\d-]")
_FLOAT_CLEAN_RE = re.compile(r"[^\d\.-]")


class TypeParser:
    """Static utility for parsing raw strings into domain types."""

    @staticmethod
    def _get_multiplier(value: str) -> tuple[str, float]:
        """Extract multiplier suffix (k, m, b) and return clean string + multiplier."""
        normalized_value = convert_arabic_digits(str(value).strip())
        s_val = normalized_value.lower()
        if s_val.endswith("k"):
            return s_val[:-1], 1_000.0
        if s_val.endswith("m"):
            return s_val[:-1], 1_000_000.0
        if s_val.endswith("b"):
            return s_val[:-1], 1_000_000_000.0
        return normalized_value, 1.0

    @staticmethod
    def parse_int(value: str | None, default: int | None = 0) -> int | None:
        """Parse string to integer, handling cleanup of spaces/symbols."""
        if not value:
            return default

        # Handle multipliers for prices (e.g. 1.5M)
        s_val, multiplier = TypeParser._get_multiplier(str(value).strip())

        # Fast path for pure digits (if no multiplier)
        if multiplier == 1.0 and s_val.isdigit():
            return int(s_val)

        # Clean string (remove spaces, currency symbols, etc)
        # Keep only digits, dot, comma, minus
        clean_base = _INT_CLEAN_RE.sub("", s_val)
        if not clean_base:
            return default

        try:
            # Re-use float logic for the numeric part (handles 1.200,50 vs 1,200.50)
            f_val = TypeParser.calculate_float_value(s_val)
            if f_val is None:
                return default

            return int(f_val * multiplier)
        except (ValueError, TypeError):
            return default

    @staticmethod
    def parse_float(value: str | None, default: float | None = 0.0) -> float | None:
        """Parse string to float."""
        if not value:
            return default

        s_val, multiplier = TypeParser._get_multiplier(str(value).strip())

        f_val = TypeParser.calculate_float_value(s_val)
        if f_val is None:
            return default

        return f_val * multiplier

    @staticmethod
    def calculate_float_value(value: str) -> float | None:
        """Core float parsing logic handling delimiters (dot vs comma)."""
        try:
            s_val = convert_arabic_digits(str(value).strip())

            # Complex case: contains both . and ,
            if "," in s_val and "." in s_val:
                # Heuristic: the last one is likely the decimal separator
                last_comma = s_val.rfind(",")
                last_dot = s_val.rfind(".")

                if last_comma > last_dot:
                    # Euro style: 1.200,50 -> Remove dots, replace comma with dot
                    s_val = s_val.replace(".", "").replace(",", ".")
                else:
                    # US style: 1,200.50 -> Remove commas
                    s_val = s_val.replace(",", "")

            elif "," in s_val:
                comma_candidate = re.sub(r"[^\d,-]", "", s_val)
                if re.fullmatch(r"-?\d{1,3}(?:,\d{3})+", comma_candidate):
                    s_val = s_val.replace(",", "")
                elif re.fullmatch(r"-?\d+,\d{1,2}", comma_candidate):
                    s_val = s_val.replace(",", ".")
                else:
                    s_val = s_val.replace(",", ".")

            # Remove everything except digits, dot, minus
            clean = _FLOAT_CLEAN_RE.sub("", s_val)
            if not clean:
                return None

            return float(clean)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def parse_decimal(value: str | None, default: Decimal | None = None) -> Decimal:
        """Parse string to Decimal for currency."""
        if default is None:
            default = Decimal("0.00")

        if not value:
            return default

        # For decimal, we might need a similar multiplier logic, but usually Decimal is passed cleaned.
        # Let's support multipliers here too for consistency.
        s_val, multiplier = TypeParser._get_multiplier(str(value).strip())

        f_val = TypeParser.calculate_float_value(s_val)
        if f_val is None:
            return default

        return Decimal(str(f_val * multiplier))

    @staticmethod
    def parse_bool(value: str | None, default: bool | None = False) -> bool | None:
        """Parse fuzzy boolean values (yes/no, 1/0, true/false)."""
        if not value:
            return default

        s_val = str(value).strip().lower()
        if _BOOL_TRUE_RE.match(s_val):
            return True
        if _BOOL_FALSE_RE.match(s_val):
            return False

        return default

    @staticmethod
    def parse_date(value: str | None) -> date | None:
        """Parse date string using standard formats (ISO, European)."""
        if not value:
            return None

        s_val = str(value).strip()
        if not s_val:
            return None

        # Common formats to try
        formats = [
            "%Y-%m-%d",  # ISO: 2023-12-25
            "%d/%m/%Y",  # EU: 25/12/2023
            "%d-%m-%Y",  # EU: 25-12-2023
            "%Y/%m/%d",  # Alt ISO: 2023/12/25
            "%d.%m.%Y",  # Dot: 25.12.2023
        ]

        for fmt in formats:
            try:
                return datetime.strptime(s_val, fmt).date()
            except ValueError:
                continue

        # Try to handle timestamps if passed as string
        try:
            # "2023-12-25 10:00:00"
            return datetime.fromisoformat(s_val).date()
        except ValueError:
            pass

        return None
