import logging
import os
from urllib.parse import urlparse

from PySide6.QtCore import Qt, QThread, QUrl, Signal
from PySide6.QtCore import Signal as QSignal
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.services.api_client_errors import ApiError
from app.services.local_service_urls import rewrite_local_service_url
from app.utils.i18n import tr_factory
from app.views.imports.import_experience import ImportReviewPaneState
from app.views.imports.mapping_palette import derive_mapping_palette_state
from app.views.imports.wizard_state import ImportWizardController

logger = logging.getLogger(__name__)
_TR = tr_factory("ImportWizardStepUpload")
_DEFAULT_UPLOAD_POLL_SECONDS = 0.15
_MAX_PARSE_WAIT_SECONDS = 300.0
_VALID_UPLOAD_EXTENSIONS = {".xlsx", ".csv", ".tsv", ".txt", ".ods"}
_IMPORT_BOOTSTRAP_TIMEOUT_SECONDS = 30.0
_LOCAL_TLS_RETRY_DELAY_SECONDS = 1.5


def _iter_exception_chain(exc: BaseException) -> list[BaseException]:
    chain: list[BaseException] = []
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        chain.append(current)
        seen.add(id(current))
        next_exc = current.__cause__ or current.__context__
        current = next_exc if isinstance(next_exc, BaseException) else None
    return chain


def _is_local_secure_import_base_url() -> bool:
    from app.services.api_config import get_api_base_url

    base_url = str(get_api_base_url() or "").strip()
    if not base_url:
        return False
    parsed = urlparse(base_url)
    return parsed.scheme == "https" and parsed.hostname in {"localhost", "127.0.0.1"}


def _is_connection_refused_error(exc: BaseException) -> bool:
    for candidate in _iter_exception_chain(exc):
        text = str(candidate).lower()
        if isinstance(candidate, ConnectionRefusedError):
            return True
        if (
            "connection refused" in text
            or "failed to establish a new connection" in text
            or "winerror 10061" in text
        ):
            return True
    return False


def _is_tls_handshake_timeout(exc: BaseException) -> bool:
    for candidate in _iter_exception_chain(exc):
        text = str(candidate).lower()
        if "handshake operation timed out" in text or "_ssl.c:1063" in text:
            return True
    return False


def _is_request_timeout(exc: BaseException) -> bool:
    for candidate in _iter_exception_chain(exc):
        text = str(candidate).lower()
        if isinstance(candidate, TimeoutError):
            return True
        if "read timed out" in text or "timed out" in text:
            return True
    return False


def _friendly_upload_error_message(error: Exception | str) -> str:
    if isinstance(error, ApiError):
        if error.code == "IMPORT_ACCOUNT_SCOPE_REQUIRED":
            return _TR(
                "Your account is not ready for imports yet. Please contact the agency owner or support."
            )
        if error.code in {"IMPORT_SERVICE_WARMING_UP", "IMPORT_STORAGE_NOT_READY"}:
            return _TR(
                "The local import service is still starting up. Please try again in a moment."
            )
        if error.status_code >= 500:
            return _TR("The import service took too long to respond. Please try again in a moment.")
        return error.message or _TR(
            "We couldn’t read this file yet. Please try again or choose another file."
        )
    if isinstance(error, RuntimeError):
        cause = error.__cause__ if isinstance(error.__cause__, BaseException) else error
        if _is_connection_refused_error(cause):
            return _TR(
                "The local import service is not ready yet. Please wait a moment and try again."
            )
        if _is_tls_handshake_timeout(cause):
            return _TR(
                "The local secure import service is still starting up. Please try again in a moment."
            )
        if _is_request_timeout(cause):
            return _TR(
                "The local import service took too long to respond. Please try again in a moment."
            )
    return _TR("We couldn’t read this file yet. Please try again or choose another file.")


