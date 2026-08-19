"""Offer photo upload helpers with offline queue support."""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any, cast

from app.services.api_client import ApiError, api_delete, api_get, api_post, as_dict, as_dict_list
from app.services.local_service_urls import rewrite_local_service_request, rewrite_local_service_url
from app.services.offline_account_scope import OfflineAccountScope, require_active_account_scope
from app.services.offline_capabilities import require_supported_offline_action
from app.services.offline_state import get_offline_mode
from app.services.upload_queue import enqueue_offer_photo_upload, mark_media_upload
from core.contracts.offer_photo_media import (
    OFFER_PHOTO_PURPOSE,
    is_supported_offer_photo_filename,
    offer_photo_content_type_for_filename,
    supported_offer_photo_formats_label,
)


def _guess_content_type(filename: str) -> str:
    return offer_photo_content_type_for_filename(filename)


def validate_offer_photo_path(source_path: str) -> None:
    if not os.path.exists(source_path):
        raise FileNotFoundError(f"Property photo file not found: {source_path}")
    if not is_supported_offer_photo_filename(source_path):
        raise ValueError(
            f"Unsupported property photo format. Use {supported_offer_photo_formats_label()}."
        )


def _post_presigned_upload(
    url: str,
    fields: dict[str, object],
    filename: str,
    content: bytes,
    content_type: str,
) -> None:
    from requests import RequestException, post

    files = {"file": (filename, content, content_type)}
    try:
        response = post(url, data=fields, files=files, timeout=60)
    except RequestException as exc:
        raise RuntimeError(f"Offer photo upload failed: {exc}") from exc
    if response.status_code >= 400:
        raise ApiError(response.status_code, response.text or "Offer photo upload failed")


def queue_offer_photo_upload(
    offer_id: int,
    source_path: str,
    *,
    position: int = 0,
    scope: OfflineAccountScope | None = None,
) -> str:
    require_supported_offline_action("offer_photo", "upload")
    resolved_scope = scope or require_active_account_scope()
    return enqueue_offer_photo_upload(
        offer_id,
        source_path,
        position=position,
        scope=resolved_scope,
    )


def upload_offer_photo(
    offer_id: int,
    source_path: str,
    *,
    position: int = 0,
    scope: OfflineAccountScope | None = None,
) -> int | str:
    require_supported_offline_action("offer_photo", "create")
    validate_offer_photo_path(source_path)
    resolved_scope = scope or require_active_account_scope()
    if get_offline_mode():
        return queue_offer_photo_upload(
            offer_id, source_path, position=position, scope=resolved_scope
        )
    queue_id = uuid.uuid4().hex
    item = {
        "id": queue_id,
        "path": source_path,
        "filename": os.path.basename(source_path),
        "parent_local_id": int(offer_id),
        "position": int(position),
        "storage_id": "",
    }
    return process_pending_offer_photo_upload(item, scope=resolved_scope)


