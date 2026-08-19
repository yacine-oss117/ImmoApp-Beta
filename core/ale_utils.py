"""
Common constants and utilities for Application Layer Encryption (ALE).
Designed to be shared between services and repositories.
"""

from __future__ import annotations

# Structured markers using non-printable ASCII (Start of Heading/Text)
# These cannot be typed by users in standard text fields, preventing mask collisions.
MASK_ENC = "\u0001\u0002[ALE:ENC]\u0003\u0004"
MASK_BIDX_PREFIX = "\u0001\u0002[ALE:BIDX]\u0003\u0004"
LEGACY_MASK_ENC = "ALE_ENCRYPTED"
LEGACY_MASK_BIDX_PREFIX = "ALE_BIDX_"


def is_structured_ale_mask(value: str | None) -> bool:
    """Check only the structured non-printable ALE masks."""
    if not value:
        return False
    return value == MASK_ENC or value.startswith(MASK_BIDX_PREFIX)


def is_legacy_ale_mask(value: str | None) -> bool:
    """Check legacy printable ALE masks from previous releases."""
    if not value:
        return False
    return value == LEGACY_MASK_ENC or value.startswith(LEGACY_MASK_BIDX_PREFIX)


def is_ale_mask(value: str | None, *, allow_legacy: bool = False) -> bool:
    """Check if a string is an ALE mask."""
    if is_structured_ale_mask(value):
        return True
    if allow_legacy:
        return is_legacy_ale_mask(value)
    return False


__all__ = [
    "LEGACY_MASK_BIDX_PREFIX",
    "LEGACY_MASK_ENC",
    "MASK_BIDX_PREFIX",
    "MASK_ENC",
    "is_ale_mask",
    "is_legacy_ale_mask",
    "is_structured_ale_mask",
]
