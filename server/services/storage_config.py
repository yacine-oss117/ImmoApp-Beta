"""Storage configuration loader."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class StorageConfig:
    endpoint_url: str | None
    access_key: str
    secret_key: str
    bucket: str
    region: str | None
    use_ssl: bool
    max_file_bytes: int
    max_import_bytes: int
    max_offer_photo_bytes: int
    max_agency_media_bytes: int
    max_inline_media_bytes: int
    agency_quota_bytes: int | None
    user_daily_max_files: int | None
    virus_scan: bool
    virus_scan_required: bool
    presign_default_seconds: int
    clamd_socket: str | None
    clamd_host: str | None
    clamd_port: int
    clamd_timeout: float
    sse: str | None
    sse_kms_key_id: str | None


def _load_config() -> StorageConfig:
    endpoint_url = os.environ.get("STORAGE_ENDPOINT_URL") or None
    access_key = os.environ.get("STORAGE_ACCESS_KEY", "")
    secret_key = os.environ.get("STORAGE_SECRET_KEY", "")
    bucket = os.environ.get("STORAGE_BUCKET", "immoapp")
    region = os.environ.get("STORAGE_REGION") or None
    use_ssl = os.environ.get("STORAGE_USE_SSL", "1") == "1"
    max_mb = int(os.environ.get("STORAGE_MAX_FILE_MB", "25"))
    max_import_mb = int(os.environ.get("STORAGE_MAX_IMPORT_MB", str(max_mb)))
    max_offer_photo_mb = int(os.environ.get("STORAGE_MAX_OFFER_PHOTO_MB", "10"))
    max_agency_media_mb = int(os.environ.get("STORAGE_MAX_AGENCY_MEDIA_MB", "2"))
    max_inline_media_kb = int(os.environ.get("STORAGE_MAX_INLINE_MEDIA_KB", "256"))
    quota_mb_raw = os.environ.get("STORAGE_AGENCY_QUOTA_MB")
    quota_mb = int(quota_mb_raw) if quota_mb_raw else None
    user_limit_raw = os.environ.get("STORAGE_USER_DAILY_MAX_FILES")
    user_daily_max_files = int(user_limit_raw) if user_limit_raw else None
    virus_scan = os.environ.get("STORAGE_VIRUS_SCAN", "0") == "1"
    virus_scan_required = os.environ.get("STORAGE_VIRUS_SCAN_REQUIRED", "0") == "1"
    presign_seconds = int(os.environ.get("STORAGE_PRESIGN_SECONDS", "900"))
    clamd_socket = os.environ.get("STORAGE_CLAMD_SOCKET") or None
    clamd_host = os.environ.get("STORAGE_CLAMD_HOST") or None
    clamd_port = int(os.environ.get("STORAGE_CLAMD_PORT", "3310"))
    clamd_timeout = float(os.environ.get("STORAGE_CLAMD_TIMEOUT", "10"))
    sse_raw = (os.environ.get("STORAGE_SSE") or "").strip()
    sse = sse_raw if sse_raw else None
    sse_kms_key_id = os.environ.get("STORAGE_SSE_KMS_KEY_ID") or None
    return StorageConfig(
        endpoint_url=endpoint_url,
        access_key=access_key,
        secret_key=secret_key,
        bucket=bucket,
        region=region,
        use_ssl=use_ssl,
        max_file_bytes=max_mb * 1024 * 1024,
        max_import_bytes=max_import_mb * 1024 * 1024,
        max_offer_photo_bytes=max_offer_photo_mb * 1024 * 1024,
        max_agency_media_bytes=max_agency_media_mb * 1024 * 1024,
        max_inline_media_bytes=max_inline_media_kb * 1024,
        agency_quota_bytes=(quota_mb * 1024 * 1024) if quota_mb is not None else None,
        user_daily_max_files=user_daily_max_files,
        virus_scan=virus_scan,
        virus_scan_required=virus_scan_required,
        presign_default_seconds=presign_seconds,
        clamd_socket=clamd_socket,
        clamd_host=clamd_host,
        clamd_port=clamd_port,
        clamd_timeout=clamd_timeout,
        sse=sse,
        sse_kms_key_id=sse_kms_key_id,
    )


_CONFIG = _load_config()


def get_storage_config() -> StorageConfig:
    return _CONFIG
