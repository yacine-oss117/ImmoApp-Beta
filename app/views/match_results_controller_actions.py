"""
Action handlers for match result interactions (phone, map, actions buttons).
"""

from __future__ import annotations

from collections.abc import Callable
from functools import partial

from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtGui import QPixmap

from app.models import Offer
from app.services import offer_photos as offer_photo_service
from app.utils.geo import map_link_to_url
from app.utils.i18n import tr_factory
from app.views.base import (
    QDesktopServices,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    Qt,
    QUrl,
    QVBoxLayout,
    QWidget,
)
from app.views.match_actions import create_contract_action, generate_pdf_contract, schedule_visit
from app.views.match_phone_menu import show_phone_menu
from app.widgets.user_feedback import UserFacingMessage

_TR = tr_factory("MatchResultsControllerActions")
_MATCH_THUMBNAIL_BYTES = 2 * 1024 * 1024
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


class _MatchPhotoThumbnailWorker(QThread):
    loaded = Signal(int, int, object)
    failed = Signal(int, int)

    def __init__(self, *, offer_id: int, jobs: list[tuple[int, str]]) -> None:
        super().__init__(None)
        self._offer_id = int(offer_id)
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
                    max_bytes=_MATCH_THUMBNAIL_BYTES,
                )
            except (OSError, RuntimeError, ValueError, offer_photo_service.ApiError):
                self.failed.emit(self._offer_id, photo_id)
                continue
            if self._cancelled:
                return
            if data:
                self.loaded.emit(self._offer_id, photo_id, data)
            else:
                self.failed.emit(self._offer_id, photo_id)


def _photo_id_from_payload(payload: dict[str, object]) -> int:
    raw_photo_id = payload.get("id")
    try:
        if not isinstance(raw_photo_id, (str, int, float)):
            return 0
        return int(raw_photo_id or 0)
    except (TypeError, ValueError):
        return 0


def _thumbnail_label(parent: QWidget, *, photo_id: int, storage_id: str) -> QLabel:
    preview = QLabel(_TR("Loading preview"), parent)
    preview.setObjectName(f"matchOfferPhotoThumbnail_{int(photo_id)}")
    preview.setAccessibleName(_TR("Matched offer photo thumbnail loading"))
    preview.setProperty("photo_id", int(photo_id))
    preview.setProperty("storage_id", storage_id)
    preview.setProperty("photoThumbnailLoaded", False)
    preview.setProperty("photoThumbnailState", "loading")
    preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
    preview.setFixedSize(96, 72)
    return preview