def _coerce_poll_after_seconds(value: object, fallback_seconds: float) -> float:
    if isinstance(value, bool):
        return max(0.05, min(float(int(value)) / 1000.0, 5.0))
    if isinstance(value, int):
        return max(0.05, min(float(value) / 1000.0, 5.0))
    if isinstance(value, float):
        return max(0.05, min(value / 1000.0, 5.0))
    if isinstance(value, str):
        try:
            parsed = int(value)
        except ValueError:
            return max(0.05, min(float(fallback_seconds), 5.0))
        return max(0.05, min(float(parsed) / 1000.0, 5.0))
    return max(0.05, min(float(fallback_seconds), 5.0))


class DragDropZone(QFrame):
    fileDropped = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("DropZone")
        self.setAcceptDrops(True)
        self.setMinimumHeight(220)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(14)

        # Icon
        self.icon_label = QLabel("↓")
        self.icon_label.setObjectName("DropIcon")
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Text
        self.text_label = QLabel(_TR("Choose your file\nor drag it here"))
        self.text_label.setObjectName("DropText")
        self.text_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Browse Button
        self.browse_btn = QPushButton(_TR("Choose file"))
        self.browse_btn.setObjectName("importUploadChooseFileButton")
        self.browse_btn.setProperty("immoVariant", "primary")
        self.browse_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.browse_btn.clicked.connect(self._browse)

        layout.addWidget(self.icon_label)
        layout.addWidget(self.text_label)
        layout.addWidget(self.browse_btn)

    def _browse(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            _TR("Select import file"),
            "",
            _TR("Excel Files (*.xlsx);;CSV Files (*.csv *.tsv *.txt);;ODS Files (*.ods)"),
        )
        if file_path:
            self.fileDropped.emit(file_path)

    @staticmethod
    def supported_drop_files(urls: list[QUrl]) -> list[str]:
        files: list[str] = []
        for url in urls:
            local_file = os.path.normpath(str(url.toLocalFile() or "").strip())
            if not local_file:
                continue
            ext = os.path.splitext(local_file)[1].lower()
            if ext in _VALID_UPLOAD_EXTENSIONS:
                files.append(local_file)
        return files

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        files = self.supported_drop_files(list(event.mimeData().urls() or []))
        if files:
            event.acceptProposedAction()
            return
        event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        files = self.supported_drop_files(list(event.mimeData().urls() or []))
        if files:
            event.acceptProposedAction()
            return
        event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        files = self.supported_drop_files(list(event.mimeData().urls() or []))
        if files:
            event.acceptProposedAction()
            self.fileDropped.emit(files[0])
            return
        event.ignore()


