"""
Object-storage-backed agency media helpers (logo/signature).
"""

from __future__ import annotations

import logging
import os

from core.data import storage_objects as storage_data
from server.pg.tenant_context import require_agency_id
from server.pg.uow import get_uow

from . import agency_settings
from .storage import (
    StorageError,
    complete_presigned_upload,
    fetch_small_bytes,
    generate_download_url,
    generate_presigned_upload,
    get_presign_default_seconds,
    mark_storage_deleted,
    store_bytes,
)
from .storage_config import get_storage_config

logger = logging.getLogger(__name__)
_ALLOWED_EXTS = {".png", ".jpg", ".jpeg", ".bmp"}


def _normalize_kind(kind: str) -> str:
    normalized = (kind or "").strip().lower()
    if normalized not in {"logo", "signature"}:
        raise ValueError("kind must be 'logo' or 'signature'")
    return normalized


def _settings_key(kind: str) -> str:
    # Preserve existing setting keys for UI compatibility.
    return "agency_logo_path" if kind == "logo" else "agency_signature_path"


def store_agency_media(
    kind: str,
    filename: str,
    content: bytes,
    *,
    actor: str | None,
    user_id: int | None,
    role: str | None,
    created_ip: str | None,
) -> str:
    """
    Store agency logo/signature in object storage and persist the storage id in settings.
    """
    normalized = _normalize_kind(kind)
    ext = (filename or "").rsplit(".", 1)[-1].lower()
    if not ext or f".{ext}" not in _ALLOWED_EXTS:
        raise ValueError("Unsupported file extension.")

    agency_id = require_agency_id(error_message="agency_id is required to store agency media.")
    storage_id = store_bytes(
        content=content,
        filename=filename,
        content_type=f"image/{ext if ext != 'jpg' else 'jpeg'}",
        purpose=f"agency_{normalized}",
        user_id=user_id,
        role=role,
        created_ip=created_ip,
    )
    previous = agency_settings.get_agency_setting(_settings_key(normalized), "")
    agency_settings.set_agency_setting(
        _settings_key(normalized),
        storage_id,
        agency_id=agency_id,
        actor=actor,
    )
    if previous and previous != storage_id:
        try:
            mark_storage_deleted(
                storage_id=previous,
                user_id=user_id,
                role=role,
                created_ip=created_ip,
            )
        except StorageError:
            logger.warning(
                "Failed to mark previous %s media as deleted: storage_id=%s",
                normalized,
                previous,
                exc_info=True,
            )
    return storage_id


def load_agency_media(kind: str) -> tuple[str, bytes] | None:
    """
    Load agency logo/signature content from object storage.
    """
    normalized = _normalize_kind(kind)
    storage_id = agency_settings.get_agency_setting(_settings_key(normalized), "")
    if not storage_id:
        return None
    with get_uow().session() as session:
        record = storage_data.get_storage_object(session, storage_id)
    if not record or record.get("status") != "ready":
        return None
    size_bytes = int(record.get("size_bytes") or 0)
    config = get_storage_config()
    inline_limit = min(config.max_inline_media_bytes, config.max_agency_media_bytes)
    if size_bytes > inline_limit:
        logger.warning(
            "Skipping oversized agency media load: storage_id=%s size_bytes=%s",
            storage_id,
            size_bytes,
        )
        return None
    try:
        object_key, content, _content_type = fetch_small_bytes(
            storage_id,
            max_bytes=inline_limit,
        )
    except StorageError:
        return None
    filename = object_key.rsplit("/", 1)[-1]
    return filename, content


def get_agency_media_url(
    kind: str,
    *,
    expires_seconds: int | None = None,
) -> dict[str, object] | None:
    """Generate a presigned download URL for agency media."""
    normalized = _normalize_kind(kind)
    storage_id = agency_settings.get_agency_setting(_settings_key(normalized), "")
    if not storage_id:
        return None
    with get_uow().session() as session:
        record = storage_data.get_storage_object(session, storage_id)
    if not record:
        return None
    filename = str(record.get("object_key") or "").rsplit("/", 1)[-1]
    try:
        url = generate_download_url(
            storage_id,
            expires_seconds=expires_seconds,
            filename=filename or None,
        )
    except StorageError:
        return None
    ttl = expires_seconds or get_presign_default_seconds()
    return {"storage_id": storage_id, "filename": filename, "url": url, "expires_in": ttl}


def prepare_agency_media_upload(
    kind: str,
    filename: str,
    content_type: str | None,
    size_bytes: int,
    *,
    user_id: int | None,
    role: str | None,
    created_ip: str | None,
    expires_seconds: int | None = None,
) -> dict[str, object]:
    """Generate a presigned upload for agency media and return upload metadata."""
    normalized = _normalize_kind(kind)
    ext = os.path.splitext(filename)[1].lower()
    if ext and ext not in _ALLOWED_EXTS:
        raise ValueError("Unsupported file extension.")
    if not content_type:
        content_type = "image/png" if ext == ".png" else "image/jpeg"
    result = generate_presigned_upload(
        filename=filename,
        content_type=content_type,
        purpose=f"agency_{normalized}",
        size_bytes=size_bytes,
        user_id=user_id,
        role=role,
        created_ip=created_ip,
        expires_seconds=expires_seconds,
    )
    result["kind"] = normalized
    return result


def finalize_agency_media_upload(
    kind: str,
    storage_id: str,
    *,
    actor: str | None,
    user_id: int | None,
    role: str | None,
    created_ip: str | None,
) -> str:
    """Finalize an agency media upload and update agency settings."""
    normalized = _normalize_kind(kind)
    complete_presigned_upload(
        storage_id=storage_id,
        user_id=user_id,
        role=role,
        created_ip=created_ip,
    )
    agency_id = require_agency_id(error_message="agency_id is required to finalize agency media.")
    previous = agency_settings.get_agency_setting(_settings_key(normalized), "")
    agency_settings.set_agency_setting(
        _settings_key(normalized),
        storage_id,
        agency_id=agency_id,
        actor=actor,
    )
    if previous and previous != storage_id:
        try:
            mark_storage_deleted(
                storage_id=previous,
                user_id=user_id,
                role=role,
                created_ip=created_ip,
            )
        except StorageError:
            logger.warning(
                "Failed to mark previous %s media as deleted: storage_id=%s",
                normalized,
                previous,
                exc_info=True,
            )
    return storage_id


def remove_agency_media(
    kind: str,
    *,
    actor: str | None,
    user_id: int | None,
    role: str | None,
    created_ip: str | None,
) -> None:
    """Clear agency media setting and mark the underlying storage object as deleted."""
    normalized = _normalize_kind(kind)
    existing = agency_settings.get_agency_setting(_settings_key(normalized), "")
    if not existing:
        return
    try:
        mark_storage_deleted(
            storage_id=existing,
            user_id=user_id,
            role=role,
            created_ip=created_ip,
        )
    except StorageError:
        logger.warning(
            "Failed to mark %s media as deleted: storage_id=%s",
            normalized,
            existing,
            exc_info=True,
        )
    agency_id = require_agency_id(error_message="agency_id is required to remove agency media.")
    agency_settings.set_agency_setting(
        _settings_key(normalized),
        "",
        agency_id=agency_id,
        actor=actor,
    )
