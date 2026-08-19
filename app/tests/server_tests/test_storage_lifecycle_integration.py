from __future__ import annotations

import base64
import uuid
from dataclasses import replace
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

pytest.importorskip("psycopg", reason="storage lifecycle integration tests require Postgres")

from app.tests.server_tests._integration_auth_helpers import (
    admin_conn,
    cleanup_import_test_agency,
    create_agency,
    create_manager_user,
    ensure_django,
)

ensure_django()

from core.data import storage_objects as storage_data  # noqa: E402
from server.pg.schema import ensure_schema  # noqa: E402
from server.pg.uow import get_uow, use_security_context  # noqa: E402
from server.services import offer_photo_image_validation, storage  # noqa: E402

_TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4z8AAAAMBAQDJ/"
    "pLvAAAAAElFTkSuQmCC"
)


class _FakeStorageClient:
    def __init__(self) -> None:
        self.deleted: list[tuple[str, str]] = []

    def delete_object(self, *, Bucket: str, Key: str) -> None:
        self.deleted.append((Bucket, Key))


class _FakePendingUploadClient:
    def __init__(
        self,
        *,
        body: bytes = b"a,b\n1,2\n3,4\n5,6\n\n",
        content_type: str = "text/csv",
    ) -> None:
        self.body = bytes(body)
        self.content_type = content_type
        self.head_calls: list[tuple[str, str]] = []
        self.download_calls: list[tuple[str, str, str]] = []
        self.deleted: list[tuple[str, str]] = []

    def head_object(self, *, Bucket: str, Key: str) -> dict[str, object]:
        self.head_calls.append((Bucket, Key))
        return {
            "ContentLength": len(self.body),
            "ContentType": self.content_type,
            "ETag": '"fake-etag"',
        }

    def download_file(self, bucket: str, key: str, filename: str) -> None:
        self.download_calls.append((bucket, key, filename))
        Path(filename).write_bytes(self.body)

    def delete_object(self, *, Bucket: str, Key: str) -> None:
        self.deleted.append((Bucket, Key))


def _seed_storage_actor(prefix: str) -> tuple[int, int]:
    suffix = uuid.uuid4().hex[:8]
    conn = admin_conn()
    try:
        agency_id = create_agency(conn, f"{prefix.upper()}{suffix}", f"{prefix} {suffix}")
        user_id = create_manager_user(
            conn,
            agency_id=agency_id,
            username=f"{prefix.lower()}_{suffix}",
            password="StrongTestPass_123!",
        )
        conn.commit()
        return int(agency_id), int(user_id)
    finally:
        conn.close()


def _cleanup_storage_actor(*, agency_id: int, user_id: int, storage_id: str = "") -> None:
    _ = storage_id
    cleanup_import_test_agency(agency_id=agency_id, user_id=user_id)


def _create_pending_storage_object(
    *,
    agency_id: int,
    user_id: int,
    suffix: str,
    purpose: str,
    content_type: str,
    size_bytes: int,
    extension: str = ".png",
) -> str:
    with get_uow().transaction(actor="test_storage_pending_offer_photo_seed") as session:
        return storage_data.create_storage_object(
            session,
            bucket="immoapp",
            object_key=f"agency/{agency_id}/offer-photos/{suffix}{extension}",
            user_id=user_id,
            role="manager",
            purpose=purpose,
            content_type=content_type,
            size_bytes=size_bytes,
            checksum=None,
            created_ip="127.0.0.1",
        )


def _image_bytes(image_format: str, *, size: tuple[int, int] = (1, 1)) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", size, color=(240, 10, 10)).save(buffer, format=image_format)
    return buffer.getvalue()


