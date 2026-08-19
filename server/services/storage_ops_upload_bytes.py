"""Byte upload operations."""

from __future__ import annotations

import hashlib

from .storage_client import BotoCoreError, ClientError, ensure_bucket, get_storage_client, sse_args
from .storage_config import get_storage_config
from .storage_errors import StorageError
from .storage_ops_upload_helpers import (
    create_storage_record,
    mark_storage_failed,
    mark_storage_ready,
    require_agency_id,
)
from .storage_ops_upload_utils import build_object_key
from .storage_scanning import scan_bytes
from .storage_validation import validate_purpose


def store_bytes(
    *,
    content: bytes,
    filename: str | None,
    content_type: str | None,
    purpose: str,
    user_id: int | None,
    role: str | None,
    created_ip: str | None,
) -> str:
    config = get_storage_config()
    agency_id = require_agency_id()
    size_bytes = len(content)
    validate_purpose(purpose, filename, content_type)
    scan_bytes(content, filename)
    object_key = build_object_key(agency_id, purpose, filename)

    storage_id = create_storage_record(
        bucket=config.bucket,
        object_key=object_key,
        user_id=user_id,
        role=role,
        purpose=purpose,
        content_type=content_type,
        size_bytes=size_bytes,
        checksum=None,
        created_ip=created_ip,
    )

    checksum = hashlib.sha256(content).hexdigest()
    try:
        ensure_bucket()
        get_storage_client().put_object(
            Bucket=config.bucket,
            Key=object_key,
            Body=content,
            ContentType=content_type or "application/octet-stream",
            **sse_args(),
        )
    except (BotoCoreError, ClientError) as exc:
        mark_storage_failed(
            storage_id=storage_id,
            message=str(exc),
            user_id=user_id,
            role=role,
            created_ip=created_ip,
            purpose=purpose,
        )
        raise StorageError("Failed to store object.") from exc

    mark_storage_ready(
        storage_id=storage_id,
        content_type=content_type,
        size_bytes=size_bytes,
        checksum=checksum,
        agency_id=agency_id,
        user_id=user_id,
        role=role,
        created_ip=created_ip,
        purpose=purpose,
    )

    return storage_id
