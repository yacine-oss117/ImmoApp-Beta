"""Media helpers for agency logo/signature."""

from __future__ import annotations

import base64
import hashlib
import os
import shutil
from pathlib import Path
from typing import cast

from app.core_app.paths import cache_dir
from app.services.agency_settings_cache import _update_settings_cache
from app.services.api_client import ApiError, api_get, api_post, as_dict
from app.services.api_config import get_api_base_url
from app.services.local_service_urls import rewrite_local_service_url
from app.services.offer_photos import process_pending_offer_photo_upload
from app.services.offline_account_scope import (
    OfflineAccountScope,
    get_account_root,
    get_active_account_scope,
    require_active_account_scope,
)
from app.services.offline_conflicts import OfflineConflict, add_conflict, remove_conflict
from app.services.offline_state import get_offline_mode
from app.services.upload_queue import (
    enqueue_media,
    get_media_upload,
    list_media_uploads,
    mark_media_upload,
    note_media_upload_attempt,
    remove_media_upload,
)

_media_cache: dict[str, str] = {}
_MEDIA_SYNC_BATCH_LIMIT = 5
_RETRYABLE_STATUS_CODES = {408, 425, 429, 500, 502, 503, 504}


def _media_scope_key(scope: OfflineAccountScope | None = None) -> str:
    resolved = scope or get_active_account_scope()
    if resolved is not None:
        return resolved.account_key
    return str(get_api_base_url() or "default")


def _media_cache_dir(scope: OfflineAccountScope | None = None) -> Path:
    resolved = scope or get_active_account_scope()
    if resolved is not None:
        root = get_account_root(resolved) / "remote_media"
        root.mkdir(parents=True, exist_ok=True)
        return root
    api_base = str(get_api_base_url() or "default")
    digest = hashlib.sha256(api_base.encode("utf-8")).hexdigest()[:12]
    root = cache_dir() / "remote_media" / digest
    root.mkdir(parents=True, exist_ok=True)
    return root


def _cache_token(kind: str, *, scope: OfflineAccountScope | None = None) -> str:
    return f"{_media_scope_key(scope)}:{kind}"


def _cache_media_path(
    kind: str,
    filename: str,
    *,
    scope: OfflineAccountScope | None = None,
) -> Path:
    """Build the local cache path for a media file (logo, signature)."""
    root = _media_cache_dir(scope)
    ext = os.path.splitext(filename)[1].lower()
    name = f"{kind}{ext}" if ext else kind
    return root / name


def _fetch_media(kind: str) -> str:
    """Fetch a media file from the API and cache locally. Returns path or empty string."""
    cache_token = _cache_token(kind)
    cached = _media_cache.get(cache_token, "")
    if cached and os.path.exists(cached):
        return cached
    if get_offline_mode():
        return ""
    try:
        response = api_get("/settings/agency/media", params={"kind": kind, "mode": "url"})
    except ApiError as exc:
        if exc.status_code == 404:
            return ""
        raise
    payload = as_dict(response)
    url = str(payload.get("url") or "")
    if url:
        filename = str(payload.get("filename") or "") or f"{kind}.bin"
        content = _download_media_url(url)
        dest_path = _cache_media_path(kind, filename)
        dest_path.write_bytes(content)
        _media_cache[cache_token] = str(dest_path)
        return str(dest_path)
    filename = str(payload.get("filename") or "")
    content_b64 = str(payload.get("content_b64") or "")
    if not filename or not content_b64:
        return ""
    content = base64.b64decode(content_b64)
    dest_path = _cache_media_path(kind, filename)
    dest_path.write_bytes(content)
    _media_cache[cache_token] = str(dest_path)
    return str(dest_path)


def _store_local_media(kind: str, source_path: str) -> str:
    """Copy a media file to the local cache directory."""
    filename = os.path.basename(source_path)
    dest_path = _cache_media_path(kind, filename)
    shutil.copy2(source_path, str(dest_path))
    _media_cache[_cache_token(kind)] = str(dest_path)
    return str(dest_path)


def _download_media_url(url: str) -> bytes:
    from requests import RequestException, get

    try:
        response = get(url, timeout=30)
        response.raise_for_status()
    except RequestException as exc:
        raise ApiError(502, f"Media download failed: {exc}") from exc
    return cast(bytes, response.content)


