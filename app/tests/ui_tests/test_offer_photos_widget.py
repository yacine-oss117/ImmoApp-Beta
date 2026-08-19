from __future__ import annotations

import inspect
import time
from collections.abc import Callable
from pathlib import Path

import pytest
from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QWidget

pytestmark = pytest.mark.ui


def _tiny_png_bytes() -> bytes:
    return bytes.fromhex(
        "89504e470d0a1a0a0000000d4948445200000001000000010802000000907753"
        "de0000000c49444154789c63606060000000040001f61738550000000049454e44ae426082"
    )


def _process_events_until(
    qapp: QApplication,
    predicate: Callable[[], bool],
    *,
    timeout: float = 1.0,
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qapp.processEvents()
        if predicate():
            return
    qapp.processEvents()


def test_offer_photos_widget_shows_persisted_offer_hooks(
    monkeypatch: pytest.MonkeyPatch,
    qapp: QApplication,
) -> None:
    from app.widgets.offer_photos_widget import OfferPhotosWidget

    monkeypatch.setattr("app.widgets.offer_photos_widget.get_offline_mode", lambda: False)
    monkeypatch.setattr(
        "app.widgets.offer_photos_widget.offer_photo_service.list_offer_photos",
        lambda offer_id: [
            {
                "id": 42,
                "offer_id": offer_id,
                "storage_id": "550e8400-e29b-41d4-a716-446655440000",
                "position": 0,
                "deleted_at": None,
            }
        ],
    )
    monkeypatch.setattr(
        "app.widgets.offer_photos_widget.offer_photo_service.download_offer_photo_thumbnail_bytes",
        lambda _storage_id, *, max_bytes: b"",
    )

    widget = OfferPhotosWidget(offer_id=123, offer_number=1)
    try:
        assert widget.findChild(QWidget, "offerPhotosSection_123") is not None
        add_button = widget.findChild(QPushButton, "offerPhotosAddButton_123")
        assert add_button is not None
        assert add_button.isEnabled()
        assert widget.findChild(QWidget, "offerPhotosList_123") is not None
        assert widget.findChild(QWidget, "offerPhotoItem_42") is not None
        assert widget.findChild(QPushButton, "offerPhotoDeleteButton_42") is not None
        status = widget.findChild(QLabel, "offerPhotosStatus_123")
        assert status is not None
        assert "1 property photo" in status.text()
    finally:
        widget.close()
        widget.deleteLater()
        qapp.processEvents()


def test_offer_photos_widget_disables_unsaved_offer(qapp: QApplication) -> None:
    from app.widgets.offer_photos_widget import OfferPhotosWidget

    widget = OfferPhotosWidget(offer_id=0, offer_number=3)
    try:
        assert widget.findChild(QWidget, "offerPhotosSection_unsaved_3") is not None
        add_button = widget.findChild(QPushButton, "offerPhotosAddButton_unsaved_3")
        assert add_button is not None
        assert not add_button.isEnabled()
        status = widget.findChild(QLabel, "offerPhotosStatus_unsaved_3")
        assert status is not None
        assert "Save this offer before adding property photos" in status.text()
    finally:
        widget.close()
        widget.deleteLater()
        qapp.processEvents()


def test_offer_photos_widget_disables_upload_offline(
    monkeypatch: pytest.MonkeyPatch,
    qapp: QApplication,
) -> None:
    from app.widgets.offer_photos_widget import OfferPhotosWidget

    monkeypatch.setattr("app.widgets.offer_photos_widget.get_offline_mode", lambda: True)

    widget = OfferPhotosWidget(offer_id=123, offer_number=1)
    try:
        add_button = widget.findChild(QPushButton, "offerPhotosAddButton_123")
        assert add_button is not None
        assert not add_button.isEnabled()
        status = widget.findChild(QLabel, "offerPhotosStatus_123")
        assert status is not None
        assert "unavailable while offline" in status.text()
    finally:
        widget.close()
        widget.deleteLater()
        qapp.processEvents()


def test_offer_photo_supported_types_use_shared_client_contract() -> None:
    from app.services.offer_photos import _guess_content_type
    from core.contracts.offer_photo_media import (
        OFFER_PHOTO_CONTENT_TYPES,
        OFFER_PHOTO_EXTENSIONS,
        OFFER_PHOTO_FILE_DIALOG_FILTER,
        is_supported_offer_photo_filename,
    )

    assert set(OFFER_PHOTO_EXTENSIONS) == {".png", ".jpg", ".jpeg", ".bmp"}
    assert set(OFFER_PHOTO_CONTENT_TYPES) == {"image/png", "image/jpeg", "image/bmp"}
    assert is_supported_offer_photo_filename("front.png")
    assert is_supported_offer_photo_filename("front.JPG")
    assert not is_supported_offer_photo_filename("front.webp")
    assert _guess_content_type("front.bmp") == "image/bmp"
    assert _guess_content_type("front.webp") == "application/octet-stream"
    assert "*.webp" not in OFFER_PHOTO_FILE_DIALOG_FILTER.lower()
    assert "image/webp" not in OFFER_PHOTO_CONTENT_TYPES


def test_refresh_photos_starts_thumbnail_loading_off_gui_thread(
    monkeypatch: pytest.MonkeyPatch,
    qapp: QApplication,
) -> None:
    from app.widgets import offer_photos_widget
    from app.widgets.offer_photos_widget import OfferPhotosWidget

    calls: list[str] = []

    def fake_download(_storage_id: str, *, max_bytes: int) -> bytes:
        assert max_bytes == offer_photos_widget._MAX_THUMBNAIL_BYTES
        assert QThread.currentThread() != qapp.thread()
        calls.append("worker")
        return b"not an image"

    monkeypatch.setattr("app.widgets.offer_photos_widget.get_offline_mode", lambda: False)
    monkeypatch.setattr(
        "app.widgets.offer_photos_widget.offer_photo_service.list_offer_photos",
        lambda offer_id: [
            {
                "id": 42,
                "offer_id": offer_id,
                "storage_id": "550e8400-e29b-41d4-a716-446655440000",
                "position": 0,
                "deleted_at": None,
            }
        ],
    )
    monkeypatch.setattr(
        "app.widgets.offer_photos_widget.offer_photo_service.download_offer_photo_thumbnail_bytes",
        fake_download,
    )

    widget = OfferPhotosWidget(offer_id=123, offer_number=1)
    try:
        assert widget.findChild(QWidget, "offerPhotoItem_42") is not None
        assert widget.findChild(QLabel, "offerPhotoThumbnail_42") is not None
        _process_events_until(qapp, lambda: bool(calls))
        assert calls == ["worker"]
    finally:
        widget.close()
        widget.deleteLater()
        qapp.processEvents()


def test_thumbnail_success_marks_loaded_hook(
    monkeypatch: pytest.MonkeyPatch,
    qapp: QApplication,
) -> None:
    from app.widgets.offer_photos_widget import OfferPhotosWidget

    monkeypatch.setattr("app.widgets.offer_photos_widget.get_offline_mode", lambda: False)
    monkeypatch.setattr(
        "app.widgets.offer_photos_widget.offer_photo_service.list_offer_photos",
        lambda offer_id: [
            {
                "id": 88,
                "offer_id": offer_id,
                "storage_id": "550e8400-e29b-41d4-a716-446655440088",
                "position": 0,
                "deleted_at": None,
            }
        ],
    )
    monkeypatch.setattr(
        "app.widgets.offer_photos_widget.offer_photo_service.download_offer_photo_thumbnail_bytes",
        lambda _storage_id, *, max_bytes: _tiny_png_bytes(),
    )

    widget = OfferPhotosWidget(offer_id=123, offer_number=1)
    try:
        preview = widget.findChild(QLabel, "offerPhotoThumbnail_88")
        assert preview is not None
        _process_events_until(
            qapp,
            lambda: preview.property("photoThumbnailState") == "loaded",
        )
        assert preview.property("photoThumbnailLoaded") is True
        assert preview.accessibleName() == "Property photo thumbnail loaded"
        pixmap = preview.pixmap()
        assert pixmap is not None and not pixmap.isNull()
    finally:
        widget.close()
        widget.deleteLater()
        qapp.processEvents()


def test_thumbnail_invalid_bytes_mark_failed_not_loading(
    monkeypatch: pytest.MonkeyPatch,
    qapp: QApplication,
) -> None:
    from app.widgets.offer_photos_widget import OfferPhotosWidget

    monkeypatch.setattr("app.widgets.offer_photos_widget.get_offline_mode", lambda: False)
    monkeypatch.setattr(
        "app.widgets.offer_photos_widget.offer_photo_service.list_offer_photos",
        lambda offer_id: [
            {
                "id": 77,
                "offer_id": offer_id,
                "storage_id": "550e8400-e29b-41d4-a716-446655440077",
                "position": 0,
                "deleted_at": None,
            }
        ],
    )
    monkeypatch.setattr(
        "app.widgets.offer_photos_widget.offer_photo_service.download_offer_photo_thumbnail_bytes",
        lambda _storage_id, *, max_bytes: b"not an image",
    )

    widget = OfferPhotosWidget(offer_id=123, offer_number=1)
    try:
        row = widget.findChild(QWidget, "offerPhotoItem_77")
        preview = widget.findChild(QLabel, "offerPhotoThumbnail_77")
        assert row is not None
        assert preview is not None
        _process_events_until(qapp, lambda: True)
        assert widget.findChild(QWidget, "offerPhotoItem_77") is row
        _process_events_until(
            qapp,
            lambda: preview.property("photoThumbnailState") == "failed",
        )
        assert preview.text() == "Preview unavailable"
        assert preview.property("photoThumbnailLoaded") is False
        assert preview.accessibleName() == "Property photo thumbnail unavailable"
        pixmap = preview.pixmap()
        assert pixmap is None or pixmap.isNull()
    finally:
        widget.close()
        widget.deleteLater()
        qapp.processEvents()


def test_thumbnail_non_bytes_payload_marks_failed_not_loading(
    monkeypatch: pytest.MonkeyPatch,
    qapp: QApplication,
) -> None:
    from app.widgets.offer_photos_widget import OfferPhotosWidget

    monkeypatch.setattr("app.widgets.offer_photos_widget.get_offline_mode", lambda: False)
    monkeypatch.setattr(
        "app.widgets.offer_photos_widget.offer_photo_service.list_offer_photos",
        lambda offer_id: [
            {
                "id": 66,
                "offer_id": offer_id,
                "storage_id": "550e8400-e29b-41d4-a716-446655440066",
                "position": 0,
                "deleted_at": None,
            }
        ],
    )
    monkeypatch.setattr(
        "app.widgets.offer_photos_widget.offer_photo_service.download_offer_photo_thumbnail_bytes",
        lambda _storage_id, *, max_bytes: "not-bytes",
    )

    widget = OfferPhotosWidget(offer_id=123, offer_number=1)
    try:
        preview = widget.findChild(QLabel, "offerPhotoThumbnail_66")
        assert preview is not None
        _process_events_until(
            qapp,
            lambda: preview.property("photoThumbnailState") == "failed",
        )
        assert preview.text() == "Preview unavailable"
        assert preview.property("photoThumbnailLoaded") is False
        assert preview.accessibleName() == "Property photo thumbnail unavailable"
    finally:
        widget.close()
        widget.deleteLater()
        qapp.processEvents()


def test_offer_photo_widget_source_keeps_refresh_network_free() -> None:
    from app.widgets.offer_photos_widget import OfferPhotosWidget

    source = inspect.getsource(OfferPhotosWidget.refresh_photos)
    assert "requests.get" not in source
    assert "presign_offer_photo_url" not in source
    assert "download_offer_photo_thumbnail_bytes" not in source


class _FakeUploadWorker(QObject):
    uploaded = Signal(int)
    failed = Signal(str)
    finished = Signal()

    instances: list[_FakeUploadWorker] = []

    def __init__(self, *, offer_id: int, source_path: str) -> None:
        super().__init__(None)
        self.offer_id = offer_id
        self.source_path = source_path
        self.started = False
        self.deleted_later = False
        _FakeUploadWorker.instances.append(self)

    def start(self) -> None:
        self.started = True

    def deleteLater(self) -> None:  # noqa: N802
        self.deleted_later = True
        super().deleteLater()

    def complete(self, photo_id: int = 1234) -> None:
        self.uploaded.emit(photo_id)
        self.finished.emit()


def _install_fake_upload(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _FakeUploadWorker.instances.clear()
    image_path = tmp_path / "front.png"
    image_path.write_bytes(b"fake png bytes")
    monkeypatch.setattr(
        "app.widgets.offer_photos_widget.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(image_path), ""),
    )
    monkeypatch.setattr(
        "app.widgets.offer_photos_widget.offer_photo_service.validate_offer_photo_path",
        lambda _path: None,
    )
    monkeypatch.setattr(
        "app.widgets.offer_photos_widget._UploadWorker",
        _FakeUploadWorker,
    )


def test_upload_success_refreshes_current_offer(
    monkeypatch: pytest.MonkeyPatch,
    qapp: QApplication,
    tmp_path: Path,
) -> None:
    from app.widgets.offer_photos_widget import OfferPhotosWidget

    list_calls: list[int] = []

    def fake_list_offer_photos(offer_id: int) -> list[dict[str, object]]:
        list_calls.append(int(offer_id))
        return []

    monkeypatch.setattr("app.widgets.offer_photos_widget.get_offline_mode", lambda: False)
    monkeypatch.setattr(
        "app.widgets.offer_photos_widget.offer_photo_service.list_offer_photos",
        fake_list_offer_photos,
    )
    _install_fake_upload(monkeypatch, tmp_path)

    widget = OfferPhotosWidget(offer_id=123, offer_number=1)
    try:
        widget._choose_photo()
        assert _FakeUploadWorker.instances[-1].started
        _FakeUploadWorker.instances[-1].complete()
        qapp.processEvents()
        assert list_calls[-1] == 123
        status = widget.findChild(QLabel, "offerPhotosStatus_123")
        assert status is not None
        assert status.text() == "No property photos yet."
    finally:
        widget.close()
        widget.deleteLater()
        qapp.processEvents()


def test_delete_photo_passes_stable_idempotency_key(
    monkeypatch: pytest.MonkeyPatch,
    qapp: QApplication,
) -> None:
    from app.widgets.offer_photos_widget import OfferPhotosWidget

    delete_calls: list[tuple[int, str]] = []

    monkeypatch.setattr("app.widgets.offer_photos_widget.get_offline_mode", lambda: False)
    monkeypatch.setattr(
        "app.widgets.offer_photos_widget.offer_photo_service.list_offer_photos",
        lambda _offer_id: [],
    )

    def fake_delete(photo_id: int, *, idempotency_key: str) -> bool:
        delete_calls.append((int(photo_id), str(idempotency_key)))
        return True

    monkeypatch.setattr(
        "app.widgets.offer_photos_widget.offer_photo_service.delete_offer_photo",
        fake_delete,
    )

    widget = OfferPhotosWidget(offer_id=123, offer_number=1)
    try:
        widget._delete_photo(42)
        assert len(delete_calls) == 1
        photo_id, key = delete_calls[0]
        assert photo_id == 42
        assert key.startswith("offer-photo-delete:42:")
    finally:
        widget.close()
        widget.deleteLater()
        qapp.processEvents()


def test_delete_photo_reuses_pending_key_after_transient_failure(
    monkeypatch: pytest.MonkeyPatch,
    qapp: QApplication,
) -> None:
    from app.widgets.offer_photos_widget import OfferPhotosWidget

    delete_calls: list[str] = []

    monkeypatch.setattr("app.widgets.offer_photos_widget.get_offline_mode", lambda: False)
    monkeypatch.setattr(
        "app.widgets.offer_photos_widget.offer_photo_service.list_offer_photos",
        lambda _offer_id: [],
    )

    def fake_delete(_photo_id: int, *, idempotency_key: str) -> bool:
        delete_calls.append(str(idempotency_key))
        if len(delete_calls) == 1:
            raise RuntimeError("temporary network failure")
        return True

    monkeypatch.setattr(
        "app.widgets.offer_photos_widget.offer_photo_service.delete_offer_photo",
        fake_delete,
    )

    widget = OfferPhotosWidget(offer_id=123, offer_number=1)
    try:
        widget._delete_photo(42)
        assert len(delete_calls) == 1
        assert widget._pending_delete_keys[42] == delete_calls[0]

        widget._delete_photo(42)
        assert delete_calls == [delete_calls[0], delete_calls[0]]
        assert 42 not in widget._pending_delete_keys
    finally:
        widget.close()
        widget.deleteLater()
        qapp.processEvents()


def test_delete_photo_success_clears_key_and_later_operation_gets_new_key(
    monkeypatch: pytest.MonkeyPatch,
    qapp: QApplication,
) -> None:
    from app.widgets.offer_photos_widget import OfferPhotosWidget

    delete_calls: list[str] = []

    monkeypatch.setattr("app.widgets.offer_photos_widget.get_offline_mode", lambda: False)
    monkeypatch.setattr(
        "app.widgets.offer_photos_widget.offer_photo_service.list_offer_photos",
        lambda _offer_id: [],
    )

    def fake_delete(_photo_id: int, *, idempotency_key: str) -> bool:
        delete_calls.append(str(idempotency_key))
        return True

    monkeypatch.setattr(
        "app.widgets.offer_photos_widget.offer_photo_service.delete_offer_photo",
        fake_delete,
    )

    widget = OfferPhotosWidget(offer_id=123, offer_number=1)
    try:
        widget._delete_photo(42)
        assert 42 not in widget._pending_delete_keys
        widget._delete_photo(42)
        assert len(delete_calls) == 2
        assert delete_calls[0] != delete_calls[1]
        assert all(key.startswith("offer-photo-delete:42:") for key in delete_calls)
    finally:
        widget.close()
        widget.deleteLater()
        qapp.processEvents()


def test_delete_photo_terminal_not_found_clears_pending_key(
    monkeypatch: pytest.MonkeyPatch,
    qapp: QApplication,
) -> None:
    from app.widgets.offer_photos_widget import OfferPhotosWidget

    list_calls: list[int] = []

    def fake_list_offer_photos(offer_id: int) -> list[dict[str, object]]:
        list_calls.append(int(offer_id))
        return []

    monkeypatch.setattr("app.widgets.offer_photos_widget.get_offline_mode", lambda: False)
    monkeypatch.setattr(
        "app.widgets.offer_photos_widget.offer_photo_service.list_offer_photos",
        fake_list_offer_photos,
    )
    monkeypatch.setattr(
        "app.widgets.offer_photos_widget.offer_photo_service.delete_offer_photo",
        lambda _photo_id, *, idempotency_key: False,
    )

    widget = OfferPhotosWidget(offer_id=123, offer_number=1)
    try:
        assert list_calls == [123]
        widget._delete_photo(42)
        assert 42 not in widget._pending_delete_keys
        assert list_calls == [123, 123]
        status = widget.findChild(QLabel, "offerPhotosStatus_123")
        assert status is not None
        assert status.text() == "No property photos yet."
    finally:
        widget.close()
        widget.deleteLater()
        qapp.processEvents()


def test_delete_photo_api_error_keeps_pending_key_and_shows_retryable_failure(
    monkeypatch: pytest.MonkeyPatch,
    qapp: QApplication,
) -> None:
    from app.services.api_client import ApiError
    from app.widgets.offer_photos_widget import OfferPhotosWidget

    delete_calls: list[str] = []

    monkeypatch.setattr("app.widgets.offer_photos_widget.get_offline_mode", lambda: False)
    monkeypatch.setattr(
        "app.widgets.offer_photos_widget.offer_photo_service.list_offer_photos",
        lambda _offer_id: [],
    )

    def fake_delete(_photo_id: int, *, idempotency_key: str) -> bool:
        delete_calls.append(str(idempotency_key))
        raise ApiError(500, "server failed")

    monkeypatch.setattr(
        "app.widgets.offer_photos_widget.offer_photo_service.delete_offer_photo",
        fake_delete,
    )

    widget = OfferPhotosWidget(offer_id=123, offer_number=1)
    try:
        widget._delete_photo(42)
        assert len(delete_calls) == 1
        assert widget._pending_delete_keys[42] == delete_calls[0]
        status = widget.findChild(QLabel, "offerPhotosStatus_123")
        assert status is not None
        assert status.text() == "Property photo could not be removed. Try again."
    finally:
        widget.close()
        widget.deleteLater()
        qapp.processEvents()


def test_offer_photo_delete_service_requires_idempotency_key() -> None:
    from app.services.offer_photos import delete_offer_photo

    with pytest.raises(ValueError, match="idempotency_key is required"):
        delete_offer_photo(42, idempotency_key="")


def test_offer_photo_delete_service_returns_true_for_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.offer_photos as service

    calls: list[tuple[str, dict[str, str]]] = []

    def fake_api_delete(path: str, *, headers: dict[str, str]) -> object:
        calls.append((path, dict(headers)))
        return None

    monkeypatch.setattr(service, "api_delete", fake_api_delete)

    assert service.delete_offer_photo(42, idempotency_key="delete-key") is True
    assert calls == [
        ("/offers/photos/42", {"Idempotency-Key": "delete-key"}),
    ]


def test_offer_photo_delete_service_honors_deleted_false_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.offer_photos as service

    monkeypatch.setattr(
        service,
        "api_delete",
        lambda _path, *, headers: {"deleted": False},
    )

    assert service.delete_offer_photo(42, idempotency_key="delete-key") is False


def test_offer_photo_delete_service_treats_404_as_terminal_absence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.offer_photos as service

    def fake_api_delete(_path: str, *, headers: dict[str, str]) -> object:
        raise service.ApiError(404, "Not found")

    monkeypatch.setattr(service, "api_delete", fake_api_delete)

    assert service.delete_offer_photo(42, idempotency_key="delete-key") is False


def test_offer_photo_delete_service_reraises_non_404_api_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.offer_photos as service

    def fake_api_delete(_path: str, *, headers: dict[str, str]) -> object:
        raise service.ApiError(500, "server failed")

    monkeypatch.setattr(service, "api_delete", fake_api_delete)

    with pytest.raises(service.ApiError) as exc_info:
        service.delete_offer_photo(42, idempotency_key="delete-key")
    assert exc_info.value.status_code == 500


def test_offer_photo_delete_service_does_not_generate_idempotency_key() -> None:
    import app.services.offer_photos as service

    source = inspect.getsource(service.delete_offer_photo)
    assert "uuid.uuid4" not in source
    assert "idempotency_key" in source


def test_context_change_during_upload_ignores_stale_completion(
    monkeypatch: pytest.MonkeyPatch,
    qapp: QApplication,
    tmp_path: Path,
) -> None:
    from app.widgets.offer_photos_widget import OfferPhotosWidget

    list_calls: list[int] = []

    def fake_list_offer_photos(offer_id: int) -> list[dict[str, object]]:
        list_calls.append(int(offer_id))
        return []

    monkeypatch.setattr("app.widgets.offer_photos_widget.get_offline_mode", lambda: False)
    monkeypatch.setattr(
        "app.widgets.offer_photos_widget.offer_photo_service.list_offer_photos",
        fake_list_offer_photos,
    )
    _install_fake_upload(monkeypatch, tmp_path)

    widget = OfferPhotosWidget(offer_id=123, offer_number=1)
    try:
        widget._choose_photo()
        stale_worker = _FakeUploadWorker.instances[-1]
        widget.set_offer_context(offer_id=456, offer_number=1)
        stale_worker.complete()
        qapp.processEvents()
        assert list_calls[-1] == 456
        status = widget.findChild(QLabel, "offerPhotosStatus_456")
        assert status is not None
        assert status.text() == "No property photos yet."
    finally:
        widget.close()
        widget.deleteLater()
        qapp.processEvents()


def test_destroy_during_upload_detaches_worker_without_parenting_to_widget(
    monkeypatch: pytest.MonkeyPatch,
    qapp: QApplication,
    tmp_path: Path,
) -> None:
    from app.widgets.offer_photos_widget import OfferPhotosWidget

    monkeypatch.setattr("app.widgets.offer_photos_widget.get_offline_mode", lambda: False)
    monkeypatch.setattr(
        "app.widgets.offer_photos_widget.offer_photo_service.list_offer_photos",
        lambda _offer_id: [],
    )
    _install_fake_upload(monkeypatch, tmp_path)

    widget = OfferPhotosWidget(offer_id=123, offer_number=1)
    widget._choose_photo()
    worker = _FakeUploadWorker.instances[-1]
    assert worker.parent() is None
    assert worker.started
    widget.close()
    widget.deleteLater()
    qapp.processEvents()
    worker.complete()
    qapp.processEvents()
    assert worker.deleted_later