class UploadWorker(QThread):
    uploadFinished = QSignal(dict)
    error = QSignal(str)
    status = QSignal(str)

    def __init__(self, file_path: str, *, entity_hint: str | None = None) -> None:
        super().__init__()
        self.file_path = file_path
        self.entity_hint = entity_hint

    def run(self) -> None:
        import mimetypes
        import time

        from app.services.api_client import api_get, as_dict
        from app.services.api_client_errors import ApiError

        try:
            logger.debug("Import upload worker started for %s", self.file_path)
            filename = os.path.basename(self.file_path)
            size_bytes = os.path.getsize(self.file_path)
            content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"

            # 1. Presign
            presign = self._request_import_post(
                "import/presign",
                {
                    "filename": filename,
                    "content_type": content_type,
                    "size_bytes": size_bytes,
                },
                retry_status_text=_TR("The local import service is waking up..."),
            )
            url = rewrite_local_service_url(str(presign.get("url") or ""))
            fields = presign.get("fields")
            if not isinstance(fields, dict):
                fields = {}
            storage_id = str(presign.get("storage_id") or "")
            if not url or not fields or not storage_id:
                self.error.emit(
                    _TR("We couldn’t start the upload yet. Please try again in a moment.")
                )
                return

            # 2. Upload directly to storage
            self.status.emit(_TR("Uploading your file..."))
            _post_presigned_upload(url, fields, filename, self.file_path, content_type)

            # 3. Complete upload + queue parse
            complete_payload: dict[str, object] = {
                "storage_id": storage_id,
                "filename": filename,
            }
            if self.entity_hint:
                complete_payload["entity_type"] = self.entity_hint
            data = self._request_import_post(
                "import/complete",
                complete_payload,
                retry_status_text=_TR("We’re preparing the upload..."),
            )
            task_id = str(data.get("task_id", ""))
            poll_after_seconds = _coerce_poll_after_seconds(
                data.get("poll_after_ms"), _DEFAULT_UPLOAD_POLL_SECONDS
            )

            if not task_id:
                self.error.emit(_TR("Upload failed. Please try again."))
                return

            logger.debug("Import upload complete, polling task_id=%s", task_id)

            # 2. Poll for analysis result
            start_time = time.time()
            while time.time() - start_time < _MAX_PARSE_WAIT_SECONDS:
                self.status.emit(_TR("We’re checking the format..."))
                resp = api_get(f"import/status/{task_id}/")
                res_data = as_dict(resp)

                status = str(res_data.get("status", ""))
                if status == "ready":
                    logger.debug("Import parse ready for task_id=%s", task_id)
                    self.uploadFinished.emit(res_data)
                    return
                elif status == "failed":
                    err = res_data.get(
                        "error_message",
                        _TR(
                            "We couldn’t read this file yet. Please try again or choose another file."
                        ),
                    )
                    self.error.emit(str(err))
                    return

                poll_after_seconds = _coerce_poll_after_seconds(
                    res_data.get("poll_after_ms"), poll_after_seconds
                )
                self.status.emit(_TR("We’re preparing a quick summary..."))
                time.sleep(poll_after_seconds)

            self.error.emit(_TR("We couldn’t finish checking this file yet. Please try again."))

        except ApiError as e:
            self.error.emit(_friendly_upload_error_message(e))
        except RuntimeError as exc:
            if (
                _is_connection_refused_error(exc)
                or _is_tls_handshake_timeout(exc)
                or _is_request_timeout(exc)
            ):
                logger.info(
                    "Import upload worker hit local readiness issue for %s: %s", self.file_path, exc
                )
            else:
                logger.exception("Import upload worker failed for %s", self.file_path)
            self.error.emit(_friendly_upload_error_message(exc))
        except Exception as exc:
            logger.exception("Import upload worker failed for %s", self.file_path)
            self.error.emit(_friendly_upload_error_message(exc))

    def _request_import_post(
        self,
        path: str,
        payload: dict[str, object],
        *,
        retry_status_text: str,
    ) -> dict[str, object]:
        import time

        from app.services.api_client import api_post, as_dict
        from app.services.api_client_errors import ApiError

        max_attempts = 2 if _is_local_secure_import_base_url() else 1
        for attempt in range(1, max_attempts + 1):
            try:
                return as_dict(api_post(path, payload, timeout=_IMPORT_BOOTSTRAP_TIMEOUT_SECONDS))
            except ApiError as exc:
                if (
                    attempt < max_attempts
                    and exc.status_code == 503
                    and exc.code in {"IMPORT_SERVICE_WARMING_UP", "IMPORT_STORAGE_NOT_READY"}
                ):
                    retry_after_ms = 1500
                    if isinstance(exc.payload, dict):
                        raw_retry = exc.payload.get("retry_after_ms")
                        if isinstance(raw_retry, (int, float)) and not isinstance(raw_retry, bool):
                            retry_after_ms = max(250, int(raw_retry))
                    self.status.emit(retry_status_text)
                    time.sleep(retry_after_ms / 1000.0)
                    continue
                raise
            except RuntimeError as exc:
                if (
                    attempt < max_attempts
                    and _is_local_secure_import_base_url()
                    and _is_tls_handshake_timeout(exc)
                ):
                    self.status.emit(retry_status_text)
                    time.sleep(_LOCAL_TLS_RETRY_DELAY_SECONDS)
                    continue
                raise
        raise RuntimeError(f"Import request failed unexpectedly: {path}")


