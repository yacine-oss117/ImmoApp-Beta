"""Presigned upload operations."""

from __future__ import annotations

import logging
from pathlib import Path

from core.contracts.offer_photo_media import OFFER_PHOTO_PURPOSE
from core.data import storage_objects as storage_data
from server.immoapp_server.observability import _normalize_span_attribute, business_span
from server.pg.uow import get_uow

from .import_file_security import validate_import_file
from .offer_photo_image_validation import (
    OfferPhotoImageValidationError,
    validate_offer_photo_image,
)
from .storage_client import (
    BotoCoreError,
    ClientError,
    apply_sse_presign,
    ensure_bucket,
    get_storage_client,
)
from .storage_config import get_storage_config
from .storage_errors import StorageError
from .storage_ops_access import download_to_temp
from .storage_ops_upload_helpers import (
    create_storage_record,
    mark_storage_failed,
    mark_storage_ready,
    require_agency_id,
)
from .storage_ops_upload_utils import build_object_key
from .storage_scanning import scan_file
from .storage_validation import validate_purpose

logger = logging.getLogger(__name__)


def generate_presigned_upload(
    *,
    filename: str,
    content_type: str | None,
    purpose: str,
    size_bytes: int,
    user_id: int | None,
    role: str | None,
    created_ip: str | None,
    expires_seconds: int | None = None,
) -> dict[str, object]:
    with business_span(
        "storage.generate_presigned_upload",
        attributes={
            "storage.purpose": purpose,
            "storage.requested_size_bytes": size_bytes,
            "storage.has_content_type": bool(content_type),
        },
    ) as span:
        config = get_storage_config()
        agency_id = require_agency_id()
        span.set_attribute("storage.agency_id", agency_id)
        validate_purpose(purpose, filename, content_type)
        object_key = build_object_key(agency_id, purpose, filename)
        ensure_bucket()

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
        span.set_attribute("storage.storage_id", storage_id)

        ttl = expires_seconds or config.presign_default_seconds
        span.set_attribute("storage.presign_ttl_seconds", ttl)
        conditions: list[object] = [["content-length-range", 1, config.max_file_bytes]]
        fields: dict[str, str] = {}
        if content_type:
            conditions.append({"Content-Type": content_type})
            fields["Content-Type"] = content_type
        apply_sse_presign(fields, conditions)

        presigned = get_storage_client().generate_presigned_post(
            Bucket=config.bucket,
            Key=object_key,
            Fields=fields,
            Conditions=conditions,
            ExpiresIn=ttl,
        )

        return {
            "storage_id": storage_id,
            "bucket": config.bucket,
            "object_key": object_key,
            "url": presigned["url"],
            "fields": presigned["fields"],
            "expires_in": ttl,
        }


def complete_presigned_upload(
    *,
    storage_id: str,
    user_id: int | None,
    role: str | None,
    created_ip: str | None,
) -> dict[str, object]:
    with business_span(
        "storage.complete_presigned_upload",
        attributes={"storage.storage_id": storage_id},
    ) as span:
        config = get_storage_config()
        with get_uow().session() as session:
            record = storage_data.get_storage_object(session, storage_id)
        if not record:
            span.set_attribute("storage.record_exists", False)
            raise StorageError("Object not found.")
        span.set_attribute("storage.record_exists", True)
        if record.get("purpose") is not None:
            span.set_attribute("storage.purpose", _normalize_span_attribute(record["purpose"]))
        if isinstance(record.get("agency_id"), int):
            span.set_attribute("storage.agency_id", record["agency_id"])

        try:
            head = get_storage_client().head_object(
                Bucket=record["bucket"],
                Key=record["object_key"],
            )
        except (BotoCoreError, ClientError) as exc:
            raise StorageError("Failed to confirm upload.") from exc

        size_bytes = int(head.get("ContentLength") or 0)
        span.set_attribute("storage.size_bytes", size_bytes)
        content_type = head.get("ContentType")
        expected_size = record.get("size_bytes") or 0
        if size_bytes <= 0:
            raise StorageError("Uploaded object is empty.")
        if size_bytes > config.max_file_bytes or (expected_size and size_bytes > expected_size):
            get_storage_client().delete_object(
                Bucket=record["bucket"],
                Key=record["object_key"],
            )
            mark_storage_failed(
                storage_id=storage_id,
                message="size_limit",
                user_id=user_id,
                role=role,
                created_ip=created_ip,
                purpose=str(record.get("purpose", "") or ""),
                details={"error": "size_limit"},
            )
            raise StorageError("Uploaded object exceeds allowed size.")

        validate_purpose(record.get("purpose", ""), record.get("object_key", ""), content_type)

        purpose = str(record.get("purpose", "") or "")
        validate_import = purpose == "import"
        validate_offer_photo = purpose == OFFER_PHOTO_PURPOSE
        if config.virus_scan or validate_import or validate_offer_photo:
            temp_path: Path | None = None
            span.set_attribute("storage.virus_scan_enabled", bool(config.virus_scan))
            try:
                temp_path = download_to_temp(
                    storage_id,
                    suffix=Path(record.get("object_key", "")).suffix or None,
                    require_ready=False,
                )
                if validate_import:
                    validate_import_file(temp_path, str(record.get("object_key", "")))
                if validate_offer_photo:
                    validate_offer_photo_image(temp_path)
                if config.virus_scan:
                    scan_file(temp_path)
            except StorageError as exc:
                failure_marker = (
                    "image_validation"
                    if isinstance(exc, OfferPhotoImageValidationError)
                    else "virus_scan"
                )
                try:
                    get_storage_client().delete_object(
                        Bucket=record["bucket"],
                        Key=record["object_key"],
                    )
                except (BotoCoreError, ClientError):
                    logger.warning("Failed to delete infected upload %s", storage_id)
                mark_storage_failed(
                    storage_id=storage_id,
                    message=failure_marker,
                    user_id=user_id,
                    role=role,
                    created_ip=created_ip,
                    purpose=purpose,
                    details={"error": failure_marker, "message": str(exc)},
                )
                raise
            finally:
                if temp_path is not None:
                    try:
                        temp_path.unlink()
                    except OSError:
                        pass
        else:
            span.set_attribute("storage.virus_scan_enabled", False)

        mark_storage_ready(
            storage_id=storage_id,
            content_type=content_type,
            size_bytes=size_bytes,
            checksum=head.get("ETag"),
            agency_id=record["agency_id"],
            user_id=user_id,
            role=role,
            created_ip=created_ip,
            purpose=str(record.get("purpose", "") or ""),
        )
        span.set_attribute("storage.status", "ready")

        return {"storage_id": storage_id, "size_bytes": size_bytes, "content_type": content_type}
