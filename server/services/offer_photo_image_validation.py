"""Server-side image validation for offer photo uploads."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, UnidentifiedImageError

from .storage_errors import StorageError

_ALLOWED_IMAGE_FORMATS = {"PNG", "JPEG", "BMP"}
MAX_OFFER_PHOTO_WIDTH = 12_000
MAX_OFFER_PHOTO_HEIGHT = 12_000
MAX_OFFER_PHOTO_PIXELS = 40_000_000
_INVALID_IMAGE_MESSAGE = "Invalid property photo image."


class OfferPhotoImageValidationError(StorageError):
    """Raised when uploaded offer-photo bytes are not an accepted property image."""


def _invalid_image() -> OfferPhotoImageValidationError:
    return OfferPhotoImageValidationError(_INVALID_IMAGE_MESSAGE)


def validate_offer_photo_image(path: Path) -> None:
    """Reject malformed or unsupported image bytes for offer-photo uploads."""
    try:
        with Image.open(path) as image:
            image_format = str(image.format or "").upper()
            if image_format not in _ALLOWED_IMAGE_FORMATS:
                raise _invalid_image()
            width, height = image.size
            if (
                width <= 0
                or height <= 0
                or width > MAX_OFFER_PHOTO_WIDTH
                or height > MAX_OFFER_PHOTO_HEIGHT
                or width * height > MAX_OFFER_PHOTO_PIXELS
            ):
                raise _invalid_image()
            image.verify()
    except OfferPhotoImageValidationError:
        raise
    except (OSError, SyntaxError, UnidentifiedImageError, ValueError) as exc:
        raise _invalid_image() from exc


__all__ = [
    "MAX_OFFER_PHOTO_HEIGHT",
    "MAX_OFFER_PHOTO_PIXELS",
    "MAX_OFFER_PHOTO_WIDTH",
    "OfferPhotoImageValidationError",
    "validate_offer_photo_image",
]
