"""Storage validation helpers."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from core.contracts.offer_photo_media import (
    OFFER_PHOTO_CONTENT_TYPES,
    OFFER_PHOTO_EXTENSIONS,
    OFFER_PHOTO_PURPOSE,
)
from core.data import storage_objects as storage_data
from server.pg.uow import get_uow

from .storage_config import get_storage_config
from .storage_errors import StorageError

if TYPE_CHECKING:
    from server.pg.uow import PgSession

_ALLOWED_PURPOSES: dict[str, dict[str, set[str]]] = {
    "import": {
        "exts": {".csv", ".tsv", ".txt", ".xlsx", ".ods"},
        "content_types": {
            "text/csv",
            "application/vnd.ms-excel",
            "text/tab-separated-values",
            "text/plain",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "application/vnd.oasis.opendocument.spreadsheet",
        },
    },
    "import_artifact": {
        "exts": {".json", ".jsonl"},
        "content_types": {
            "application/json",
            "application/x-ndjson",
            "text/plain",
        },
    },
    "agency_logo": {
        "exts": {".png", ".jpg", ".jpeg", ".bmp"},
        "content_types": {"image/png", "image/jpeg", "image/bmp"},
    },
    "agency_signature": {
        "exts": {".png", ".jpg", ".jpeg", ".bmp"},
        "content_types": {"image/png", "image/jpeg", "image/bmp"},
    },
    OFFER_PHOTO_PURPOSE: {
        "exts": set(OFFER_PHOTO_EXTENSIONS),
        "content_types": set(OFFER_PHOTO_CONTENT_TYPES),
    },
}


def validate_purpose(purpose: str, filename: str | None, content_type: str | None) -> None:
    if purpose not in _ALLOWED_PURPOSES:
        raise StorageError("Unsupported upload purpose.")
    rules = _ALLOWED_PURPOSES[purpose]
    ext = Path(filename or "").suffix.lower()
    if ext and ext not in rules["exts"]:
        raise StorageError("File type not allowed for this upload.")
    if content_type and content_type not in rules["content_types"]:
        raise StorageError("Content type not allowed for this upload.")


def _max_bytes_for_purpose(purpose: str, *, default_max: int) -> int:
    config = get_storage_config()
    if purpose == "import":
        return min(config.max_import_bytes, default_max)
    if purpose == "import_artifact":
        return min(config.max_import_bytes, default_max)
    if purpose == OFFER_PHOTO_PURPOSE:
        return min(config.max_offer_photo_bytes, default_max)
    if purpose in {"agency_logo", "agency_signature"}:
        return min(config.max_agency_media_bytes, default_max)
    return default_max


def enforce_limits(
    size_bytes: int,
    agency_id: int,
    *,
    user_id: int | None,
    purpose: str,
    session: PgSession | None = None,
) -> None:
    config = get_storage_config()
    if size_bytes <= 0:
        raise StorageError("File is empty.")
    purpose_limit = _max_bytes_for_purpose(purpose, default_max=config.max_file_bytes)
    if size_bytes > purpose_limit:
        raise StorageError("File exceeds the maximum allowed size.")

    def _run(active_session: PgSession) -> None:
        if config.agency_quota_bytes is not None:
            used = storage_data.get_reserved_usage_for_agency(
                active_session,
                agency_id=agency_id,
            )
            if used + size_bytes > config.agency_quota_bytes:
                raise StorageError("Storage quota exceeded for agency.")
        if config.user_daily_max_files is not None and user_id is not None:
            recent = storage_data.count_recent_uploads(
                active_session,
                user_id=user_id,
                since_hours=24,
            )
            if recent >= config.user_daily_max_files:
                raise StorageError("Daily upload limit reached for user.")

    if session is not None:
        _run(session)
        return

    with get_uow().session() as local_session:
        _run(local_session)


__all__ = ["validate_purpose", "enforce_limits", "_ALLOWED_PURPOSES"]
