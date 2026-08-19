"""Offer photo management widget for persisted property offers."""

from __future__ import annotations

import uuid

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtGui import QCloseEvent, QPixmap
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.services import offer_photos as offer_photo_service
from app.services.offline_state import get_offline_mode
from app.utils.i18n import tr_factory
from app.widgets.collapsible_section import CollapsibleSection
from core.contracts.offer_photo_media import OFFER_PHOTO_FILE_DIALOG_FILTER

_TR = tr_factory("OfferPhotosWidget")
_MAX_THUMBNAIL_BYTES = 2 * 1024 * 1024
_BACKGROUND_WORKERS: set[QObject] = set()


def _track_worker(worker: QObject) -> None:
    _BACKGROUND_WORKERS.add(worker)
    finished = getattr(worker, "finished", None)
    if finished is not None:
        finished.connect(lambda tracked=worker: _BACKGROUND_WORKERS.discard(tracked))
        finished.connect(worker.deleteLater)


def _disconnect_all(signal: object) -> None:
    disconnect = getattr(signal, "disconnect", None)
    if not callable(disconnect):
        return
    try:
        disconnect()
    except (RuntimeError, TypeError):
        pass


class _UploadWorker(QThread):
    uploaded = Signal(int)
    failed = Signal(str)

    def __init__(self, *, offer_id: int, source_path: str) -> None:
        super().__init__(None)
        self._offer_id = int(offer_id)
        self._source_path = str(source_path)

    def run(self) -> None:
        try:
            photo_id = offer_photo_service.upload_offer_photo(
                self._offer_id,
                self._source_path,
            )
        except (OSError, RuntimeError, ValueError, offer_photo_service.ApiError) as exc:
            self.failed.emit(_safe_photo_error(exc))
            return
        try:
            self.uploaded.emit(int(photo_id))
        except (TypeError, ValueError):
            self.failed.emit(_TR("Property photo upload did not return a photo id."))


class _ThumbnailWorker(QThread):
    loaded = Signal(int, int, int, int, object)
    failed = Signal(int, int, int, int)

    def __init__(
        self,
        *,
        offer_id: int,
        context_generation: int,
        thumbnail_generation: int,
        jobs: list[tuple[int, str]],
    ) -> None:
        super().__init__(None)
        self._offer_id = int(offer_id)
        self._context_generation = int(context_generation)
        self._thumbnail_generation = int(thumbnail_generation)
        self._jobs = list(jobs)
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        for photo_id, storage_id in self._jobs:
            if self._cancelled:
                return
            try:
                data = offer_photo_service.download_offer_photo_thumbnail_bytes(
                    storage_id,
                    max_bytes=_MAX_THUMBNAIL_BYTES,
                )
            except (OSError, RuntimeError, ValueError, offer_photo_service.ApiError):
                self.failed.emit(
                    self._offer_id,
                    self._context_generation,
                    self._thumbnail_generation,
                    photo_id,
                )
                continue
            if self._cancelled:
                return
            if data:
                self.loaded.emit(
                    self._offer_id,
                    self._context_generation,
                    self._thumbnail_generation,
                    photo_id,
                    data,
                )
            else:
                self.failed.emit(
                    self._offer_id,
                    self._context_generation,
                    self._thumbnail_generation,
                    photo_id,
                )


def _safe_photo_error(exc: Exception) -> str:
    if isinstance(exc, FileNotFoundError):
        return _TR("Property photo file was not found.")
    if isinstance(exc, ValueError):
        message = str(exc).strip()
        return message or _TR("Property photo could not be uploaded.")
    if isinstance(exc, offer_photo_service.ApiError):
        return _TR("Property photo upload was rejected. Check the file type and try again.")
    return _TR("Property photo upload failed. Check your connection and try again.")


