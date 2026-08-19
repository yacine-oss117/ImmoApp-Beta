"""
Phone number normalizer for Algerian formats.

Handles various phone formats and normalizes to standard format.
"""

from __future__ import annotations

import re

from core.importer.normalizers.base import NormalizeResult, RowContext
from core.importer.normalizers.text_utils import canonicalize_text, strip_labels

# Algerian phone prefixes
MOBILE_PREFIXES = {"05", "06", "07"}  # Mobile operators
LANDLINE_PREFIXES = {"02", "03", "04"}  # Landlines by region
SERVICE_PREFIXES = {"08"}  # Commercial / toll-free style numbers
SPECIAL_PREFIXES = {"09"}  # Special / VSAT / non-mobile service ranges

# Country code
ALGERIA_CODE = "+213"


class PhoneNormalizer:
    """Normalizer for Algerian phone numbers.

    Handles formats like:
    - 0555123456
    - 05 55 12 34 56
    - +213 555 123 456
    - 00213555123456
    - 555123456 (missing leading 0)
    """

    def normalize(self, value: str, context: RowContext | None = None) -> NormalizeResult:
        """Normalize a phone number.

        Args:
            value: Raw phone string.
            context: Optional row context (not used for phone).

        Returns:
            NormalizeResult with normalized phone number.
        """
        if not value or not value.strip():
            return NormalizeResult(
                value=None,
                confidence=1.0,
                original=value,
                needs_review=False,
            )

        original = value
        phone = strip_labels(
            canonicalize_text(value),
            labels={"mobile", "phone", "portable", "tel", "telephone"},
        )

        # Normalize plus sign variants (full-width, etc.)
        phone = phone.replace("＋", "+").replace("➕", "+")

        # Remove common separators and whitespace
        phone = re.sub(r"[\s\-\.\(\)]+", "", phone)

        # Handle international format
        if phone.startswith("+213"):
            phone = "0" + phone[4:]
        elif phone.startswith("00213"):
            phone = "0" + phone[5:]
        # A bare 213 prefix with at least 12 digits is treated as Algeria's country
        # code. Shorter values are left untouched because "213" can also be part of
        # a local digit sequence and we do not want to over-strip partial numbers.
        elif phone.startswith("213") and len(phone) >= 12:
            phone = "0" + phone[3:]

        # Remove any remaining non-digit characters
        phone = re.sub(r"[^\d]", "", phone)

        # Handle missing leading zero
        if len(phone) == 9 and phone[0] in "567":
            phone = "0" + phone

        # Validate length
        if len(phone) != 10:
            # Never keep partial digit fragments as normalized identities. The
            # raw value already survives in review payloads, and returning "66"
            # for inputs like "zero six 66" can poison duplicate grouping.
            return NormalizeResult(
                value=None,
                confidence=0.3,
                original=original,
                needs_review=True,
                to_remarks=f"Invalid phone: {original}",
            )

        # Validate prefix
        prefix = phone[:2]
        is_mobile = prefix in MOBILE_PREFIXES
        is_landline = prefix in LANDLINE_PREFIXES
        is_service = prefix in SERVICE_PREFIXES
        is_special = prefix in SPECIAL_PREFIXES

        if not is_mobile and not is_landline and not is_service and not is_special:
            return NormalizeResult(
                value=phone,
                confidence=0.5,
                original=original,
                needs_review=True,
                to_remarks=f"Unknown prefix: {prefix}",
            )

        phone_kind = "mobile"
        confidence = 1.0
        if is_landline:
            phone_kind = "landline"
        elif is_service:
            phone_kind = "service"
            confidence = 0.95
        elif is_special:
            phone_kind = "special"
            confidence = 0.95

        # Valid Algerian phone number
        return NormalizeResult(
            value=phone,
            confidence=confidence,
            original=original,
            needs_review=False,
            extracted_extras={"phone_kind": phone_kind},
        )

    def format_display(self, phone: str) -> str:
        """Format phone for display.

        Args:
            phone: Normalized phone (10 digits).

        Returns:
            Formatted string like "05 55 12 34 56".
        """
        if not phone or len(phone) != 10:
            return phone or ""

        return f"{phone[:2]} {phone[2:4]} {phone[4:6]} {phone[6:8]} {phone[8:10]}"

    def format_international(self, phone: str) -> str:
        """Format phone in international format.

        Args:
            phone: Normalized phone (10 digits).

        Returns:
            Formatted string like "+213 555 123 456".
        """
        if not phone or len(phone) != 10:
            return phone or ""

        # Remove leading 0 and add country code
        return f"+213 {phone[1:4]} {phone[4:7]} {phone[7:10]}"