def _storage_failed_event(storage_id: str) -> dict[str, object]:
    with get_uow().session() as session:
        row = session.execute(
            """
            SELECT event_type, details
            FROM storage_events
            WHERE storage_id = %s AND event_type = 'failed'
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (storage_id,),
        ).fetchone()
    assert row is not None
    return dict(row)


def test_storage_delete_and_gc_purge_lifecycle(monkeypatch: pytest.MonkeyPatch) -> None:
    ensure_schema()
    suffix = uuid.uuid4().hex[:8]

    agency_id = 0
    user_id = 0
    storage_id = ""
    conn = admin_conn()
    try:
        agency_id = create_agency(conn, f"STGC{suffix}", f"Storage GC {suffix}")
        user_id = create_manager_user(
            conn,
            agency_id=agency_id,
            username=f"st_gc_{suffix}",
            password="StrongTestPass_123!",
        )
        conn.commit()

        with use_security_context(agency_id=agency_id, is_superuser=False):
            monkeypatch.setattr(
                "server.services.storage_ops_maintenance.storage_events_data.insert_storage_event",
                lambda *args, **kwargs: None,
            )
            with get_uow().transaction(actor="test_storage_seed") as session:
                storage_id = storage_data.create_storage_object(
                    session,
                    bucket="immoapp",
                    object_key=f"tests/{suffix}/seed.bin",
                    user_id=user_id,
                    role="manager",
                    purpose="attachment",
                    content_type="application/octet-stream",
                    size_bytes=4096,
                    checksum="seed-checksum",
                    created_ip="127.0.0.1",
                )
                storage_data.mark_storage_ready(
                    session,
                    storage_id=storage_id,
                    content_type="application/octet-stream",
                    size_bytes=4096,
                    checksum="seed-checksum",
                )
                storage_data.bump_storage_usage(session, agency_id=agency_id, delta_bytes=4096)

            with get_uow().session() as session:
                usage_before = storage_data.get_usage_for_agency(session, agency_id=agency_id)
            assert usage_before >= 4096

            deleted_bytes = storage.mark_storage_deleted(
                storage_id=storage_id,
                user_id=user_id,
                role="manager",
                created_ip="127.0.0.1",
            )
            assert deleted_bytes == 4096

            with get_uow().session() as session:
                record_after_delete = storage_data.get_storage_object(session, storage_id)
                usage_after_delete = storage_data.get_usage_for_agency(session, agency_id=agency_id)
            assert record_after_delete is not None
            assert str(record_after_delete.get("status")) == "deleted"
            assert usage_after_delete == usage_before - 4096

            with get_uow().transaction(actor="test_storage_backdate") as session:
                session.execute(
                    "UPDATE storage_objects SET deleted_at = CURRENT_TIMESTAMP - interval '45 days' WHERE id = %s",
                    (storage_id,),
                )

            fake_client = _FakeStorageClient()
            monkeypatch.setattr(
                "server.services.storage_ops_maintenance.get_storage_client", lambda: fake_client
            )

            purged = storage.purge_deleted_objects(older_than_days=30, limit=10)
            assert purged == 1

            with get_uow().session() as session:
                record_after_purge = storage_data.get_storage_object(session, storage_id)

            assert record_after_purge is not None
            assert str(record_after_purge.get("status")) == "purged"
            assert ("immoapp", f"tests/{suffix}/seed.bin") in fake_client.deleted
    finally:
        if agency_id:
            cleanup_import_test_agency(agency_id=agency_id, user_id=user_id or None)
        conn.close()


def test_complete_presigned_import_upload_accepts_pending_storage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_schema()
    suffix = uuid.uuid4().hex[:8]

    agency_id = 0
    user_id = 0
    storage_id = ""
    conn = admin_conn()
    try:
        agency_id = create_agency(conn, f"STPU{suffix}", f"Storage Pending Upload {suffix}")
        user_id = create_manager_user(
            conn,
            agency_id=agency_id,
            username=f"st_pu_{suffix}",
            password="StrongTestPass_123!",
        )
        conn.commit()

        fake_client = _FakePendingUploadClient()
        with use_security_context(agency_id=agency_id, is_superuser=False):
            monkeypatch.setattr(
                "server.services.storage_ops_upload_presign.get_storage_client",
                lambda: fake_client,
            )
            monkeypatch.setattr(
                "server.services.storage_ops_upload_helpers.storage_events_data.insert_storage_event",
                lambda *args, **kwargs: None,
            )
            monkeypatch.setattr(
                "server.services.storage_ops_access.get_storage_client",
                lambda: fake_client,
            )
            monkeypatch.setattr(
                "server.services.storage_ops_upload_presign.scan_file",
                lambda _path: None,
            )
            with get_uow().transaction(actor="test_storage_pending_seed") as session:
                storage_id = storage_data.create_storage_object(
                    session,
                    bucket="immoapp",
                    object_key=f"agency/{agency_id}/import/{suffix}.csv",
                    user_id=user_id,
                    role="manager",
                    purpose="import",
                    content_type="text/csv",
                    size_bytes=18,
                    checksum=None,
                    created_ip="127.0.0.1",
                )

            result = storage.complete_presigned_upload(
                storage_id=storage_id,
                user_id=user_id,
                role="manager",
                created_ip="127.0.0.1",
            )

            assert result["storage_id"] == storage_id
            assert int(result["size_bytes"]) == len(fake_client.body)

            with get_uow().session() as session:
                record = storage_data.get_storage_object(session, storage_id)
            assert record is not None
            assert str(record.get("status")) == "ready"
            assert fake_client.head_calls
            assert fake_client.download_calls
    finally:
        if agency_id:
            cleanup_import_test_agency(agency_id=agency_id, user_id=user_id or None)
        conn.close()


@pytest.mark.parametrize(
    ("body", "content_type", "extension"),
    [
        pytest.param(_TINY_PNG, "image/png", ".png", id="png"),
        pytest.param(_image_bytes("JPEG"), "image/jpeg", ".jpg", id="jpeg"),
        pytest.param(_image_bytes("BMP"), "image/bmp", ".bmp", id="bmp"),
    ],
)
def test_complete_presigned_offer_photo_validates_actual_image_bytes(
    monkeypatch: pytest.MonkeyPatch,
    body: bytes,
    content_type: str,
    extension: str,
) -> None:
    ensure_schema()
    agency_id, user_id = _seed_storage_actor("offer_photo_valid")
    storage_id = ""
    try:
        fake_client = _FakePendingUploadClient(body=body, content_type=content_type)
        with use_security_context(agency_id=agency_id, is_superuser=False):
            monkeypatch.setattr(
                "server.services.storage_ops_upload_presign.get_storage_client",
                lambda: fake_client,
            )
            monkeypatch.setattr(
                "server.services.storage_ops_access.get_storage_client",
                lambda: fake_client,
            )
            monkeypatch.setattr(
                "server.services.storage_ops_upload_helpers.storage_events_data.insert_storage_event",
                lambda *args, **kwargs: None,
            )
            storage_id = _create_pending_storage_object(
                agency_id=agency_id,
                user_id=user_id,
                suffix="valid",
                purpose="offer_photo",
                content_type=content_type,
                size_bytes=len(body),
                extension=extension,
            )

            result = storage.complete_presigned_upload(
                storage_id=storage_id,
                user_id=user_id,
                role="manager",
                created_ip="127.0.0.1",
            )

            assert result["storage_id"] == storage_id
            assert int(result["size_bytes"]) == len(body)
            with get_uow().session() as session:
                record = storage_data.get_storage_object(session, storage_id)
            assert record is not None
            assert record["status"] == "ready"
            assert fake_client.download_calls
            assert fake_client.deleted == []
    finally:
        _cleanup_storage_actor(agency_id=agency_id, user_id=user_id, storage_id=storage_id)


@pytest.mark.parametrize(
    "body",
    [
        b"this is not really a png",
        _TINY_PNG[:16],
    ],
)
def test_complete_presigned_offer_photo_rejects_invalid_image_bytes(
    monkeypatch: pytest.MonkeyPatch,
    body: bytes,
) -> None:
    ensure_schema()
    agency_id, user_id = _seed_storage_actor("offer_photo_invalid")
    storage_id = ""
    try:
        fake_client = _FakePendingUploadClient(body=body, content_type="image/png")
        with use_security_context(agency_id=agency_id, is_superuser=False):
            monkeypatch.setattr(
                "server.services.storage_ops_upload_presign.get_storage_client",
                lambda: fake_client,
            )
            monkeypatch.setattr(
                "server.services.storage_ops_access.get_storage_client",
                lambda: fake_client,
            )
            storage_id = _create_pending_storage_object(
                agency_id=agency_id,
                user_id=user_id,
                suffix="invalid",
                purpose="offer_photo",
                content_type="image/png",
                size_bytes=len(body),
            )

            with pytest.raises(storage.StorageError, match="Invalid property photo image"):
                storage.complete_presigned_upload(
                    storage_id=storage_id,
                    user_id=user_id,
                    role="manager",
                    created_ip="127.0.0.1",
                )

            with get_uow().session() as session:
                record = storage_data.get_storage_object(session, storage_id)
            assert record is not None
            assert record["status"] == "failed"
            assert record["checksum"] == "image_validation"
            event = _storage_failed_event(storage_id)
            assert event["event_type"] == "failed"
            assert event["details"]["error"] == "image_validation"
            assert "Invalid property photo image" in str(event["details"]["message"])
            assert fake_client.deleted == [
                ("immoapp", f"agency/{agency_id}/offer-photos/invalid.png")
            ]
    finally:
        _cleanup_storage_actor(agency_id=agency_id, user_id=user_id, storage_id=storage_id)


def test_complete_presigned_offer_photo_records_virus_scan_failure_separately(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_schema()
    agency_id, user_id = _seed_storage_actor("offer_photo_virus")
    storage_id = ""
    body = _image_bytes("PNG")
    try:
        fake_client = _FakePendingUploadClient(body=body, content_type="image/png")
        with use_security_context(agency_id=agency_id, is_superuser=False):
            import server.services.storage_ops_upload_presign as upload_presign

            original_config = upload_presign.get_storage_config()
            monkeypatch.setattr(upload_presign, "get_storage_client", lambda: fake_client)
            monkeypatch.setattr(
                "server.services.storage_ops_access.get_storage_client",
                lambda: fake_client,
            )
            monkeypatch.setattr(
                upload_presign,
                "get_storage_config",
                lambda: replace(original_config, virus_scan=True),
            )

            def _raise_virus(_path: Path) -> None:
                raise storage.StorageError("Virus scan failed.")

            monkeypatch.setattr(upload_presign, "scan_file", _raise_virus)
            storage_id = _create_pending_storage_object(
                agency_id=agency_id,
                user_id=user_id,
                suffix="virus",
                purpose="offer_photo",
                content_type="image/png",
                size_bytes=len(body),
            )

            with pytest.raises(storage.StorageError, match="Virus scan failed"):
                storage.complete_presigned_upload(
                    storage_id=storage_id,
                    user_id=user_id,
                    role="manager",
                    created_ip="127.0.0.1",
                )

            with get_uow().session() as session:
                record = storage_data.get_storage_object(session, storage_id)
            assert record is not None
            assert record["status"] == "failed"
            assert record["checksum"] == "virus_scan"
            event = _storage_failed_event(storage_id)
            assert event["details"]["error"] == "virus_scan"
            assert event["details"]["error"] != "image_validation"
    finally:
        _cleanup_storage_actor(agency_id=agency_id, user_id=user_id, storage_id=storage_id)


def test_complete_presigned_offer_photo_rejects_dimension_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_schema()
    agency_id, user_id = _seed_storage_actor("offer_photo_pixels")
    storage_id = ""
    body = _image_bytes("PNG", size=(2, 2))
    try:
        fake_client = _FakePendingUploadClient(body=body, content_type="image/png")
        with use_security_context(agency_id=agency_id, is_superuser=False):
            monkeypatch.setattr(
                "server.services.storage_ops_upload_presign.get_storage_client",
                lambda: fake_client,
            )
            monkeypatch.setattr(
                "server.services.storage_ops_access.get_storage_client",
                lambda: fake_client,
            )
            monkeypatch.setattr(offer_photo_image_validation, "MAX_OFFER_PHOTO_PIXELS", 3)
            storage_id = _create_pending_storage_object(
                agency_id=agency_id,
                user_id=user_id,
                suffix="pixels",
                purpose="offer_photo",
                content_type="image/png",
                size_bytes=len(body),
            )

            with pytest.raises(storage.StorageError, match="Invalid property photo image"):
                storage.complete_presigned_upload(
                    storage_id=storage_id,
                    user_id=user_id,
                    role="manager",
                    created_ip="127.0.0.1",
                )

            with get_uow().session() as session:
                record = storage_data.get_storage_object(session, storage_id)
            assert record is not None
            assert record["status"] == "failed"
            assert record["checksum"] == "image_validation"
            event = _storage_failed_event(storage_id)
            assert event["details"]["error"] == "image_validation"
    finally:
        _cleanup_storage_actor(agency_id=agency_id, user_id=user_id, storage_id=storage_id)