class OfferPhotosWidget(QWidget):
    """Manage photos for a persisted offer."""

    def __init__(
        self,
        *,
        offer_id: int = 0,
        offer_number: int = 1,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._offer_id = int(offer_id)
        self._offer_number = int(offer_number)
        self._upload_worker: QObject | None = None
        self._thumbnail_worker: _ThumbnailWorker | None = None
        self._pending_delete_keys: dict[int, str] = {}
        self._alive = True
        self._context_generation = 0
        self._thumbnail_generation = 0
        self.destroyed.connect(lambda *_args: self._mark_destroyed())
        self._setup_ui()
        self.set_offer_context(offer_id=self._offer_id, offer_number=self._offer_number)

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self._section = CollapsibleSection(
            _TR("Property Photos"),
            self,
            show_delete=False,
            collapsible=True,
        )
        self._section.setAccessibleName(_TR("Property photos"))

        content = QWidget(self._section)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(6)

        toolbar = QWidget(content)
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(0, 0, 0, 0)
        toolbar_layout.setSpacing(8)

        self._add_button = QPushButton(_TR("Add Photo"), toolbar)
        self._add_button.setAccessibleName(_TR("Add property photo"))
        self._add_button.setProperty("immoVariant", "secondary")
        self._add_button.clicked.connect(self._choose_photo)

        self._status = QLabel("", toolbar)
        self._status.setWordWrap(True)
        self._status.setProperty("immoMuted", True)

        toolbar_layout.addWidget(self._add_button)
        toolbar_layout.addWidget(self._status, 1)

        self._list = QWidget(content)
        self._list_layout = QVBoxLayout(self._list)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(6)

        content_layout.addWidget(toolbar)
        content_layout.addWidget(self._list)
        self._section.set_content(content)
        layout.addWidget(self._section)

    def _automation_suffix(self) -> str:
        if self._offer_id > 0:
            return str(self._offer_id)
        return f"unsaved_{self._offer_number}"

    def set_offer_context(self, *, offer_id: int, offer_number: int) -> None:
        self._context_generation += 1
        self._detach_upload_worker()
        self._cancel_thumbnail_worker()
        self._pending_delete_keys.clear()
        self._offer_id = int(offer_id)
        self._offer_number = int(offer_number)
        suffix = self._automation_suffix()
        self._section.setObjectName(f"offerPhotosSection_{suffix}")
        self._section.setAccessibleName("offerPhotosSection")
        self._add_button.setObjectName(f"offerPhotosAddButton_{suffix}")
        self._list.setObjectName(f"offerPhotosList_{suffix}")
        self._status.setObjectName(f"offerPhotosStatus_{suffix}")
        self.refresh_photos()

    def refresh_photos(self) -> None:
        self._thumbnail_generation += 1
        self._cancel_thumbnail_worker()
        self._clear_list()
        if self._offer_id <= 0:
            self._add_button.setEnabled(False)
            self._set_status(_TR("Save this offer before adding property photos."))
            self._add_empty_state("unsaved")
            return
        if get_offline_mode():
            self._add_button.setEnabled(False)
            self._set_status(_TR("Property photo upload is unavailable while offline."))
            self._add_empty_state(str(self._offer_id))
            return

        self._add_button.setEnabled(self._upload_worker is None)
        try:
            photos = offer_photo_service.list_offer_photos(self._offer_id)
        except (RuntimeError, ValueError, offer_photo_service.ApiError):
            self._set_status(_TR("Unable to load property photos. Try again later."))
            self._add_empty_state(str(self._offer_id))
            return
        if not photos:
            self._set_status(_TR("No property photos yet."))
            self._add_empty_state(str(self._offer_id))
            return
        self._set_status(_TR("{count} property photo(s).").format(count=len(photos)))
        thumbnail_jobs: list[tuple[int, str]] = []
        for photo in photos:
            job = self._add_photo_row(photo)
            if job is not None:
                thumbnail_jobs.append(job)
        if thumbnail_jobs:
            self._start_thumbnail_worker(thumbnail_jobs)

    def _choose_photo(self) -> None:
        if self._upload_worker is not None:
            return
        if self._offer_id <= 0:
            self._set_status(_TR("Save this offer before adding property photos."))
            return
        if get_offline_mode():
            self._set_status(_TR("Property photo upload is unavailable while offline."))
            return
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            _TR("Select Property Photo"),
            "",
            _TR(OFFER_PHOTO_FILE_DIALOG_FILTER),
        )
        if not file_path:
            return
        try:
            offer_photo_service.validate_offer_photo_path(file_path)
        except (OSError, ValueError) as exc:
            self._set_status(_safe_photo_error(exc), error=True)
            return
        self._set_status(_TR("Uploading property photo..."))
        self._add_button.setEnabled(False)
        worker = _UploadWorker(offer_id=self._offer_id, source_path=file_path)
        self._upload_worker = worker
        context_generation = self._context_generation
        offer_id = self._offer_id
        worker.uploaded.connect(
            lambda photo_id, generation=context_generation, oid=offer_id, w=worker: (
                self._on_photo_uploaded(photo_id, generation, oid, w)
            )
        )
        worker.failed.connect(
            lambda message, generation=context_generation, oid=offer_id, w=worker: (
                self._on_upload_failed(message, generation, oid, w)
            )
        )
        _track_worker(worker)
        worker.start()

    def _on_photo_uploaded(
        self,
        _photo_id: int,
        context_generation: int,
        offer_id: int,
        worker: QObject,
    ) -> None:
        if not self._accept_upload_result(context_generation, offer_id, worker):
            return
        self._upload_worker = None
        self._set_status(_TR("Property photo uploaded."))
        self.refresh_photos()

    def _on_upload_failed(
        self,
        message: str,
        context_generation: int,
        offer_id: int,
        worker: QObject,
    ) -> None:
        if not self._accept_upload_result(context_generation, offer_id, worker):
            return
        self._upload_worker = None
        self._add_button.setEnabled(True)
        self._set_status(message, error=True)

    def _delete_photo(self, photo_id: int) -> None:
        resolved_photo_id = int(photo_id)
        idempotency_key = self._pending_delete_keys.get(resolved_photo_id)
        if not idempotency_key:
            idempotency_key = f"offer-photo-delete:{resolved_photo_id}:{uuid.uuid4().hex}"
            self._pending_delete_keys[resolved_photo_id] = idempotency_key
        try:
            deleted = offer_photo_service.delete_offer_photo(
                resolved_photo_id,
                idempotency_key=idempotency_key,
            )
        except (RuntimeError, offer_photo_service.ApiError):
            self._set_status(_TR("Property photo could not be removed. Try again."), error=True)
            return
        self._pending_delete_keys.pop(resolved_photo_id, None)
        if not deleted:
            self._set_status(_TR("Property photo was already removed."), error=True)
        else:
            self._set_status(_TR("Property photo removed."))
        self.refresh_photos()

    def _clear_list(self) -> None:
        while self._list_layout.count():
            item = self._list_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _add_empty_state(self, suffix: str) -> None:
        empty = QLabel(_TR("No active property photos."), self._list)
        empty.setObjectName(f"offerPhotosEmpty_{suffix}")
        empty.setAccessibleName(_TR("No active property photos"))
        empty.setProperty("immoEmptyState", True)
        self._list_layout.addWidget(empty)

    def _add_photo_row(self, photo: dict[str, object]) -> tuple[int, str] | None:
        photo_id = _coerce_int(photo.get("id"))
        storage_id = str(photo.get("storage_id") or "")
        row = QFrame(self._list)
        row.setObjectName(f"offerPhotoItem_{photo_id}")
        row.setAccessibleName(_TR("Property photo {id}").format(id=photo_id))
        row.setFrameShape(QFrame.Shape.StyledPanel)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(6, 6, 6, 6)
        row_layout.setSpacing(8)

        preview = QLabel(_TR("Photo"), row)
        preview.setObjectName(f"offerPhotoThumbnail_{photo_id}")
        preview.setAccessibleName(_TR("Property photo thumbnail loading"))
        preview.setProperty("photo_id", photo_id)
        preview.setProperty("storage_id", storage_id)
        preview.setProperty("photoThumbnailLoaded", False)
        preview.setProperty("photoThumbnailState", "loading")
        preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        preview.setFixedSize(72, 56)
        row_layout.addWidget(preview)

        info = QLabel(_TR("Photo #{id}").format(id=photo_id), row)
        info.setAccessibleName(_TR("Property photo label"))
        row_layout.addWidget(info, 1)

        delete_button = QPushButton(_TR("Remove"), row)
        delete_button.setObjectName(f"offerPhotoDeleteButton_{photo_id}")
        delete_button.setAccessibleName(_TR("Remove property photo"))
        delete_button.setProperty("immoVariant", "danger")
        delete_button.clicked.connect(lambda _checked=False, pid=photo_id: self._delete_photo(pid))
        row_layout.addWidget(delete_button)

        self._list_layout.addWidget(row)
        if not storage_id:
            return None
        return photo_id, storage_id

    def _start_thumbnail_worker(self, jobs: list[tuple[int, str]]) -> None:
        self._cancel_thumbnail_worker()
        worker = _ThumbnailWorker(
            offer_id=self._offer_id,
            context_generation=self._context_generation,
            thumbnail_generation=self._thumbnail_generation,
            jobs=jobs,
        )
        self._thumbnail_worker = worker
        worker.loaded.connect(self._on_thumbnail_loaded)
        worker.failed.connect(self._on_thumbnail_failed)
        _track_worker(worker)
        worker.start()

    def _on_thumbnail_loaded(
        self,
        offer_id: int,
        context_generation: int,
        thumbnail_generation: int,
        photo_id: int,
        data: object,
    ) -> None:
        if not self._accept_thumbnail_result(
            offer_id,
            context_generation,
            thumbnail_generation,
        ):
            return
        preview = self.findChild(QLabel, f"offerPhotoThumbnail_{photo_id}")
        if preview is None:
            return
        if not isinstance(data, bytes):
            self._mark_thumbnail_failed(preview)
            return
        pixmap = QPixmap()
        if not pixmap.loadFromData(data):
            self._mark_thumbnail_failed(preview)
            return
        preview.setPixmap(
            pixmap.scaled(
                72,
                56,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        preview.setAccessibleName(_TR("Property photo thumbnail loaded"))
        preview.setProperty("photoThumbnailLoaded", True)
        preview.setProperty("photoThumbnailState", "loaded")
        preview.style().unpolish(preview)
        preview.style().polish(preview)

    def _on_thumbnail_failed(
        self,
        offer_id: int,
        context_generation: int,
        thumbnail_generation: int,
        _photo_id: int,
    ) -> None:
        if not self._accept_thumbnail_result(
            offer_id,
            context_generation,
            thumbnail_generation,
        ):
            return
        preview = self.findChild(QLabel, f"offerPhotoThumbnail_{_photo_id}")
        if preview is None:
            return
        self._mark_thumbnail_failed(preview)

    def _mark_thumbnail_failed(self, preview: QLabel) -> None:
        preview.setText(_TR("Preview unavailable"))
        preview.setAccessibleName(_TR("Property photo thumbnail unavailable"))
        preview.setProperty("photoThumbnailLoaded", False)
        preview.setProperty("photoThumbnailState", "failed")
        preview.style().unpolish(preview)
        preview.style().polish(preview)

    def _accept_upload_result(
        self,
        context_generation: int,
        offer_id: int,
        worker: QObject,
    ) -> bool:
        return (
            self._alive
            and self._upload_worker is worker
            and self._context_generation == context_generation
            and self._offer_id == offer_id
        )

    def _accept_thumbnail_result(
        self,
        offer_id: int,
        context_generation: int,
        thumbnail_generation: int,
    ) -> bool:
        return (
            self._alive
            and self._offer_id == offer_id
            and self._context_generation == context_generation
            and self._thumbnail_generation == thumbnail_generation
        )

    def _detach_upload_worker(self) -> None:
        worker = self._upload_worker
        self._upload_worker = None
        if worker is None:
            return
        _disconnect_all(getattr(worker, "uploaded", None))
        _disconnect_all(getattr(worker, "failed", None))

    def _cancel_thumbnail_worker(self) -> None:
        worker = self._thumbnail_worker
        self._thumbnail_worker = None
        if worker is None:
            return
        worker.cancel()
        _disconnect_all(getattr(worker, "loaded", None))
        _disconnect_all(getattr(worker, "failed", None))

    def _mark_destroyed(self) -> None:
        self._alive = False
        self._detach_upload_worker()
        self._cancel_thumbnail_worker()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        self._mark_destroyed()
        super().closeEvent(event)

    def _set_status(self, text: str, *, error: bool = False) -> None:
        if not self._alive:
            return
        self._status.setText(text)
        self._status.setProperty("immoState", "error" if error else "normal")
        self._status.style().unpolish(self._status)
        self._status.style().polish(self._status)


def _coerce_int(value: object) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return 0


__all__ = ["OfferPhotosWidget"]