def _post_presigned_upload(
    url: str,
    fields: dict[str, object],
    filename: str,
    file_path: str,
    content_type: str,
) -> None:
    from requests import RequestException, post

    from app.services.api_client import ApiError

    try:
        with open(file_path, "rb") as handle:
            files = {"file": (filename, handle, content_type)}
            response = post(url, data=fields, files=files, timeout=30)
    except RequestException as exc:
        raise ApiError(502, f"Upload failed: {exc}") from exc
    if response.status_code >= 400:
        raise ApiError(response.status_code, response.text or "Upload failed")


class StepUpload(QWidget):
    nextRequested = Signal()

    def __init__(self, controller: ImportWizardController) -> None:
        super().__init__()
        self.setObjectName("importStepUpload")
        self.controller = controller
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(12)
        self._worker: UploadWorker | None = None

        # Header
        header = QVBoxLayout()
        self.title_label = QLabel(_TR("Bring in your file"))
        self.title_label.setObjectName("StepTitle")
        self.desc_label = QLabel(
            _TR(
                "Excel, CSV or ODS. We’ll check it and organize it for you before anything is added."
            )
        )
        self.desc_label.setObjectName("StepDescription")
        self.bundle_hint_label = QLabel("")
        self.bundle_hint_label.setObjectName("StepDescription")
        self.bundle_hint_label.setWordWrap(True)
        header.addWidget(self.title_label)
        header.addWidget(self.desc_label)
        header.addWidget(self.bundle_hint_label)
        self._layout.addLayout(header)

        # Drop Zone
        self.drop_zone = DragDropZone()
        self.drop_zone.setObjectName("importUploadDropZone")
        self.drop_zone.fileDropped.connect(self._handle_file)
        self._layout.addWidget(self.drop_zone)

        # Loading State
        self.progress_container = QWidget()
        self.progress_container.setObjectName("importUploadProgressContainer")
        self.progress_container.setVisible(False)
        p_layout = QVBoxLayout(self.progress_container)
        p_layout.setContentsMargins(0, 0, 0, 0)
        p_layout.setSpacing(10)
        self.upload_label = QLabel(_TR("Uploading your file..."))
        self.upload_label.setObjectName("importUploadStatusLabel")
        self.upload_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("importUploadProgressBar")
        self.progress_bar.setRange(0, 0)
        p_layout.addWidget(self.upload_label)
        p_layout.addWidget(self.progress_bar)

        self._layout.addWidget(self.progress_container)
        self._layout.addStretch()
        self.controller.stateChanged.connect(self._refresh_copy)
        self._refresh_copy()

    def _reset_import_state_for_new_upload(self, *, file_path: str) -> None:
        self.controller.update_state(
            filename=os.path.basename(file_path),
            file_type="",
            session_id="",
            task_id="",
            row_count=0,
            detected_entity="",
            headers=[],
            detected_columns=[],
            column_mapping={},
            preview_rows=[],
            stats={},
            inference_summary={},
            bundle_mode="single_entity",
            topology_side_hint="unknown",
            file_model_hint="unknown",
            dominant_side="unknown",
            dominant_side_confidence=0.0,
            row_mixed_review_count=0,
            semantic_projection_conflicts=[],
            price_dialect_summary={},
            import_supported=True,
            blocking_code="",
            blocking_message="",
            entity_type_confidence=0.0,
            manual_mapping_required=False,
            manual_mapping_reasons=[],
            recoverability_summary={},
            sheet_profiles=[],
            column_semantic_profiles=[],
            agency_profile_hints_used={},
            progress_detail={},
            execution_profile="",
            queue_name="",
            queue_position=0,
            agency_queue_depth=0,
            cancellation_state="",
            preview_entity_counts={},
            preview_auto_fix_summary={},
            preview_attention_summary={},
            result_entity_counts={},
            result_auto_fix_summary={},
            result_attention_summary={},
            review_groups=[],
            review_page=None,
            review_pane_state=ImportReviewPaneState(),
            progress=0,
            status="uploading",
            stage="",
            review_count=0,
            review_pending_group_count=0,
            review_mode="groups",
            review_state="none",
            overflow_blocking=False,
            review_disabled=False,
            review_disabled_reason="",
            review_overflow_count=0,
            review_total_count=0,
            review_rows=[],
            error_message="",
            created_count=0,
            updated_count=0,
            skipped_count=0,
            error_count=0,
        )

    def _refresh_copy(self) -> None:
        entity_hint = str(self.controller.state.entity_hint or "").strip().lower()
        if entity_hint == "client":
            self.title_label.setText(_TR("Bring in clients and requests"))
            self.desc_label.setText(
                _TR(
                    "Excel, CSV or ODS. The easiest format is one file with each client and their requests."
                )
            )
            self.bundle_hint_label.setText(
                _TR("Recommended: one combined file with clients and requests.")
            )
            return
        if entity_hint == "listing":
            self.title_label.setText(_TR("Bring in properties and offers"))
            self.desc_label.setText(
                _TR(
                    "Excel, CSV or ODS. The easiest format is one file with each property and its offers."
                )
            )
            self.bundle_hint_label.setText(
                _TR("Recommended: one combined file with properties and offers.")
            )
            return
        self.title_label.setText(_TR("Bring in your file"))
        self.desc_label.setText(
            _TR(
                "Excel, CSV or ODS. We’ll check it and organize it for you before anything is added."
            )
        )
        self.bundle_hint_label.setText("")

    def _handle_file(self, file_path: str) -> None:
        if self._worker is not None and self._worker.isRunning():
            self.upload_label.setText(_TR("Your file is already uploading..."))
            return
        logger.debug("Import file selected: %s", file_path)
        self.drop_zone.setVisible(False)
        self.progress_container.setVisible(True)
        self.upload_label.setText(_TR("Uploading your file..."))
        self._reset_import_state_for_new_upload(file_path=file_path)

        entity_hint = self.controller.state.entity_hint or None
        worker = UploadWorker(file_path, entity_hint=entity_hint)
        self._worker = worker
        worker.status.connect(self.upload_label.setText)
        worker.error.connect(self._on_error)
        worker.uploadFinished.connect(self._on_success)
        worker.finished.connect(lambda: self._on_worker_finished(worker))
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _on_worker_finished(self, worker: UploadWorker) -> None:
        if self._worker is worker:
            self._worker = None

    def _on_success(self, data: dict[str, object]) -> None:
        logger.debug("Import upload succeeded; moving to mapping step")
        row_count_raw = data.get("row_count", 0)
        row_count = int(row_count_raw) if isinstance(row_count_raw, (int, float, str)) else 0
        inference_summary_raw = data.get("inference_summary", {})
        inference_summary = (
            {str(key): value for key, value in inference_summary_raw.items()}
            if isinstance(inference_summary_raw, dict)
            else {}
        )
        final_inference_raw = inference_summary.get("final_inference", {})
        final_inference = (
            {str(key): value for key, value in final_inference_raw.items()}
            if isinstance(final_inference_raw, dict)
            else {}
        )
        if not final_inference and any(
            key in inference_summary
            for key in (
                "bundle_mode",
                "topology_side_hint",
                "file_model_hint",
                "dominant_side",
                "detected_entity",
            )
        ):
            final_inference = {
                str(key): value
                for key, value in inference_summary.items()
                if str(key)
                in {
                    "bundle_mode",
                    "topology_side_hint",
                    "file_model_hint",
                    "dominant_side",
                    "dominant_side_confidence",
                    "detected_entity",
                    "confidence",
                    "row_mixed_review_count",
                    "semantic_projection_conflicts",
                    "import_supported",
                    "blocking_code",
                    "blocking_message",
                }
            }
            inference_summary = {"final_inference": dict(final_inference), **inference_summary}
        detected_entity = str(
            data.get("detected_entity")
            or final_inference.get("detected_entity")
            or self.controller.state.entity_hint
            or "client"
        )
        detected_columns_raw = data.get("detected_columns", [])
        detected_columns = (
            list(detected_columns_raw) if isinstance(detected_columns_raw, list) else []
        )
        progress_detail_raw = data.get("progress_detail", {})
        progress_detail = (
            {str(key): value for key, value in progress_detail_raw.items()}
            if isinstance(progress_detail_raw, dict)
            else {}
        )
        manual_mapping_required = bool(
            data.get("manual_mapping_required")
            or inference_summary.get("manual_mapping_required", False)
        )
        manual_mapping_reasons_raw = data.get(
            "manual_mapping_reasons",
            inference_summary.get("manual_mapping_reasons", []),
        )
        manual_mapping_reasons = (
            [str(reason) for reason in manual_mapping_reasons_raw]
            if isinstance(manual_mapping_reasons_raw, list)
            else []
        )
        recoverability_summary_raw = inference_summary.get("preview_recoverability_summary", {})
        recoverability_summary = (
            {
                str(key): int(value)
                for key, value in recoverability_summary_raw.items()
                if isinstance(value, (int, float))
            }
            if isinstance(recoverability_summary_raw, dict)
            else {}
        )
        preview_entity_counts_raw = data.get(
            "preview_entity_counts",
            inference_summary.get("preview_entity_counts", {}),
        )
        preview_entity_counts = (
            {
                str(key): int(value)
                for key, value in preview_entity_counts_raw.items()
                if isinstance(value, (int, float))
            }
            if isinstance(preview_entity_counts_raw, dict)
            else {}
        )
        preview_auto_fix_summary_raw = data.get(
            "preview_auto_fix_summary",
            inference_summary.get("preview_auto_fix_summary", {}),
        )
        preview_auto_fix_summary = (
            {
                str(key): int(value)
                for key, value in preview_auto_fix_summary_raw.items()
                if isinstance(value, (int, float))
            }
            if isinstance(preview_auto_fix_summary_raw, dict)
            else {}
        )
        preview_attention_summary_raw = data.get(
            "preview_attention_summary",
            inference_summary.get("preview_attention_summary", {}),
        )
        preview_attention_summary = (
            {
                str(key): int(value)
                for key, value in preview_attention_summary_raw.items()
                if isinstance(value, (int, float))
            }
            if isinstance(preview_attention_summary_raw, dict)
            else {}
        )
        sheet_profiles_raw = data.get("sheet_profiles", inference_summary.get("sheet_profiles", []))
        sheet_profiles = list(sheet_profiles_raw) if isinstance(sheet_profiles_raw, list) else []
        column_semantic_profiles_raw = data.get(
            "column_semantic_profiles",
            inference_summary.get("column_semantic_profiles", []),
        )
        column_semantic_profiles = (
            list(column_semantic_profiles_raw)
            if isinstance(column_semantic_profiles_raw, list)
            else []
        )
        column_mapping_raw = data.get(
            "column_mapping",
            inference_summary.get("column_mapping", {}),
        )
        column_mapping = (
            {str(key): str(value) for key, value in column_mapping_raw.items()}
            if isinstance(column_mapping_raw, dict)
            else {}
        )
        agency_profile_hints_raw = data.get(
            "agency_profile_hints_used",
            inference_summary.get("agency_profile_hints_used", {}),
        )
        agency_profile_hints_used = (
            {str(key): value for key, value in agency_profile_hints_raw.items()}
            if isinstance(agency_profile_hints_raw, dict)
            else {}
        )
        price_dialect_summary_raw = data.get(
            "price_dialect_summary",
            inference_summary.get("price_dialect_summary", {}),
        )
        price_dialect_summary = (
            {str(key): value for key, value in price_dialect_summary_raw.items()}
            if isinstance(price_dialect_summary_raw, dict)
            else {}
        )
        mapping_palette_mode, _candidate_entities = derive_mapping_palette_state(
            bundle_mode=str(final_inference.get("bundle_mode", "single_entity") or "single_entity"),
            topology_side_hint=str(
                final_inference.get("topology_side_hint", "unknown") or "unknown"
            ),
            detected_entity=detected_entity,
            manual_mapping_required=manual_mapping_required,
            detected_columns=detected_columns,
            column_mapping=column_mapping,
            sheet_profiles=sheet_profiles,
            selected_sheet_name=str(inference_summary.get("selected_sheet_name", "") or ""),
        )
        self.controller.update_state(
            session_id=str(data.get("session_id", "")),
            task_id=str(data.get("task_id", "")),
            file_type=str(data.get("file_type", "csv")),
            row_count=row_count,
            detected_entity=detected_entity,
            detected_columns=detected_columns,
            column_mapping=column_mapping,
            preview_rows=data.get("preview_rows", []),
            inference_summary=inference_summary,
            bundle_mode=str(final_inference.get("bundle_mode", "single_entity") or "single_entity"),
            topology_side_hint=str(
                final_inference.get("topology_side_hint", "unknown") or "unknown"
            ),
            file_model_hint=str(final_inference.get("file_model_hint", "unknown") or "unknown"),
            dominant_side=str(final_inference.get("dominant_side", "unknown") or "unknown"),
            dominant_side_confidence=float(
                final_inference.get("dominant_side_confidence", 0.0) or 0.0
            ),
            row_mixed_review_count=int(final_inference.get("row_mixed_review_count", 0) or 0),
            semantic_projection_conflicts=[
                str(value)
                for value in list(final_inference.get("semantic_projection_conflicts", []) or [])
            ],
            price_dialect_summary=price_dialect_summary,
            import_supported=bool(final_inference.get("import_supported", True)),
            blocking_code=str(final_inference.get("blocking_code", "") or ""),
            blocking_message=str(final_inference.get("blocking_message", "") or ""),
            entity_type_confidence=float(final_inference.get("confidence", 0.0) or 0.0),
            manual_mapping_required=manual_mapping_required,
            manual_mapping_reasons=manual_mapping_reasons,
            recoverability_summary=recoverability_summary,
            mapping_palette_mode=mapping_palette_mode,
            sheet_profiles=sheet_profiles,
            column_semantic_profiles=column_semantic_profiles,
            agency_profile_hints_used=agency_profile_hints_used,
            progress_detail=progress_detail,
            preview_entity_counts=preview_entity_counts,
            preview_auto_fix_summary=preview_auto_fix_summary,
            preview_attention_summary=preview_attention_summary,
            status="mapping",
        )

        cols = detected_columns
        if isinstance(cols, list):
            headers = [c.get("header") for c in cols if isinstance(c, dict) and "header" in c]
            state_preview = data.get("preview_rows")
            if not headers and isinstance(state_preview, list) and state_preview:
                first = state_preview[0]
                if isinstance(first, dict):
                    headers = [str(k) for k in first.keys()]
            self.controller.update_state(headers=headers)

        self.nextRequested.emit()

    def _on_error(self, message: str) -> None:
        logger.warning("Import upload error: %s", message)
        self.upload_label.setText(message)
        self.progress_container.setVisible(False)
        self.drop_zone.setVisible(True)
        self.controller.update_state(status="failed", error_message=message)
        self.controller.errorOccurred.emit(message)
