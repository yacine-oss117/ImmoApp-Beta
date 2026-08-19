"""Shared offer-photo media contract.

Offer photos belong to offers, not listing roots. Keep this contract shared so
desktop filters, client MIME guessing, and server upload validation cannot drift.
"""

from __future__ import annotations

from pathlib import Path

OFFER_PHOTO_PURPOSE = "offer_photo"
OFFER_PHOTO_EXTENSIONS: tuple[str, ...] = (".png", ".jpg", ".jpeg", ".bmp")
OFFER_PHOTO_CONTENT_TYPES: tuple[str, ...] = ("image/png", "image/jpeg", "image/bmp")
OFFER_PHOTO_FILE_DIALOG_FILTER = "Property photos (*.png *.jpg *.jpeg *.bmp)"

_CONTENT_TYPE_BY_EXTENSION = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".bmp": "image/bmp",
}


def offer_photo_content_type_for_filename(filename: str) -> str:
    """Return the allowed content type for an offer photo filename."""
    return _CONTENT_TYPE_BY_EXTENSION.get(Path(filename).suffix.lower(), "application/octet-stream")


def is_supported_offer_photo_filename(filename: str) -> bool:
    """Return True when a filename has an allowed offer-photo extension."""
    return Path(filename).suffix.lower() in _CONTENT_TYPE_BY_EXTENSION


def supported_offer_photo_formats_label() -> str:
    """Human-readable supported format list for validation messages."""
    return "PNG, JPG, JPEG, or BMP"


__all__ = [
    "OFFER_PHOTO_CONTENT_TYPES",
    "OFFER_PHOTO_EXTENSIONS",
    "OFFER_PHOTO_FILE_DIALOG_FILTER",
    "OFFER_PHOTO_PURPOSE",
    "is_supported_offer_photo_filename",
    "offer_photo_content_type_for_filename",
    "supported_offer_photo_formats_label",
]
