"""Object storage service (S3/MinIO) with tenant-aware metadata."""

from __future__ import annotations

from .storage_config import StorageConfig, get_storage_config
from .storage_errors import StorageError
from .storage_ops import (
    complete_presigned_upload,
    download_to_temp,
    fetch_small_bytes,
    generate_download_url,
    generate_presigned_upload,
    get_presign_default_seconds,
    mark_storage_deleted,
    purge_deleted_objects,
    purge_pending_objects,
    purge_storage_object_now,
    restore_deleted_storage,
    store_bytes,
    store_fileobj,
)

__all__ = [
    "StorageConfig",
    "StorageError",
    "get_storage_config",
    "store_bytes",
    "store_fileobj",
    "fetch_small_bytes",
    "generate_download_url",
    "get_presign_default_seconds",
    "generate_presigned_upload",
    "complete_presigned_upload",
    "purge_deleted_objects",
    "purge_pending_objects",
    "mark_storage_deleted",
    "restore_deleted_storage",
    "purge_storage_object_now",
    "download_to_temp",
]
