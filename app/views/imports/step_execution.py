import logging
from typing import Literal

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.services.api_client_errors import ApiError
from app.utils.i18n import tr_factory
from app.utils.qt_async import run_background_result
from app.views.imports.import_experience import review_group_from_payload, review_page_from_payload
from app.views.imports.wizard_state import ImportWizardController
from app.widgets.collapsible_section import CollapsibleSection

logger = logging.getLogger(__name__)
_TR = tr_factory("ImportWizardStepExecution")
_DEFAULT_ACTIVE_POLL_MS = 1000
_DEFAULT_PARSE_POLL_MS = 150
_DEFAULT_QUEUE_POLL_MS = 1000


def _coerce_int_mapping(value: object) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    return {
        str(key): int(item) for key, item in value.items() if isinstance(item, (int, float, str))
    }


def _coerce_poll_after_ms(value: object, fallback_ms: int) -> int:
    if isinstance(value, bool):
        return max(50, min(int(value), 5000))
    if isinstance(value, int):
        return max(50, min(value, 5000))
    if isinstance(value, float):
        return max(50, min(int(value), 5000))
    if isinstance(value, str):
        try:
            return max(50, min(int(value), 5000))
        except ValueError:
            return max(50, min(int(fallback_ms), 5000))
    return max(50, min(int(fallback_ms), 5000))