def _upload_media(kind: str, source_path: str) -> str:
    """Upload media via presigned POST to avoid proxying bytes through the API."""
    filename = os.path.basename(source_path)
    content = Path(source_path).read_bytes()
    size_bytes = len(content)
    if size_bytes <= 0:
        raise ValueError("media file is empty")
    content_type = _guess_media_content_type(filename)
    presign = as_dict(
        api_post(
            "/settings/agency/media/presign",
            {
                "kind": kind,
                "filename": filename,
                "content_type": content_type,
                "size_bytes": size_bytes,
            },
        )
    )
    url = rewrite_local_service_url(str(presign.get("url") or ""))
    fields = presign.get("fields")
    if not isinstance(fields, dict):
        fields = {}
    fields = cast(dict[str, object], fields)
    storage_id = str(presign.get("storage_id") or "")
    if not url or not fields or not storage_id:
        raise ApiError(500, "Invalid presign response from server")

    _post_presigned_upload(url, fields, filename, content, content_type)

    completed = as_dict(
        api_post(
            "/settings/agency/media/complete",
            {"kind": kind, "storage_id": storage_id},
        )
    )
    return str(completed.get("storage_id") or storage_id)


def _guess_media_content_type(filename: str) -> str:
    ext = os.path.splitext(filename)[1].lower()
    if ext == ".png":
        return "image/png"
    if ext in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if ext == ".bmp":
        return "image/bmp"
    return "application/octet-stream"


def _post_presigned_upload(
    url: str,
    fields: dict[str, object],
    filename: str,
    content: bytes,
    content_type: str,
) -> None:
    """Send a presigned POST upload directly to object storage."""
    from requests import RequestException, post

    files = {"file": (filename, content, content_type)}
    try:
        response = post(url, data=fields, files=files, timeout=30)
    except RequestException as exc:
        raise ApiError(502, f"Upload failed: {exc}") from exc
    if response.status_code >= 400:
        raise ApiError(response.status_code, response.text or "Upload failed")


def get_agency_logo_path() -> str:
    """Get the local path to the agency logo image."""
    return _fetch_media("logo")


def set_agency_logo(source_path: str) -> str:
    """Upload a new agency logo and cache locally. Returns cached path."""
    if not os.path.exists(source_path):
        raise FileNotFoundError(f"Logo file not found: {source_path}")

    if get_offline_mode():
        enqueue_media("logo", source_path, scope=require_active_account_scope())
        return _store_local_media("logo", source_path)

    stored_path = _upload_media("logo", source_path)
    if stored_path:
        _update_settings_cache("agency_logo_path", stored_path)
    return _store_local_media("logo", source_path)


def get_agency_signature_path() -> str:
    """Get the local path to the agency signature image."""
    return _fetch_media("signature")


def set_agency_signature(source_path: str) -> str:
    """Upload a new agency signature and cache locally. Returns cached path."""
    if not os.path.exists(source_path):
        raise FileNotFoundError(f"Signature file not found: {source_path}")

    if get_offline_mode():
        enqueue_media("signature", source_path, scope=require_active_account_scope())
        return _store_local_media("signature", source_path)

    stored_path = _upload_media("signature", source_path)
    if stored_path:
        _update_settings_cache("agency_signature_path", stored_path)
    return _store_local_media("signature", source_path)