def _mark_thumbnail_loaded(preview: QLabel, data: bytes) -> bool:
    pixmap = QPixmap()
    if not pixmap.loadFromData(data):
        return False
    preview.setPixmap(
        pixmap.scaled(
            96,
            72,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
    )
    preview.setAccessibleName(_TR("Matched offer photo thumbnail loaded"))
    preview.setProperty("photoThumbnailLoaded", True)
    preview.setProperty("photoThumbnailState", "loaded")
    preview.style().unpolish(preview)
    preview.style().polish(preview)
    return True


def _mark_thumbnail_failed(preview: QLabel) -> None:
    preview.setText(_TR("Preview unavailable"))
    preview.setAccessibleName(_TR("Matched offer photo thumbnail unavailable"))
    preview.setProperty("photoThumbnailLoaded", False)
    preview.setProperty("photoThumbnailState", "failed")
    preview.style().unpolish(preview)
    preview.style().polish(preview)


class MatchResultsActionHandlers:
    """Encapsulates action handlers used by the match results UI."""

    def __init__(
        self,
        *,
        parent: QWidget,
        sender_provider: Callable[[], QObject | None],
        get_selected_client_id: Callable[[], int | None],
        refresh_crm_cb: Callable[[], None] | None,
        feedback_cb: Callable[[UserFacingMessage, int | None], None] | None,
    ) -> None:
        self._parent = parent
        self._sender_provider = sender_provider
        self._get_selected_client_id = get_selected_client_id
        self._refresh_crm_cb = refresh_crm_cb
        self._feedback_cb = feedback_cb

    def on_phone_click(self) -> None:
        """Handle phone button clicks from the match results UI."""
        sender = self._sender_provider()
        if sender is None:
            return

        phone_obj = sender.property("phone")
        if not isinstance(phone_obj, str) or not phone_obj:
            return

        owner_obj = sender.property("owner_name")
        owner_name = owner_obj if isinstance(owner_obj, str) and owner_obj else _TR("Client")
        show_phone_menu(self._parent, phone_obj, owner_name)

    def on_position_click(self) -> None:
        """Handle map position clicks from the match results UI."""
        sender = self._sender_provider()
        if sender is None:
            return
        link_obj = sender.property("link")
        link = link_obj if isinstance(link_obj, str) else ""
        lat_obj = sender.property("latitude")
        lon_obj = sender.property("longitude")

        def _coerce_coord(value: object) -> float | None:
            if isinstance(value, (int, float)):
                return float(value)
            if isinstance(value, str):
                try:
                    return float(value)
                except ValueError:
                    return None
            return None

        url = map_link_to_url(
            link,
            latitude=_coerce_coord(lat_obj),
            longitude=_coerce_coord(lon_obj),
        )
        if url:
            QDesktopServices.openUrl(QUrl(url))

    def _build_offer_photos_dialog(self, *, offer_id: int, owner_name: str) -> QDialog:
        dialog = QDialog(self._parent)
        resolved_offer_id = int(offer_id)
        dialog.setObjectName(f"matchOfferPhotosDialog_offer_{resolved_offer_id}")
        dialog.setAccessibleName(_TR("Matched offer photos"))
        dialog.setWindowTitle(_TR("Property photos"))
        dialog.setProperty("offer_id", resolved_offer_id)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)

        heading = QLabel(owner_name or _TR("Matched offer"), dialog)
        heading.setObjectName(f"matchOfferPhotosDialogTitle_offer_{resolved_offer_id}")
        layout.addWidget(heading)

        try:
            photos = offer_photo_service.list_offer_photos(resolved_offer_id)
        except (RuntimeError, ValueError, offer_photo_service.ApiError):
            photos = []

        thumbnail_jobs: list[tuple[int, str]] = []
        if photos:
            for raw_photo in photos:
                if not isinstance(raw_photo, dict):
                    continue
                photo_id = _photo_id_from_payload(raw_photo)
                if photo_id <= 0:
                    continue
                storage_id = str(raw_photo.get("storage_id") or "")
                row = QFrame(dialog)
                row.setObjectName(f"matchOfferPhotoItem_{photo_id}")
                row.setAccessibleName(_TR("Matched offer photo"))
                row.setProperty("offer_id", int(offer_id))
                row.setProperty("photo_id", photo_id)
                row_layout = QHBoxLayout(row)
                row_layout.setContentsMargins(6, 6, 6, 6)
                row_layout.setSpacing(8)

                preview = _thumbnail_label(row, photo_id=photo_id, storage_id=storage_id)
                row_layout.addWidget(preview)

                label = QLabel(_TR("Photo #{id}").format(id=photo_id), row)
                label.setAccessibleName(_TR("Matched offer photo label"))
                row_layout.addWidget(label, 1)
                layout.addWidget(row)
                if storage_id:
                    thumbnail_jobs.append((photo_id, storage_id))
        else:
            empty = QLabel(_TR("No active property photos."), dialog)
            empty.setObjectName(f"matchOfferPhotosEmpty_offer_{resolved_offer_id}")
            layout.addWidget(empty)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, dialog)
        close_button = buttons.button(QDialogButtonBox.StandardButton.Close)
        if close_button is not None:
            close_button.setObjectName("matchOfferPhotosDialogCloseButton")
            close_button.setAccessibleName(_TR("Close property photos"))
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if thumbnail_jobs:
            alive = {"value": True}
            worker = _MatchPhotoThumbnailWorker(offer_id=resolved_offer_id, jobs=thumbnail_jobs)

            def _cancel_worker(*_args: object) -> None:
                alive["value"] = False
                worker.cancel()
                _disconnect_all(worker.loaded)
                _disconnect_all(worker.failed)

            def _apply_loaded(worker_offer_id: int, photo_id: int, data: object) -> None:
                if not alive["value"] or worker_offer_id != resolved_offer_id:
                    return
                preview = dialog.findChild(QLabel, f"matchOfferPhotoThumbnail_{int(photo_id)}")
                if preview is None:
                    return
                if not isinstance(data, bytes) or not _mark_thumbnail_loaded(preview, data):
                    _mark_thumbnail_failed(preview)

            def _apply_failed(worker_offer_id: int, photo_id: int) -> None:
                if not alive["value"] or worker_offer_id != resolved_offer_id:
                    return
                preview = dialog.findChild(QLabel, f"matchOfferPhotoThumbnail_{int(photo_id)}")
                if preview is not None:
                    _mark_thumbnail_failed(preview)

            dialog.finished.connect(_cancel_worker)
            dialog.destroyed.connect(_cancel_worker)
            worker.loaded.connect(_apply_loaded)
            worker.failed.connect(_apply_failed)
            _track_worker(worker)
            worker.start()
        return dialog

    def _show_offer_photos(self, *, offer_id: int, owner_name: str) -> None:
        dialog = self._build_offer_photos_dialog(offer_id=offer_id, owner_name=owner_name)
        dialog.exec()

    def create_action_buttons(
        self, listing_id: int, offer: Offer, parent: QWidget | None = None
    ) -> QWidget:
        """Create Visit, persisted Contract, and PDF buttons matching Listing tab style."""
        container = QWidget(parent or self._parent)
        offer_id = int(getattr(offer, "id", 0) or 0)
        container.setAutoFillBackground(False)
        container.setObjectName(f"matchActionsContainer_listing_{listing_id}_offer_{offer_id}")
        container.setProperty("matchActionsContainer", True)
        layout = QHBoxLayout(container)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.setSpacing(8)

        client_id = self._get_selected_client_id()

        def make_btn(
            text: str,
            tooltip: str,
            variant: str,
            action_key: str,
        ) -> QPushButton:
            btn = QPushButton(text)
            btn.setToolTip(tooltip)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setMinimumWidth(60)
            btn.setFixedHeight(28)
            btn.setProperty("immoVariant", variant)
            btn.setProperty("matchAction", action_key)
            btn.setObjectName(
                f"match{action_key.title().replace('_', '')}Button"
                f"_listing_{listing_id}_offer_{offer_id}"
            )
            return btn

        visit_btn = make_btn(
            _TR("Visite"),
            _TR("Planifier une visite"),
            "secondary",
            "visit",
        )
        create_contract_btn = make_btn(
            _TR("Créer"),
            _TR("Creer un contrat dans le CRM"),
            "success",
            "create_contract",
        )
        pdf_btn = make_btn(
            _TR("PDF"),
            _TR("Generer le contrat PDF"),
            "ghost",
            "generate_contract_pdf",
        )
        photos_btn = make_btn(
            _TR("Photos"),
            _TR("Voir les photos du bien"),
            "ghost",
            "offer_photos",
        )
        visit_btn.setAccessibleName(_TR("Schedule visit"))
        create_contract_btn.setAccessibleName(_TR("Create contract"))
        pdf_btn.setAccessibleName(_TR("Generate contract PDF"))
        photos_btn.setAccessibleName(_TR("View property photos"))

        if client_id is None:
            visit_btn.setEnabled(False)
            create_contract_btn.setEnabled(False)
            pdf_btn.setEnabled(False)
            photos_btn.setEnabled(False)
            visit_btn.setToolTip(_TR("Client ID missing"))
            create_contract_btn.setToolTip(_TR("Client ID missing"))
            pdf_btn.setToolTip(_TR("Client ID missing"))
            photos_btn.setToolTip(_TR("Client ID missing"))
        else:
            visit_btn.clicked.connect(
                partial(
                    schedule_visit,
                    parent=self._parent,
                    client_id=client_id,
                    listing_id=listing_id,
                    location=offer.location,
                    refresh_crm_cb=self._refresh_crm_cb,
                    feedback_cb=self._feedback_cb,
                )
            )
            create_contract_btn.clicked.connect(
                partial(
                    create_contract_action,
                    parent=self._parent,
                    client_id=client_id,
                    listing_id=listing_id,
                    action=offer.action,
                    refresh_crm_cb=self._refresh_crm_cb,
                    feedback_cb=self._feedback_cb,
                )
            )
            pdf_btn.clicked.connect(
                partial(
                    generate_pdf_contract,
                    parent=self._parent,
                    client_id=client_id,
                    listing_id=listing_id,
                    offer=offer,
                    refresh_crm_cb=self._refresh_crm_cb,
                    feedback_cb=self._feedback_cb,
                )
            )
            photos_btn.clicked.connect(
                partial(
                    self._show_offer_photos,
                    offer_id=offer_id,
                    owner_name=str(getattr(offer, "location", "") or ""),
                )
            )

        layout.addWidget(visit_btn)
        layout.addWidget(create_contract_btn)
        layout.addWidget(pdf_btn)
        layout.addWidget(photos_btn)
        layout.addStretch()

        return container
