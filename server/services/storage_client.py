"""Storage client helpers (S3/MinIO)."""

from __future__ import annotations

import threading
import time
from typing import Any

import boto3
from botocore.client import Config
from botocore.exceptions import BotoCoreError, ClientError

from .storage_config import get_storage_config
from .storage_errors import StorageError, StorageNotReadyError

_CLIENT: Any | None = None
_CLIENT_CONFIG_FINGERPRINT: tuple[object, ...] | None = None
_CLIENT_LOCK = threading.RLock()
_BUCKET_READY_UNTIL_MONOTONIC = 0.0
_BUCKET_READY_KEY: tuple[object, ...] | None = None
_BUCKET_READY_LOCK = threading.RLock()
_BUCKET_READY_TTL_SECONDS = 60.0


def _client_fingerprint(config: Any) -> tuple[object, ...]:
    return (
        config.endpoint_url,
        config.access_key,
        config.secret_key,
        config.region,
        config.use_ssl,
    )


def _build_client(config: Any) -> Any:
    return boto3.client(
        "s3",
        endpoint_url=config.endpoint_url,
        aws_access_key_id=config.access_key,
        aws_secret_access_key=config.secret_key,
        region_name=config.region,
        use_ssl=config.use_ssl,
        config=Config(
            signature_version="s3v4",
            connect_timeout=3,
            read_timeout=10,
            retries={"max_attempts": 3, "mode": "standard"},
        ),
    )


def get_storage_client() -> Any:
    global _CLIENT, _CLIENT_CONFIG_FINGERPRINT
    config = get_storage_config()
    fingerprint = _client_fingerprint(config)
    if _CLIENT is not None and _CLIENT_CONFIG_FINGERPRINT == fingerprint:
        return _CLIENT
    if not config.access_key or not config.secret_key:
        raise StorageError("Storage credentials are not configured.")
    with _CLIENT_LOCK:
        if _CLIENT is not None and _CLIENT_CONFIG_FINGERPRINT == fingerprint:
            return _CLIENT
        _CLIENT = _build_client(config)
        _CLIENT_CONFIG_FINGERPRINT = fingerprint
        return _CLIENT


def _is_missing_bucket_error(exc: ClientError) -> bool:
    error = exc.response.get("Error", {}) if isinstance(exc.response, dict) else {}
    code = str(error.get("Code", "")).strip()
    status_code = (
        exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode", 0)
        if isinstance(exc.response, dict)
        else 0
    )
    return code in {"404", "NoSuchBucket", "NotFound"} or int(status_code or 0) == 404


def _bucket_ready_key(config: Any, client: Any) -> tuple[object, ...]:
    return _client_fingerprint(config) + (config.bucket, id(client))


def _bucket_error_code(exc: ClientError) -> str:
    error = exc.response.get("Error", {}) if isinstance(exc.response, dict) else {}
    return str(error.get("Code", "")).strip()


def _bucket_error_status(exc: ClientError) -> int:
    if not isinstance(exc.response, dict):
        return 0
    return int(exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode", 0) or 0)


def _is_retryable_bucket_error(exc: ClientError) -> bool:
    code = _bucket_error_code(exc)
    status_code = _bucket_error_status(exc)
    return code in {
        "RequestTimeout",
        "RequestTimeoutException",
        "SlowDown",
        "InternalError",
        "ServiceUnavailable",
    } or status_code in {408, 429, 500, 502, 503, 504}


def ensure_bucket() -> None:
    global _BUCKET_READY_KEY, _BUCKET_READY_UNTIL_MONOTONIC
    client = get_storage_client()
    config = get_storage_config()
    ready_key = _bucket_ready_key(config, client)
    now = time.monotonic()
    if ready_key == _BUCKET_READY_KEY and now < _BUCKET_READY_UNTIL_MONOTONIC:
        return
    with _BUCKET_READY_LOCK:
        now = time.monotonic()
        if ready_key == _BUCKET_READY_KEY and now < _BUCKET_READY_UNTIL_MONOTONIC:
            return
        try:
            client.head_bucket(Bucket=config.bucket)
        except ClientError as exc:
            if not _is_missing_bucket_error(exc):
                _BUCKET_READY_KEY = None
                _BUCKET_READY_UNTIL_MONOTONIC = 0.0
                if _is_retryable_bucket_error(exc):
                    raise StorageNotReadyError(
                        "Import storage is still warming up.",
                        code="IMPORT_STORAGE_NOT_READY",
                        retry_after_ms=1500,
                    ) from exc
                raise
            try:
                client.create_bucket(Bucket=config.bucket)
            except ClientError as create_exc:
                _BUCKET_READY_KEY = None
                _BUCKET_READY_UNTIL_MONOTONIC = 0.0
                if _is_retryable_bucket_error(create_exc):
                    raise StorageNotReadyError(
                        "Import storage is not ready yet.",
                        code="IMPORT_SERVICE_WARMING_UP",
                        retry_after_ms=2000,
                    ) from create_exc
                raise
            except BotoCoreError as create_exc:
                _BUCKET_READY_KEY = None
                _BUCKET_READY_UNTIL_MONOTONIC = 0.0
                raise StorageNotReadyError(
                    "Import storage is not ready yet.",
                    code="IMPORT_SERVICE_WARMING_UP",
                    retry_after_ms=2000,
                ) from create_exc
        except BotoCoreError as exc:
            _BUCKET_READY_KEY = None
            _BUCKET_READY_UNTIL_MONOTONIC = 0.0
            raise StorageNotReadyError(
                "Import storage is still warming up.",
                code="IMPORT_STORAGE_NOT_READY",
                retry_after_ms=1500,
            ) from exc
        _BUCKET_READY_KEY = ready_key
        _BUCKET_READY_UNTIL_MONOTONIC = time.monotonic() + _BUCKET_READY_TTL_SECONDS


def sse_args() -> dict[str, str]:
    config = get_storage_config()
    if not config.sse:
        return {}
    args: dict[str, str] = {"ServerSideEncryption": config.sse}
    if config.sse.lower() == "aws:kms" and config.sse_kms_key_id:
        args["SSEKMSKeyId"] = config.sse_kms_key_id
    return args


def apply_sse_presign(fields: dict[str, str], conditions: list[object]) -> None:
    config = get_storage_config()
    if not config.sse:
        return
    fields["x-amz-server-side-encryption"] = config.sse
    conditions.append({"x-amz-server-side-encryption": config.sse})
    if config.sse.lower() == "aws:kms" and config.sse_kms_key_id:
        fields["x-amz-server-side-encryption-aws-kms-key-id"] = config.sse_kms_key_id
        conditions.append(
            {
                "x-amz-server-side-encryption-aws-kms-key-id": config.sse_kms_key_id,
            }
        )


__all__ = [
    "BotoCoreError",
    "ClientError",
    "get_storage_client",
    "ensure_bucket",
    "sse_args",
    "apply_sse_presign",
]
