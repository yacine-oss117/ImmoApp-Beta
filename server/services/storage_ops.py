"""Storage operations (aggregator)."""

from __future__ import annotations

from .storage_ops_access import (
    download_to_temp,
    fetch_small_bytes,
    generate_download_url,
    get_presign_default_seconds,
)
from .storage_ops_maintenance import (
    mark_storage_deleted,
    purge_deleted_objects,
    purge_pending_objects,
    purge_storage_object_now,
    restore_deleted_storage,
)
from .storage_ops_upload import (
    complete_presigned_upload,
    generate_presigned_upload,
    store_bytes,
    store_fileobj,
)

__all__ = [
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