def process_pending_offer_photo_upload(
    item: dict[str, Any],
    *,
    scope: OfflineAccountScope | None = None,
) -> int:
    resolved_scope = scope or require_active_account_scope()
    queue_id = str(item.get("id") or uuid.uuid4().hex)
    offer_id = int(item.get("parent_local_id") or 0)
    if offer_id <= 0:
        raise RuntimeError("Offer photo parent is not reconciled yet.")
    position = int(item.get("position") or 0)
    storage_id = str(item.get("storage_id") or "")
    path = str(item.get("path") or "")

    if not storage_id:
        if not path or not os.path.exists(path):
            raise FileNotFoundError(path or "offer photo file missing")
        filename = str(item.get("filename") or os.path.basename(path))
        if not is_supported_offer_photo_filename(filename):
            raise ValueError(
                f"Unsupported property photo format. Use {supported_offer_photo_formats_label()}."
            )
        content = Path(path).read_bytes()
        if not content:
            raise ValueError("Offer photo file is empty.")
        content_type = _guess_content_type(filename)
        presign = as_dict(
            api_post(
                "/storage/presign-upload",
                {
                    "filename": filename,
                    "content_type": content_type,
                    "purpose": OFFER_PHOTO_PURPOSE,
                    "size_bytes": len(content),
                },
                headers={"Idempotency-Key": f"offer-photo:{queue_id}:presign"},
            )
        )
        url = rewrite_local_service_url(str(presign.get("url") or ""))
        fields = presign.get("fields")
        storage_id = str(presign.get("storage_id") or "")
        if not url or not isinstance(fields, dict) or not storage_id:
            raise ApiError(500, "Invalid offer photo presign response")
        _post_presigned_upload(
            url, cast(dict[str, object], fields), filename, content, content_type
        )
        completed = as_dict(
            api_post(
                "/storage/complete-upload",
                {"storage_id": storage_id},
                headers={"Idempotency-Key": f"offer-photo:{queue_id}:complete"},
            )
        )
        storage_id = str(completed.get("storage_id") or storage_id)
        mark_media_upload(queue_id, storage_id=storage_id, scope=resolved_scope)

    payload = as_dict(
        api_post(
            f"/offers/{offer_id}/photos/",
            {"storage_id": storage_id, "position": position},
            headers={"Idempotency-Key": f"offer-photo:{queue_id}:attach"},
        )
    )
    photo_id = payload.get("id")
    if not isinstance(photo_id, (int, float, str)):
        raise ApiError(500, "Invalid offer photo response")
    return int(photo_id)


def list_offer_photos(offer_id: int, *, include_deleted: bool = False) -> list[dict[str, object]]:
    payload = api_get(
        f"/offers/{int(offer_id)}/photos",
        params={"include_deleted": int(include_deleted)},
    )
    if isinstance(payload, list):
        return [dict(item) for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        return as_dict_list(payload.get("items"))
    return []


def delete_offer_photo(photo_id: int, *, idempotency_key: str) -> bool:
    key = str(idempotency_key).strip()
    if not key:
        raise ValueError("idempotency_key is required for offer photo delete.")
    try:
        payload = api_delete(
            f"/offers/photos/{int(photo_id)}",
            headers={"Idempotency-Key": key},
        )
    except ApiError as exc:
        if exc.status_code == 404:
            return False
        raise
    if isinstance(payload, dict):
        return bool(payload.get("deleted"))
    return True


def presign_offer_photo_url(storage_id: str, *, expires_seconds: int = 300) -> str:
    payload = as_dict(
        api_post(
            "/storage/presign",
            {
                "storage_id": storage_id,
                "expires_seconds": int(expires_seconds),
            },
        )
    )
    return str(payload.get("url") or "")


def download_offer_photo_thumbnail_bytes(storage_id: str, *, max_bytes: int) -> bytes:
    if int(max_bytes) <= 0:
        raise ValueError("max_bytes must be positive")
    url = presign_offer_photo_url(storage_id)
    if not url:
        return b""
    from requests import RequestException, get

    request_url, headers = rewrite_local_service_request(url)
    try:
        response = get(request_url, headers=headers, timeout=10, stream=True)
        response.raise_for_status()
        chunks: list[bytes] = []
        total = 0
        for chunk in response.iter_content(chunk_size=65536):
            if not chunk:
                continue
            chunks.append(chunk)
            total += len(chunk)
            if total > int(max_bytes):
                return b""
    except RequestException as exc:
        raise RuntimeError("Property photo thumbnail could not be loaded.") from exc
    return b"".join(chunks)


__all__ = [
    "process_pending_offer_photo_upload",
    "delete_offer_photo",
    "download_offer_photo_thumbnail_bytes",
    "list_offer_photos",
    "presign_offer_photo_url",
    "queue_offer_photo_upload",
    "upload_offer_photo",
    "validate_offer_photo_path",
]