def flush_pending_media_uploads(
    *, scope: OfflineAccountScope | None = None, limit: int = _MEDIA_SYNC_BATCH_LIMIT
) -> int:
    """Attempt to upload queued media files when online."""
    if get_offline_mode():
        return 0
    resolved_scope = scope or get_active_account_scope()
    if resolved_scope is None:
        return 0
    uploads = list_media_uploads(scope=resolved_scope)
    success = 0
    for item in uploads[: max(1, int(limit))]:
        queue_id = str(item.get("id"))
        kind = str(item.get("kind") or "")
        path = str(item.get("path") or "")
        if not queue_id or not kind:
            continue
        if kind == "offer_photo":
            current = get_media_upload(queue_id, scope=resolved_scope) or item
            parent_local_id = int(current.get("parent_local_id") or 0)
            if parent_local_id <= 0:
                continue
            if not path or not os.path.exists(path):
                mark_media_upload(
                    queue_id,
                    status="needs_review",
                    error="Offer photo file is missing.",
                    scope=resolved_scope,
                )
                add_conflict(
                    OfflineConflict(
                        op_id=f"media:{queue_id}",
                        entity_type="offer_photo",
                        local_id=parent_local_id,
                        reason_code="media_file_missing",
                        message="Offer photo file is missing.",
                    ),
                    scope=resolved_scope,
                )
                continue
            try:
                process_pending_offer_photo_upload(current, scope=resolved_scope)
            except FileNotFoundError as exc:
                mark_media_upload(
                    queue_id,
                    status="needs_review",
                    error=str(exc),
                    scope=resolved_scope,
                )
                add_conflict(
                    OfflineConflict(
                        op_id=f"media:{queue_id}",
                        entity_type="offer_photo",
                        local_id=parent_local_id,
                        reason_code="media_file_missing",
                        message=str(exc),
                    ),
                    scope=resolved_scope,
                )
                continue
            except ValueError as exc:
                mark_media_upload(
                    queue_id,
                    status="needs_review",
                    error=str(exc),
                    scope=resolved_scope,
                )
                add_conflict(
                    OfflineConflict(
                        op_id=f"media:{queue_id}",
                        entity_type="offer_photo",
                        local_id=parent_local_id,
                        reason_code="media_review_required",
                        message=str(exc),
                    ),
                    scope=resolved_scope,
                )
                continue
            except ApiError as exc:
                if int(exc.status_code) in _RETRYABLE_STATUS_CODES:
                    note_media_upload_attempt(queue_id, str(exc), scope=resolved_scope)
                    continue
                mark_media_upload(
                    queue_id,
                    status="needs_review",
                    error=str(exc),
                    scope=resolved_scope,
                )
                add_conflict(
                    OfflineConflict(
                        op_id=f"media:{queue_id}",
                        entity_type="offer_photo",
                        local_id=parent_local_id,
                        reason_code="media_review_required",
                        message=str(exc),
                    ),
                    scope=resolved_scope,
                )
                continue
            except RuntimeError as exc:
                note_media_upload_attempt(queue_id, str(exc), scope=resolved_scope)
                continue
            remove_media_upload(queue_id, scope=resolved_scope)
            remove_conflict(f"media:{queue_id}", scope=resolved_scope)
            success += 1
            continue
        if not path or not os.path.exists(path):
            mark_media_upload(
                queue_id,
                status="needs_review",
                error=f"{kind} file is missing.",
                scope=resolved_scope,
            )
            add_conflict(
                OfflineConflict(
                    op_id=f"media:{queue_id}",
                    entity_type="generic",
                    local_id=0,
                    reason_code="media_file_missing",
                    message=f"{kind} file is missing.",
                ),
                scope=resolved_scope,
            )
            continue
        try:
            stored_path = _upload_media(kind, path)
        except ApiError as exc:
            if int(exc.status_code) in _RETRYABLE_STATUS_CODES:
                note_media_upload_attempt(queue_id, str(exc), scope=resolved_scope)
                continue
            mark_media_upload(
                queue_id,
                status="needs_review",
                error=str(exc),
                scope=resolved_scope,
            )
            add_conflict(
                OfflineConflict(
                    op_id=f"media:{queue_id}",
                    entity_type="generic",
                    local_id=0,
                    reason_code="media_review_required",
                    message=str(exc),
                ),
                scope=resolved_scope,
            )
            continue
        if stored_path:
            if kind == "logo":
                _update_settings_cache(
                    "agency_logo_path",
                    stored_path,
                    scope=resolved_scope,
                )
            if kind == "signature":
                _update_settings_cache(
                    "agency_signature_path",
                    stored_path,
                    scope=resolved_scope,
                )
        remove_media_upload(queue_id, scope=resolved_scope)
        remove_conflict(f"media:{queue_id}", scope=resolved_scope)
        success += 1
    return success


def invalidate_media_cache(kind: str | None = None) -> None:
    """Invalidate cached media paths."""
    scope = get_active_account_scope()
    if scope is None:
        if kind is None:
            _media_cache.clear()
            return
        suffix = f":{kind}"
        for cache_key in [item for item in _media_cache if item.endswith(suffix)]:
            _media_cache.pop(cache_key, None)
        return
    scope_key = _media_scope_key(scope)
    prefix = f"{scope_key}:"
    if kind:
        _media_cache.pop(f"{scope_key}:{kind}", None)
        return
    for cache_key in [item for item in _media_cache if item.startswith(prefix)]:
        _media_cache.pop(cache_key, None)


__all__ = [
    "flush_pending_media_uploads",
    "get_agency_logo_path",
    "get_agency_signature_path",
    "invalidate_media_cache",
    "set_agency_logo",
    "set_agency_signature",
]