class StepExecution(QWidget):
    finished = Signal()
    reviewRequested = Signal()
    closeRequested = Signal()

    def __init__(self, controller: ImportWizardController) -> None:
        super().__init__()
        self.setObjectName("importStepExecution")
        self.controller = controller
        self._layout = QVBoxLayout(self)
        self._layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._layout.setContentsMargins(0, 8, 0, 8)
        self._layout.setSpacing(12)
        self._timer: QTimer | None = None
        self._task_id = ""
        self._poll_inflight = False
        self._poll_failures = 0
        self._max_poll_failures = 5
        self._review_fetch_failures = 0
        self._max_review_fetch_failures = 5
        self._pending_review_session_id = ""
        self.destroyed.connect(self._handle_destroyed)

        self.status_label = QLabel(_TR("We’re preparing your import"))
        self.status_label.setObjectName("StepTitle")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.subtitle_label = QLabel(_TR("We’re organizing your file and checking the details."))
        self.subtitle_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.subtitle_label.setWordWrap(True)

        self.detail_section = CollapsibleSection(_TR("View progress details"), collapsible=True)
        self.detail_section.setObjectName("importExecutionDetailSection")
        self.detail_label = QLabel("")
        self.detail_label.setObjectName("importExecutionDetailLabel")
        self.detail_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.detail_label.setWordWrap(True)
        self.detail_section.set_content(self.detail_label)
        self.detail_section.set_collapsed(True)

        self.retry_hint = QLabel("")
        self.retry_hint.setObjectName("importExecutionRetryHint")
        self.retry_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.retry_hint.setWordWrap(True)

        self.actions_layout = QHBoxLayout()
        self.close_btn = QPushButton(_TR("Close for now"))
        self.close_btn.setObjectName("importExecutionCloseButton")
        self.close_btn.setProperty("immoVariant", "secondary")
        self.close_btn.clicked.connect(self.closeRequested.emit)
        self.cancel_btn = QPushButton(_TR("Cancel import"))
        self.cancel_btn.setObjectName("importExecutionCancelButton")
        self.cancel_btn.setProperty("immoVariant", "ghost")
        self.cancel_btn.clicked.connect(self._request_cancel)
        self.retry_btn = QPushButton(_TR("Check again"))
        self.retry_btn.setObjectName("importExecutionRetryButton")
        self.retry_btn.setProperty("immoVariant", "ghost")
        self.retry_btn.clicked.connect(self._retry_status_now)
        self.actions_layout.addWidget(self.close_btn)
        self.actions_layout.addStretch()
        self.actions_layout.addWidget(self.retry_btn)
        self.actions_layout.addWidget(self.cancel_btn)

        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("importExecutionProgress")
        self.progress_bar.setProperty("immoState", "default")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(12)
        self.progress_bar.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )

        self._layout.addWidget(self.status_label)
        self._layout.addWidget(self.subtitle_label)
        self._layout.addWidget(self.progress_bar)
        self._layout.addWidget(self.detail_section)
        self._layout.addWidget(self.retry_hint)
        self._layout.addLayout(self.actions_layout)
        self.retry_btn.setVisible(False)
        self.cancel_btn.setEnabled(False)

    def start_import(self) -> None:
        self.status_label.setText(_TR("We’re preparing your import"))
        self.subtitle_label.setText(_TR("We’re organizing your file and checking the details."))
        self.progress_bar.setProperty("immoState", "default")
        style = self.progress_bar.style()
        style.unpolish(self.progress_bar)
        style.polish(self.progress_bar)
        self.progress_bar.setValue(0)
        self.detail_label.setText("")
        self.retry_hint.setText("")
        self._apply_action_state(can_cancel=False, can_close=True, show_retry=False)
        self._poll_failures = 0
        self._poll_inflight = False
        self._review_fetch_failures = 0
        self._pending_review_session_id = ""

        run_background_result(
            self._trigger_execution,
            self._handle_execute_started,
            self._handle_execute_error,
        )

    def _trigger_execution(self) -> tuple[str, int]:
        from app.services.api_client import api_post, as_dict

        state = self.controller.state

        payload = {
            "session_id": state.session_id,
            "column_mapping": state.column_mapping,
            "entity_type": state.detected_entity,
            "duplicate_strategy": "review",
        }

        try:
            logger.debug("Executing import for session %s", state.session_id)
            resp = api_post("import/execute/", payload)
            data = as_dict(resp)

            session_id = str(data.get("session_id", "") or state.session_id or "")
            # The execution status endpoint is stable on session_id; Celery task ids can change
            # when the importer is redispatched after watchdog repair.
            new_task_id = str(data.get("task_id", ""))
            initial_poll_ms = _coerce_poll_after_ms(
                data.get("poll_after_ms"), _DEFAULT_PARSE_POLL_MS
            )
            poll_id = session_id or new_task_id
            logger.debug(
                "Import execution session_id=%s task_id=%s poll_id=%s",
                session_id,
                new_task_id,
                poll_id,
            )

            if not poll_id:
                raise RuntimeError(_TR("We couldn't start polling this import yet."))

            return poll_id, initial_poll_ms
        except Exception:
            logger.exception("Import execution trigger failed")
            raise

    def _handle_execute_started(self, payload: tuple[str, int]) -> None:
        task_id, initial_poll_ms = payload
        self._start_polling(task_id, initial_poll_ms)

    def _handle_execute_error(self, error: Exception) -> None:
        if isinstance(error, ApiError):
            if error.status_code == 409:
                self._on_error(error.message or _TR("A few details still need your attention."))
                return
            if error.status_code == 429:
                self._on_error(
                    error.message
                    or _TR("Import capacity is busy right now. Please wait a moment and try again.")
                )
                return
        self._on_error(str(error))

    def _start_polling(
        self, task_id: str, initial_interval_ms: int = _DEFAULT_ACTIVE_POLL_MS
    ) -> None:
        self._stop_polling()
        self._task_id = task_id
        self._timer = QTimer(self)
        self._timer.setInterval(_coerce_poll_after_ms(initial_interval_ms, _DEFAULT_ACTIVE_POLL_MS))
        self._timer.timeout.connect(self._poll_current_status)
        self._timer.start()
        self._poll_status(task_id)

    def _poll_current_status(self) -> None:
        if not self._task_id:
            return
        self._poll_status(self._task_id)

    def _stop_polling(self) -> None:
        if self._timer is not None:
            self._timer.stop()
            self._timer.deleteLater()
            self._timer = None
        self._task_id = ""

    def _handle_destroyed(self, _obj: object | None = None) -> None:
        self._stop_polling()
        self._pending_review_session_id = ""

    def _update_poll_interval(self, value: object, fallback_ms: int) -> None:
        if self._timer is None:
            return
        next_interval_ms = _coerce_poll_after_ms(value, fallback_ms)
        if self._timer.interval() != next_interval_ms:
            self._timer.setInterval(next_interval_ms)

    def _apply_action_state(
        self,
        *,
        can_cancel: bool,
        can_close: bool,
        show_retry: bool,
    ) -> None:
        self.close_btn.setEnabled(can_close)
        self.cancel_btn.setEnabled(can_cancel)
        self.retry_btn.setVisible(show_retry)

    def _retry_status_now(self) -> None:
        self.retry_btn.setVisible(False)
        self._poll_failures = 0
        self._poll_current_status()

    def _perform_cancel_request(self) -> dict[str, object]:
        from app.services.api_client import api_post, as_dict

        session_id = str(self.controller.state.session_id or "")
        if not session_id:
            raise RuntimeError(_TR("We couldn't cancel this import right now."))
        response = api_post(f"import/{session_id}/cancel/", {})
        data = as_dict(response)
        return {str(key): value for key, value in data.items()}

    def _request_cancel(self) -> None:
        if not self.cancel_btn.isEnabled():
            return
        self.cancel_btn.setEnabled(False)
        self.retry_hint.setText(_TR("Cancelling your import..."))
        run_background_result(
            self._perform_cancel_request,
            self._handle_cancel_success,
            self._handle_cancel_error,
        )

    def _handle_cancel_success(self, data: dict[str, object]) -> None:
        self.cancel_btn.setEnabled(False)
        detail = str(data.get("detail", "") or "")
        if detail:
            self.retry_hint.setText(detail)
        self._on_poll_result(data)

    def _handle_cancel_error(self, error: Exception) -> None:
        self.cancel_btn.setEnabled(True)
        self.retry_hint.setText(_TR("We couldn’t cancel this import yet. Please try again."))
        self.detail_label.setText(str(error))
        self._apply_action_state(
            can_cancel=True,
            can_close=True,
            show_retry=True,
        )

    def _poll_status(self, task_id: str) -> None:
        if self._poll_inflight:
            return
        self._poll_inflight = True
        run_background_result(
            self._perform_poll,
            self._on_poll_result,
            self._handle_poll_exception,
            task_id,
        )

    def _perform_poll(self, task_id: str) -> dict[str, object]:
        from app.services.api_client import api_get, as_dict

        try:
            resp = api_get(f"import/status/{task_id}/")
            data = as_dict(resp)
            logger.debug(
                "Import poll result task=%s status=%s progress=%s",
                task_id,
                data.get("status"),
                data.get("progress"),
            )

            return {str(key): value for key, value in data.items()}
        except Exception as e:
            logger.warning("Import poll failed for task %s: %s", task_id, e)
            raise

    def _handle_poll_exception(self, error: Exception) -> None:
        self._on_poll_error(str(error))

    def _clear_poll_inflight(self) -> None:
        self._poll_inflight = False

    def _on_poll_result(self, data: dict[str, object]) -> None:
        self._poll_inflight = False
        self._poll_failures = 0
        status_val = str(data.get("status", ""))
        progress_raw = data.get("progress", 0)
        progress = int(progress_raw) if isinstance(progress_raw, (int, float, str)) else 0
        error_msg = str(data.get("error_message", ""))
        stage_val = str(data.get("stage", "") or "")
        progress_detail_raw = data.get("progress_detail", {})
        progress_detail = (
            {str(key): value for key, value in progress_detail_raw.items()}
            if isinstance(progress_detail_raw, dict)
            else {}
        )
        preview_entity_counts = _coerce_int_mapping(data.get("preview_entity_counts"))
        preview_auto_fix_summary = _coerce_int_mapping(data.get("preview_auto_fix_summary"))
        preview_attention_summary = _coerce_int_mapping(data.get("preview_attention_summary"))
        result_entity_counts = _coerce_int_mapping(data.get("result_entity_counts"))
        result_auto_fix_summary = _coerce_int_mapping(data.get("result_auto_fix_summary"))
        result_attention_summary = _coerce_int_mapping(data.get("result_attention_summary"))
        review_count_raw = data.get("review_count", 0)
        review_count = (
            int(review_count_raw) if isinstance(review_count_raw, (int, float, str)) else 0
        )
        review_overflow_raw = data.get("review_overflow_count", 0)
        review_overflow_count = (
            int(review_overflow_raw) if isinstance(review_overflow_raw, (int, float, str)) else 0
        )
        review_total_raw = data.get("review_total_count", review_count + review_overflow_count)
        review_total_count = (
            int(review_total_raw)
            if isinstance(review_total_raw, (int, float, str))
            else review_count + review_overflow_count
        )
        review_state = str(data.get("review_state", "none") or "none")
        overflow_blocking = bool(data.get("overflow_blocking", False))
        review_disabled = bool(data.get("review_disabled", False))
        review_disabled_reason = str(data.get("review_disabled_reason", "") or "")
        result_zero_change = bool(data.get("result_zero_change", False))
        zero_change_reasons_raw = data.get("result_zero_change_reasons", [])
        result_zero_change_reasons = (
            [str(value) for value in zero_change_reasons_raw if str(value or "").strip()]
            if isinstance(zero_change_reasons_raw, list)
            else []
        )
        terminal_reason = str(data.get("terminal_reason", "") or "")
        session_id = str(data.get("session_id", self.controller.state.session_id) or "")
        queue_position_raw = data.get("queue_position", 0)
        agency_queue_depth_raw = data.get("agency_queue_depth", 0)
        cancellation_state = str(data.get("cancellation_state", "") or "")
        wait_state = str(data.get("wait_state", "") or "")
        wait_reason = str(data.get("wait_reason", "") or "")
        wait_seconds_raw = data.get("wait_seconds", 0)
        wait_seconds = (
            int(wait_seconds_raw) if isinstance(wait_seconds_raw, (int, float, str)) else 0
        )
        stalled = bool(data.get("stalled", False))
        stalled_reason = str(data.get("stalled_reason", "") or "")
        can_cancel = bool(data.get("can_cancel", False))
        can_close = bool(data.get("can_close", True))
        queued_at = str(data.get("queued_at", "") or "")
        started_at = str(data.get("started_at", "") or "")
        last_phase_started_at = str(data.get("last_phase_started_at", "") or "")
        last_phase_heartbeat_at = str(data.get("last_phase_heartbeat_at", "") or "")
        mapping_palette_mode = str(data.get("mapping_palette_mode", "") or "")

        self.progress_bar.setValue(progress)
        if status_val == "queued":
            self._update_poll_interval(data.get("poll_after_ms"), _DEFAULT_QUEUE_POLL_MS)
            queue_position = (
                int(queue_position_raw) if isinstance(queue_position_raw, (int, float, str)) else 0
            )
            agency_queue_depth = (
                int(agency_queue_depth_raw)
                if isinstance(agency_queue_depth_raw, (int, float, str))
                else 0
            )
            self.status_label.setText(_TR("Your import is waiting its turn"))
            self.subtitle_label.setText(
                _TR(
                    "Another import from your agency is finishing first. We’ll start yours automatically."
                )
            )
            if wait_state == "waiting_for_worker":
                self.status_label.setText(_TR("Your import is starting soon"))
                self.subtitle_label.setText(
                    _TR("Your import is accepted, but it has not started yet.")
                )
            if stalled:
                self.status_label.setText(_TR("This import is taking longer than usual"))
                self.subtitle_label.setText(
                    _TR("You can close this window for now or cancel the import.")
                )
            self.detail_label.setText(
                _TR("Position {position} of {depth}. Runtime profile: {profile}").format(
                    position=max(1, queue_position),
                    depth=max(1, agency_queue_depth),
                    profile=str(data.get("execution_profile", "") or ""),
                )
            )
            if cancellation_state == "cancel_requested":
                self.retry_hint.setText(_TR("Cancellation requested. We’re stopping this import."))
            elif stalled_reason == "queue_not_advancing":
                self.retry_hint.setText(_TR("This import has not moved yet."))
            elif stalled_reason == "worker_not_picked_up":
                self.retry_hint.setText(_TR("This import has not started yet."))
            else:
                self.retry_hint.setText("")
            self._apply_action_state(
                can_cancel=can_cancel,
                can_close=can_close,
                show_retry=stalled or self._poll_failures > 0,
            )
            self.controller.update_state(
                status="queued",
                stage=stage_val or "executing",
                progress=progress,
                progress_detail=progress_detail,
                preview_entity_counts=preview_entity_counts,
                preview_auto_fix_summary=preview_auto_fix_summary,
                preview_attention_summary=preview_attention_summary,
                result_entity_counts=result_entity_counts,
                result_auto_fix_summary=result_auto_fix_summary,
                result_attention_summary=result_attention_summary,
                review_overflow_count=review_overflow_count,
                review_total_count=review_total_count,
                review_state=review_state,
                overflow_blocking=overflow_blocking,
                review_disabled=review_disabled,
                review_disabled_reason=review_disabled_reason,
                result_zero_change=result_zero_change,
                result_zero_change_reasons=result_zero_change_reasons,
                terminal_reason=terminal_reason,
                execution_profile=str(data.get("execution_profile", "") or ""),
                queue_name=str(data.get("queue_name", "") or ""),
                queue_position=queue_position,
                agency_queue_depth=agency_queue_depth,
                cancellation_state=cancellation_state,
                queued_at=queued_at,
                started_at=started_at,
                last_phase_started_at=last_phase_started_at,
                last_phase_heartbeat_at=last_phase_heartbeat_at,
                wait_state=wait_state or "queued",
                wait_reason=wait_reason,
                wait_seconds=wait_seconds,
                stalled=stalled,
                stalled_reason=stalled_reason,
                can_cancel=can_cancel,
                can_close=can_close,
                mapping_palette_mode=mapping_palette_mode
                or self.controller.state.mapping_palette_mode,
            )
            return
        self._update_poll_interval(data.get("poll_after_ms"), _DEFAULT_ACTIVE_POLL_MS)
        if cancellation_state == "cancel_requested":
            self.status_label.setText(_TR("Cancelling your import"))
            self.subtitle_label.setText(
                _TR("We’re stopping the active work and will finish cleaning up shortly.")
            )
        elif wait_state == "waiting_for_worker":
            self.status_label.setText(_TR("Your import is starting soon"))
            self.subtitle_label.setText(_TR("Your import is accepted, but it has not started yet."))
        elif stalled:
            self.status_label.setText(_TR("This import is taking longer than usual"))
            self.subtitle_label.setText(_TR("You can close this window for now or check again."))
        else:
            self.status_label.setText(_TR("We’re preparing your import"))
            self.subtitle_label.setText(_TR("We’re organizing your file and checking the details."))
        rows_processed = int(progress_detail.get("rows_processed", 0) or 0)
        rows_total = int(progress_detail.get("rows_total", 0) or 0)
        rows_created = int(progress_detail.get("rows_created", 0) or 0)
        rows_updated = int(progress_detail.get("rows_updated", 0) or 0)
        rows_skipped = int(progress_detail.get("rows_skipped", 0) or 0)
        rows_review = int(progress_detail.get("rows_review", 0) or 0)
        current_chunk = int(progress_detail.get("current_chunk", 0) or 0)
        chunks_total = int(progress_detail.get("chunks_total", 0) or 0)
        phase = str(progress_detail.get("phase", stage_val or "executing") or "executing")
        human_phase = {
            "prepare": _TR("Organizing names, phones and locations"),
            "plan": _TR("Preparing your file for import"),
            "load": _TR("Adding your data to the agency"),
            "rebuild": _TR("Finishing up"),
            "review": _TR("A few details need your attention"),
        }.get(phase, _TR("Checking your file"))
        if cancellation_state == "cancel_requested":
            self.retry_hint.setText(_TR("Cancellation requested. We’re stopping this import."))
        elif stalled_reason == "phase_heartbeat_expired":
            self.retry_hint.setText(_TR("This step stopped sending updates for too long."))
        elif wait_state == "waiting_for_worker":
            self.retry_hint.setText(_TR("Still waiting for this import to start."))
        else:
            self.retry_hint.setText(human_phase)
        if rows_total > 0 or chunks_total > 0:
            self.detail_label.setText(
                _TR(
                    "{phase}: {processed}/{total} rows, {created} created, {updated} updated, {skipped} skipped, {review} in review, chunk {chunk}/{chunks}"
                ).format(
                    phase=phase.replace("_", " "),
                    processed=rows_processed,
                    total=rows_total,
                    created=rows_created,
                    updated=rows_updated,
                    skipped=rows_skipped,
                    review=rows_review,
                    chunk=current_chunk,
                    chunks=chunks_total,
                )
            )
        else:
            self.detail_label.setText(human_phase)

        self.controller.update_state(
            status=status_val or "running",
            stage=stage_val or "executing",
            progress=progress,
            progress_detail=progress_detail,
            preview_entity_counts=preview_entity_counts,
            preview_auto_fix_summary=preview_auto_fix_summary,
            preview_attention_summary=preview_attention_summary,
            result_entity_counts=result_entity_counts,
            result_auto_fix_summary=result_auto_fix_summary,
            result_attention_summary=result_attention_summary,
            review_overflow_count=review_overflow_count,
            review_total_count=review_total_count,
            review_state=review_state,
            overflow_blocking=overflow_blocking,
            review_disabled=review_disabled,
            review_disabled_reason=review_disabled_reason,
            result_zero_change=result_zero_change,
            result_zero_change_reasons=result_zero_change_reasons,
            terminal_reason=terminal_reason,
            execution_profile=str(data.get("execution_profile", "") or ""),
            queue_name=str(data.get("queue_name", "") or ""),
            queue_position=max(
                0,
                (
                    int(queue_position_raw)
                    if isinstance(queue_position_raw, (int, float, str))
                    else 0
                ),
            ),
            agency_queue_depth=max(
                0,
                (
                    int(agency_queue_depth_raw)
                    if isinstance(agency_queue_depth_raw, (int, float, str))
                    else 0
                ),
            ),
            cancellation_state=cancellation_state,
            queued_at=queued_at,
            started_at=started_at,
            last_phase_started_at=last_phase_started_at,
            last_phase_heartbeat_at=last_phase_heartbeat_at,
            wait_state=wait_state or "running",
            wait_reason=wait_reason,
            wait_seconds=wait_seconds,
            stalled=stalled,
            stalled_reason=stalled_reason,
            can_cancel=can_cancel,
            can_close=can_close,
            mapping_palette_mode=mapping_palette_mode or self.controller.state.mapping_palette_mode,
        )
        self._apply_action_state(
            can_cancel=can_cancel and status_val not in {"completed", "failed"},
            can_close=can_close,
            show_retry=stalled or self._poll_failures > 0,
        )

        if stage_val == "review" or review_count > 0:
            self._stop_polling()
            self.controller.update_state(
                status="ready",
                stage=stage_val or "review",
                review_count=review_count,
                progress=progress,
                progress_detail=progress_detail,
                preview_entity_counts=preview_entity_counts,
                preview_auto_fix_summary=preview_auto_fix_summary,
                preview_attention_summary=preview_attention_summary,
                result_entity_counts=result_entity_counts,
                result_auto_fix_summary=result_auto_fix_summary,
                result_attention_summary=result_attention_summary,
                review_overflow_count=review_overflow_count,
                review_total_count=review_total_count,
                review_state=review_state,
                overflow_blocking=overflow_blocking,
                review_disabled=review_disabled,
                review_disabled_reason=review_disabled_reason,
                result_zero_change=result_zero_change,
                result_zero_change_reasons=result_zero_change_reasons,
                terminal_reason=terminal_reason,
                execution_profile=str(data.get("execution_profile", "") or ""),
                queue_name=str(data.get("queue_name", "") or ""),
            )
            self._review_fetch_failures = 0
            self._request_review_rows(session_id)
            return

        if status_val in ("completed", "failed"):
            self._stop_polling()
            self.progress_bar.setValue(100)
            last_result = data.get("last_result", {})
            if isinstance(last_result, dict):
                created_raw = data.get("created_count", last_result.get("created_count", 0))
                updated_raw = data.get("updated_count", last_result.get("updated_count", 0))
                errors_raw = data.get("error_count", last_result.get("error_count", 0))
                skipped_raw = data.get("skipped_count", last_result.get("skipped_count", 0))
                created = int(created_raw) if isinstance(created_raw, (int, float, str)) else 0
                updated = int(updated_raw) if isinstance(updated_raw, (int, float, str)) else 0
                errors = int(errors_raw) if isinstance(errors_raw, (int, float, str)) else 0
                skipped = int(skipped_raw) if isinstance(skipped_raw, (int, float, str)) else 0
            else:
                created_raw = data.get("created_count", 0)
                updated_raw = data.get("updated_count", 0)
                errors_raw = data.get("error_count", 0)
                skipped_raw = data.get("skipped_count", 0)
                created = int(created_raw) if isinstance(created_raw, (int, float, str)) else 0
                updated = int(updated_raw) if isinstance(updated_raw, (int, float, str)) else 0
                errors = int(errors_raw) if isinstance(errors_raw, (int, float, str)) else 0
                skipped = int(skipped_raw) if isinstance(skipped_raw, (int, float, str)) else 0
            if created <= 0 and result_entity_counts:
                created = sum(max(0, int(value or 0)) for value in result_entity_counts.values())
            if errors <= 0:
                errors = int(progress_detail.get("error_count", 0) or 0)

            self.controller.update_state(
                status=status_val,
                created_count=created,
                updated_count=updated,
                error_count=errors,
                skipped_count=skipped,
                error_message=error_msg,
                stage=stage_val,
                review_count=review_count,
                progress=100,
                progress_detail=progress_detail,
                preview_entity_counts=preview_entity_counts,
                preview_auto_fix_summary=preview_auto_fix_summary,
                preview_attention_summary=preview_attention_summary,
                result_entity_counts=result_entity_counts,
                result_auto_fix_summary=result_auto_fix_summary,
                result_attention_summary=result_attention_summary,
                review_overflow_count=review_overflow_count,
                review_total_count=review_total_count,
                review_state=review_state,
                overflow_blocking=overflow_blocking,
                review_disabled=review_disabled,
                review_disabled_reason=review_disabled_reason,
                result_zero_change=result_zero_change,
                result_zero_change_reasons=result_zero_change_reasons,
                terminal_reason=terminal_reason,
                execution_profile=str(data.get("execution_profile", "") or ""),
                queue_name=str(data.get("queue_name", "") or ""),
                queue_position=max(
                    0,
                    (
                        int(queue_position_raw)
                        if isinstance(queue_position_raw, (int, float, str))
                        else 0
                    ),
                ),
                agency_queue_depth=max(
                    0,
                    (
                        int(agency_queue_depth_raw)
                        if isinstance(agency_queue_depth_raw, (int, float, str))
                        else 0
                    ),
                ),
                cancellation_state=cancellation_state,
                queued_at=queued_at,
                started_at=started_at,
                last_phase_started_at=last_phase_started_at,
                last_phase_heartbeat_at=last_phase_heartbeat_at,
                wait_state=wait_state or status_val,
                wait_reason=wait_reason,
                wait_seconds=wait_seconds,
                stalled=stalled,
                stalled_reason=stalled_reason,
                can_cancel=False,
                can_close=can_close,
                mapping_palette_mode=mapping_palette_mode
                or self.controller.state.mapping_palette_mode,
            )
            self._apply_action_state(can_cancel=False, can_close=can_close, show_retry=False)
            self.finished.emit()

    def _fetch_review_rows(self, session_id: str) -> dict[str, object]:
        from app.services.api_client import api_get, as_dict

        try:
            response = api_get(f"import/{session_id}/review/")
            data = as_dict(response)
            return {str(key): value for key, value in data.items()}
        except Exception:
            raise

    def _request_review_rows(self, session_id: str) -> None:
        self._pending_review_session_id = session_id
        run_background_result(
            self._fetch_review_rows,
            self._on_review_rows,
            self._handle_review_fetch_error,
            session_id,
        )

    def _on_review_rows(self, data: dict[str, object]) -> None:
        self._review_fetch_failures = 0
        self._pending_review_session_id = ""
        review_rows_raw = data.get("review_rows", [])
        review_rows = list(review_rows_raw) if isinstance(review_rows_raw, list) else []
        review_groups_raw = data.get("review_groups", [])
        review_groups = (
            [
                review_group_from_payload(dict(item))
                for item in review_groups_raw
                if isinstance(item, dict)
            ]
            if isinstance(review_groups_raw, list)
            else []
        )
        review_page_raw = data.get("review_page", {})
        review_page = (
            review_page_from_payload(dict(review_page_raw))
            if isinstance(review_page_raw, dict)
            else None
        )
        review_count_raw = data.get("review_count", len(review_rows))
        review_count = (
            int(review_count_raw)
            if isinstance(review_count_raw, (int, float, str))
            else len(review_rows)
        )
        review_overflow_raw = data.get("review_overflow_count", 0)
        review_overflow_count = (
            int(review_overflow_raw) if isinstance(review_overflow_raw, (int, float, str)) else 0
        )
        review_total_raw = data.get("review_total_count", review_count + review_overflow_count)
        review_total_count = (
            int(review_total_raw)
            if isinstance(review_total_raw, (int, float, str))
            else review_count + review_overflow_count
        )
        review_pending_group_count_raw = data.get("review_pending_group_count", len(review_groups))
        review_pending_group_count = (
            int(review_pending_group_count_raw)
            if isinstance(review_pending_group_count_raw, (int, float, str))
            else len(review_groups)
        )
        review_mode = str(data.get("review_mode", "") or "")
        review_state = str(data.get("review_state", "normal") or "normal")
        overflow_blocking = bool(data.get("overflow_blocking", False))
        review_disabled = bool(data.get("review_disabled", False))
        review_disabled_reason = str(data.get("review_disabled_reason", "") or "")
        filters_raw = data.get("review_filters", {})
        filters = (
            {str(key): value for key, value in filters_raw.items()}
            if isinstance(filters_raw, dict)
            else {}
        )
        review_mode = str(review_mode or filters.get("mode", "groups") or "groups")
        resolved_review_mode: Literal["groups", "items"] = (
            "items" if review_mode == "items" else "groups"
        )
        pane_state = self.controller.state.review_pane_state
        pane_state.mode = resolved_review_mode
        pane_state.review_state = review_state
        pane_state.review_disabled = review_disabled
        pane_state.review_disabled_reason = review_disabled_reason
        pane_state.selected_group_key = (
            str(filters.get("group_key", "") or pane_state.selected_group_key or "") or None
        )
        pane_state.issue_group_filter = str(
            filters.get("issue_group", pane_state.issue_group_filter or "all") or "all"
        )
        pane_state.search_text = str(filters.get("search", pane_state.search_text or "") or "")
        if review_page is not None:
            pane_state.page = int(review_page.page or 1)
            pane_state.page_size = int(review_page.page_size or 50)
        self.controller.update_state(
            status=str(data.get("status", "ready") or "ready"),
            stage=str(data.get("stage", "review") or "review"),
            review_count=review_count,
            review_pending_group_count=review_pending_group_count,
            review_overflow_count=review_overflow_count,
            review_total_count=review_total_count,
            review_mode=resolved_review_mode,
            review_state=review_state,
            overflow_blocking=overflow_blocking,
            review_disabled=review_disabled,
            review_disabled_reason=review_disabled_reason,
            review_groups=review_groups,
            review_page=review_page,
            review_rows=review_rows,
        )
        self.reviewRequested.emit()

    def _handle_review_fetch_error(self, error: Exception) -> None:
        self._review_fetch_failures += 1
        session_id = str(self._pending_review_session_id or "")
        if session_id and self._review_fetch_failures < self._max_review_fetch_failures:
            self.status_label.setText(_TR("We found lines to review"))
            self.subtitle_label.setText(_TR("We’re loading the review details now."))
            self.detail_label.setText(
                _TR("Still loading review details... ({current}/{max})").format(
                    current=self._review_fetch_failures,
                    max=self._max_review_fetch_failures,
                )
            )
            QTimer.singleShot(250, lambda sid=session_id: self._request_review_rows(sid))
            return
        self._pending_review_session_id = ""
        self._on_error(str(error))

    def _on_poll_error(self, message: str) -> None:
        self._clear_poll_inflight()
        self._poll_failures += 1
        if self._poll_failures < self._max_poll_failures:
            self.status_label.setText(
                _TR("We’re still waiting for the server... ({current}/{max})").format(
                    current=self._poll_failures,
                    max=self._max_poll_failures,
                )
            )
            self._apply_action_state(
                can_cancel=bool(self.controller.state.can_cancel),
                can_close=True,
                show_retry=True,
            )
            return
        self._on_error(message)

    def _on_error(self, message: str) -> None:
        self._stop_polling()
        self._poll_inflight = False
        self._pending_review_session_id = ""
        self.status_label.setText(_TR("We couldn’t finish the import this time."))
        self.subtitle_label.setText(
            _TR("Please try again. If the issue continues, contact support.")
        )
        self.detail_label.setText(message)
        self.retry_hint.setText("")
        self.progress_bar.setProperty("immoState", "error")
        style = self.progress_bar.style()
        style.unpolish(self.progress_bar)
        style.polish(self.progress_bar)
        self.progress_bar.setValue(100)
        self._apply_action_state(can_cancel=False, can_close=True, show_retry=True)
        self.controller.update_state(
            status="failed",
            progress=100,
            error_message=message,
        )
        self.finished.emit()
