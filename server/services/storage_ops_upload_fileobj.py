"""File-like upload operations."""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path
from typing import IO

from .import_file_security import validate_import_file
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
from .storage_scanning import scan_file
from .storage_validation import validate_purpose


def store_fileobj(
    *,
    fileobj: IO[bytes],
    filename: str,
    content_type: str | None,
    purpose: str,
    user_id: int | None,
    role: str | None,
    created_ip: str | None,
) -> str:
    config = get_storage_config()
    agency_id = require_agency_id()
    fileobj.seek(0, os.SEEK_END)
    size_bytes = fileobj.tell()
    fileobj.seek(0)
    validate_purpose(purpose, filename, content_type)
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

    sha256 = hashlib.sha256()
    temp_path: Path | None = None
    try:
        ensure_bucket()
        validate_import = purpose == "import"
        if config.virus_scan or validate_import:
            temp = tempfile.NamedTemporaryFile(delete=False, suffix=Path(filename).suffix)
            temp_path = Path(temp.name)
            try:
                while True:
                    chunk = fileobj.read(1024 * 1024)
                    if not chunk:
                        break
                    sha256.update(chunk)
                    temp.write(chunk)
                temp.flush()
            finally:
                temp.close()
            if validate_import:
                validate_import_file(temp_path, filename)
            if config.virus_scan:
                scan_file(temp_path)
            with temp_path.open("rb") as handle:
                get_storage_client().upload_fileobj(
                    handle,
                    config.bucket,
                    object_key,
                    ExtraArgs={
                        "ContentType": content_type or "application/octet-stream",
                        **sse_args(),
                    },
                )
        else:
            while True:
                chunk = fileobj.read(1024 * 1024)
                if not chunk:
                    break
                sha256.update(chunk)
            fileobj.seek(0)
            get_storage_client().upload_fileobj(
                fileobj,
                config.bucket,
                object_key,
                ExtraArgs={
                    "ContentType": content_type or "application/octet-stream",
                    **sse_args(),
                },
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
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink()
            except OSError:
                pass

    checksum = sha256.hexdigest()
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
