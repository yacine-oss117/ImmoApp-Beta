"""Access-related storage operations."""

from __future__ import annotations

import tempfile
from pathlib import Path

from core.data import storage_objects as storage_data
from server.immoapp_server.observability import business_span
from server.pg.uow import get_uow

from .storage_client import BotoCoreError, ClientError, get_storage_client
from .storage_config import get_storage_config
from .storage_errors import StorageError


def fetch_small_bytes(storage_id: str, *, max_bytes: int) -> tuple[str, bytes, str | None]:
    if int(max_bytes) <= 0:
        raise ValueError("max_bytes must be > 0")
    with get_uow().session() as session:
        record = storage_data.get_storage_object(session, storage_id)
    if not record:
        raise StorageError("Object not found.")
    if record.get("status") != "ready":
        raise StorageError("Object not ready.")
    try:
        record_size = int(record.get("size_bytes") or 0)
    except (TypeError, ValueError):
        record_size = 0
    if record_size > int(max_bytes):
        raise StorageError("Object exceeds inline byte limit.")

    try:
        response = get_storage_client().get_object(
            Bucket=record["bucket"],
            Key=record["object_key"],
        )
    except (BotoCoreError, ClientError) as exc:
        raise StorageError("Failed to load object.") from exc

    try:
        content_length = int(response.get("ContentLength") or 0)
    except (TypeError, ValueError):
        content_length = 0
    if content_length > int(max_bytes):
        close = getattr(response.get("Body"), "close", None)
        if callable(close):
            close()
        raise StorageError("Object exceeds inline byte limit.")
    body_stream = response["Body"]
    try:
        body = body_stream.read(int(max_bytes) + 1)
    finally:
        close = getattr(body_stream, "close", None)
        if callable(close):
            close()
    if len(body) > int(max_bytes):
        raise StorageError("Object exceeds inline byte limit.")
    content_type = response.get("ContentType")
    return record["object_key"], body, content_type


def generate_download_url(
    storage_id: str,
    *,
    expires_seconds: int | None = None,
    filename: str | None = None,
) -> str:
    with business_span(
        "storage.generate_download_url",
        attributes={"storage.storage_id": storage_id},
    ) as span:
        with get_uow().session() as session:
            record = storage_data.get_storage_object(session, storage_id)
        if not record:
            span.set_attribute("storage.record_exists", False)
            raise StorageError("Object not found.")
        span.set_attribute("storage.record_exists", True)
        if record.get("status") != "ready":
            span.set_attribute("storage.record_ready", False)
            raise StorageError("Object not ready.")
        span.set_attribute("storage.record_ready", True)
        params: dict[str, object] = {
            "Bucket": record["bucket"],
            "Key": record["object_key"],
        }
        if filename:
            params["ResponseContentDisposition"] = f'attachment; filename="{filename}"'
        ttl = expires_seconds or get_storage_config().presign_default_seconds
        span.set_attribute("storage.presign_ttl_seconds", ttl)
        return str(
            get_storage_client().generate_presigned_url(
                "get_object",
                Params=params,
                ExpiresIn=ttl,
            )
        )


def get_presign_default_seconds() -> int:
    return get_storage_config().presign_default_seconds


def download_to_temp(
    storage_id: str,
    *,
    suffix: str | None = None,
    require_ready: bool = True,
) -> Path:
    with get_uow().session() as session:
        record = storage_data.get_storage_object(session, storage_id)
    if not record:
        raise StorageError("Object not found.")
    if require_ready and record.get("status") != "ready":
        raise StorageError("Object not ready.")

    temp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix or "")
    temp_path = Path(temp.name)
    temp.close()

    try:
        get_storage_client().download_file(
            record["bucket"],
            record["object_key"],
            str(temp_path),
        )
    except (BotoCoreError, ClientError) as exc:
        try:
            temp_path.unlink()
        except OSError:
            pass
        raise StorageError("Failed to download object.") from exc

    return temp_path
