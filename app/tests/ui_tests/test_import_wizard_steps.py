from __future__ import annotations

import pytest
from PySide6.QtCore import Qt, QUrl
from PySide6.QtWidgets import QLabel

from app.services.api_client_errors import ApiError
from app.views.imports.import_experience import review_group_from_payload
from app.views.imports.step_execution import StepExecution
from app.views.imports.step_mapping import StepMapping
from app.views.imports.step_review import StepReview, _ReviewRowCard
from app.views.imports.step_summary import StepSummary
from app.views.imports.step_upload import (
    DragDropZone,
    StepUpload,
    _friendly_upload_error_message,
)
from app.views.imports.wizard_dialog import ImportWizardDialog
from app.views.imports.wizard_state import ImportWizardController


def test_step_mapping_builds_field_to_header_mapping(qapp) -> None:
    controller = ImportWizardController()
    controller.update_state(
        status="mapping",
        detected_entity="client",
        headers=["Nom", "Telephone"],
        preview_rows=[{"Nom": "Doe", "Telephone": "0555123456"}],
    )
    step = StepMapping(controller)
    step._refresh()

    combo0 = step.map_table.cellWidget(0, 2)
    combo1 = step.map_table.cellWidget(1, 2)
    assert combo0 is not None
    assert combo1 is not None
    combo0.setCurrentIndex(1)  # family_name
    combo1.setCurrentIndex(2)  # phone

    step._validate_and_next()
    assert controller.state.column_mapping == {
        "family_name": "Nom",
        "phone": "Telephone",
    }
    assert controller.state.status == "execute_ready"


def test_step_mapping_blocks_duplicate_field_assignments(qapp) -> None:
    controller = ImportWizardController()
    controller.update_state(
        status="mapping",
        detected_entity="client",
        headers=["Phone 1", "Phone 2"],
        preview_rows=[{"Phone 1": "0555000001", "Phone 2": "0555000002"}],
    )
    step = StepMapping(controller)
    step._refresh()

    combo0 = step.map_table.cellWidget(0, 2)
    combo1 = step.map_table.cellWidget(1, 2)
    assert combo0 is not None
    assert combo1 is not None
    combo0.setCurrentIndex(2)  # phone
    combo1.setCurrentIndex(2)  # phone

    advanced = {"done": False}
    step.nextRequested.connect(lambda: advanced.update(done=True))

    step._validate_and_next()

    assert advanced["done"] is False
    assert controller.state.status == "mapping"
    assert "only be matched once" in step.warning_label.text().lower()


def test_step_mapping_requires_at_least_one_selected_field(qapp) -> None:
    controller = ImportWizardController()
    controller.update_state(
        status="mapping",
        detected_entity="client",
        headers=["Nom", "Telephone"],
        preview_rows=[{"Nom": "Doe", "Telephone": "0555123456"}],
    )
    step = StepMapping(controller)
    step._refresh()

    combo0 = step.map_table.cellWidget(0, 2)
    combo1 = step.map_table.cellWidget(1, 2)
    assert combo0 is not None
    assert combo1 is not None
    combo0.setCurrentIndex(0)
    combo1.setCurrentIndex(0)

    advanced = {"done": False}
    step.nextRequested.connect(lambda: advanced.update(done=True))

    step._validate_and_next()

    assert advanced["done"] is False
    assert controller.state.status == "mapping"
    assert "match at least one column" in step.warning_label.text().lower()


def test_step_mapping_preselects_existing_mapping(qapp) -> None:
    controller = ImportWizardController()
    controller.update_state(
        status="mapping",
        detected_entity="client",
        headers=["Nom", "Telephone"],
        preview_rows=[{"Nom": "Doe", "Telephone": "0555123456"}],
        column_mapping={"family_name": "Nom", "phone": "Telephone"},
    )
    step = StepMapping(controller)
    step._refresh()

    combo0 = step.map_table.cellWidget(0, 2)
    combo1 = step.map_table.cellWidget(1, 2)
    assert combo0 is not None
    assert combo1 is not None
    assert combo0.currentData() == "family_name"
    assert combo1.currentData() == "phone"


def test_step_mapping_requests_preview_before_execute(
    qapp, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller = ImportWizardController()
    controller.update_state(
        session_id="session-123",
        status="mapping",
        detected_entity="client",
        headers=["Nom", "Telephone"],
        preview_rows=[{"Nom": "Doe", "Telephone": "0555123456"}],
    )
    step = StepMapping(controller)
    step._refresh()

    combo0 = step.map_table.cellWidget(0, 2)
    combo1 = step.map_table.cellWidget(1, 2)
    assert combo0 is not None
    assert combo1 is not None
    combo0.setCurrentIndex(1)  # family_name
    combo1.setCurrentIndex(2)  # phone

    captured_payload: dict[str, object] = {}

    def _fake_background(func, on_success, _on_error, *args, **kwargs):
        on_success(func(*args, **kwargs))

    def _fake_api_post(path: str, payload: dict[str, object]):
        captured_payload["path"] = path
        captured_payload["payload"] = dict(payload)
        return {
            "preview_rows": [
                {
                    "row_num": 1,
                    "entity_type": "client",
                    "original": {"Nom": "Doe", "Telephone": "0555123456"},
                    "normalized": {"family_name": "Doe", "phone": "0555123456"},
                    "needs_review": False,
                    "errors": [],
                }
            ],
            "stats": {"valid": 1, "needs_review": 0, "duplicates": 0},
            "entity_counts": {"client": 1},
            "auto_fix_summary": {"phone_format_fixed": 1},
            "attention_summary": {"needs_attention": 0},
            "manual_mapping_required": False,
            "manual_mapping_reasons": [],
            "recoverability_summary": {"auto_recoverable": 1, "review_recoverable": 0},
        }

    monkeypatch.setattr("app.views.imports.step_mapping.run_background_result", _fake_background)
    monkeypatch.setattr("app.services.api_client.api_post", _fake_api_post)

    advanced = {"done": False}
    step.nextRequested.connect(lambda: advanced.update(done=True))

    step._validate_and_next()

    assert captured_payload == {
        "path": "import/preview/",
        "payload": {
            "session_id": "session-123",
            "entity_type": "client",
            "column_mapping": {"family_name": "Nom", "phone": "Telephone"},
        },
    }
    assert controller.state.preview_entity_counts["client"] == 1
    assert controller.state.preview_auto_fix_summary["phone_format_fixed"] == 1
    assert controller.state.status == "execute_ready"
    assert advanced["done"] is True


def test_step_mapping_preserves_hidden_auto_mappings_when_reviewing_visible_columns(qapp) -> None:
    controller = ImportWizardController()
    controller.update_state(
        status="mapping",
        detected_entity="client",
        headers=["Nom", "Telephone", "Statut"],
        detected_columns=[
            {"header": "Nom", "confidence": 0.95},
            {"header": "Telephone", "confidence": 0.95},
            {"header": "Statut", "confidence": 0.20},
        ],
        column_mapping={
            "family_name": "Nom",
            "phone": "Telephone",
            "status": "Statut",
        },
        manual_mapping_required=True,
        manual_mapping_reasons=["Low confidence mapping."],
        preview_rows=[{"Nom": "Doe", "Telephone": "0555123456", "Statut": "active"}],
    )
    step = StepMapping(controller)
    step._refresh()

    assert step.map_table.rowCount() == 1
    combo = step.map_table.cellWidget(0, 2)
    assert combo is not None
    combo.setCurrentIndex(5)  # status

    step._validate_and_next()

    assert controller.state.column_mapping == {
        "family_name": "Nom",
        "phone": "Telephone",
        "status": "Statut",
    }
    assert controller.state.status == "execute_ready"


def test_step_mapping_shows_manual_mapping_warning(qapp) -> None:
    controller = ImportWizardController()
    controller.update_state(
        status="mapping",
        detected_entity="client",
        headers=["A", "B"],
        preview_rows=[{"A": "Ben Ak", "B": "0555123456"}],
        manual_mapping_required=True,
        manual_mapping_reasons=["Low confidence mapping."],
        recoverability_summary={
            "auto_recoverable": 1,
            "review_recoverable": 1,
            "blocking": 1,
        },
    )
    step = StepMapping(controller)
    step._refresh()

    assert "a few columns need your attention" in step.warning_label.text().lower()
    assert "low confidence mapping" in step.warning_label.text().lower()
    assert "blocking" in step.warning_label.text().lower()


def test_step_mapping_blocks_unsupported_child_only_import(qapp) -> None:
    controller = ImportWizardController()
    controller.update_state(
        status="mapping",
        detected_entity="demande",
        import_supported=False,
        blocking_message="Requests-only files aren't supported. Import clients with their requests in the same file.",
        headers=["action", "type", "budget_min"],
        preview_rows=[{"action": "buy", "type": "apartment", "budget_min": "1200000"}],
    )
    step = StepMapping(controller)
    step._refresh()

    assert "different import format" in step.title_label.text().lower()
    assert "requests-only files aren't supported" in step.warning_label.text().lower()
    assert step.next_btn.isEnabled() is False


def test_step_mapping_exposes_offer_fields_for_listing_recovery_union(qapp) -> None:
    controller = ImportWizardController()
    controller.update_state(
        status="mapping",
        detected_entity="listing",
        bundle_mode="single_entity",
        topology_side_hint="listing_side",
        manual_mapping_required=True,
        headers=["owner", "phone", "action", "type", "budget"],
        detected_columns=[
            {"header": "owner", "detected_type": "name", "confidence": 0.95},
            {"header": "phone", "detected_type": "phone", "confidence": 0.95},
            {"header": "action", "detected_type": "action", "confidence": 0.3},
            {"header": "type", "detected_type": "type", "confidence": 0.3},
            {"header": "budget", "detected_type": "price", "confidence": 0.3},
        ],
        preview_rows=[
            {
                "owner": "Meriem",
                "phone": "0555000001",
                "action": "SELL",
                "type": "appartement",
                "budget": "9000000",
            }
        ],
    )
    step = StepMapping(controller)
    step._refresh()

    combo = step.map_table.cellWidget(2, 2)
    assert combo is not None
    values = {combo.itemData(index) for index in range(combo.count())}
    assert "action" in values
    assert "type" in values
    assert "status" in values
    assert "budget" in values
    assert "price_negotiable" in values
    assert controller.state.mapping_palette_mode == "recovery_union"
    assert "properties and offers" in step.info_text.text().lower()


def test_step_mapping_exposes_demande_fields_for_client_recovery_union(qapp) -> None:
    controller = ImportWizardController()
    controller.update_state(
        status="mapping",
        detected_entity="client",
        bundle_mode="single_entity",
        topology_side_hint="client_side",
        manual_mapping_required=True,
        headers=["name", "phone", "action", "locations", "budget_min"],
        detected_columns=[
            {"header": "name", "detected_type": "name", "confidence": 0.95},
            {"header": "phone", "detected_type": "phone", "confidence": 0.95},
            {"header": "action", "detected_type": "action", "confidence": 0.3},
            {"header": "locations", "detected_type": "location", "confidence": 0.3},
            {"header": "budget_min", "detected_type": "price", "confidence": 0.3},
        ],
        preview_rows=[
            {
                "name": "Nadia",
                "phone": "0555000002",
                "action": "BUY",
                "locations": "Hydra",
                "budget_min": "3500000",
            }
        ],
    )
    step = StepMapping(controller)
    step._refresh()

    combo = step.map_table.cellWidget(2, 2)
    assert combo is not None
    values = {combo.itemData(index) for index in range(combo.count())}
    assert "action" in values
    assert "locations" in values
    assert "budget_min" in values
    assert controller.state.mapping_palette_mode == "recovery_union"
    assert "clients and requests" in step.info_text.text().lower()


def test_step_mapping_uses_client_lead_sheet_copy_when_file_model_is_known(qapp) -> None:
    controller = ImportWizardController()
    controller.update_state(
        status="mapping",
        detected_entity="client",
        file_model_hint="client_lead_sheet",
        headers=["Nom complet / Client", "Budget max/Prix (DZD)"],
        preview_rows=[
            {
                "Nom complet / Client": "Nadia",
                "Budget max/Prix (DZD)": "1500000",
            }
        ],
    )
    step = StepMapping(controller)
    step._refresh()

    assert "client leads with property preferences" in step.info_text.text().lower()


def test_step_mapping_uses_first_non_empty_preview_sample(qapp) -> None:
    controller = ImportWizardController()
    controller.update_state(
        status="mapping",
        detected_entity="client",
        headers=["Nom", "Telephone"],
        preview_rows=[
            {
                "original": {"Nom": "", "Telephone": ""},
                "normalized": {"family_name": "", "phone": ""},
            },
            {
                "original": {"Nom": "Doe", "Telephone": "0555123456"},
                "normalized": {"family_name": "Doe", "phone": "0555123456"},
            },
        ],
    )
    step = StepMapping(controller)
    step._refresh()

    assert step.map_table.item(0, 1).text() == "Doe"
    assert step.map_table.item(1, 1).text() == "0555123456"


def test_step_upload_on_error_restores_retry_state(qapp) -> None:
    controller = ImportWizardController()
    step = StepUpload(controller)
    step._on_error("Upload failed")
    assert not step.drop_zone.isHidden()
    assert step.progress_container.isHidden()
    assert controller.state.status == "failed"
    assert controller.state.error_message == "Upload failed"


def test_step_upload_ignores_new_file_while_worker_running(qapp) -> None:
    class _RunningWorker:
        @staticmethod
        def isRunning() -> bool:
            return True

    controller = ImportWizardController()
    step = StepUpload(controller)
    step._worker = _RunningWorker()  # type: ignore[assignment]

    step._handle_file("dummy.csv")
    assert "already uploading" in step.upload_label.text().lower()


def test_step_upload_resets_stale_wizard_state_when_new_file_starts(
    qapp, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _Signal:
        def __init__(self) -> None:
            self.callbacks = []

        def connect(self, _callback) -> None:
            self.callbacks.append(_callback)

    captured: dict[str, object] = {}

    class _FakeWorker:
        def __init__(self, file_path: str, *, entity_hint: str | None = None) -> None:
            captured["file_path"] = file_path
            captured["entity_hint"] = entity_hint
            self.status = _Signal()
            self.error = _Signal()
            self.uploadFinished = _Signal()
            self.finished = _Signal()

        @staticmethod
        def isRunning() -> bool:
            return False

        def deleteLater(self) -> None:
            captured["delete_later_connected"] = True

        def start(self) -> None:
            captured["started"] = True

    monkeypatch.setattr("app.views.imports.step_upload.UploadWorker", _FakeWorker)

    controller = ImportWizardController()
    controller.update_state(
        entity_hint="client",
        session_id="old-session",
        task_id="old-task",
        headers=["Old"],
        detected_columns=[{"header": "Old"}],
        column_mapping={"family_name": "Old"},
        review_count=3,
        review_rows=[{"row": 1, "entity_type": "client"}],
        review_state="normal",
        status="mapping",
    )
    step = StepUpload(controller)

    step._handle_file(r"C:\imports\clients.csv")

    assert captured["file_path"] == r"C:\imports\clients.csv"
    assert captured["entity_hint"] == "client"
    assert captured["started"] is True
    assert controller.state.status == "uploading"
    assert controller.state.session_id == ""
    assert controller.state.task_id == ""
    assert controller.state.headers == []
    assert controller.state.column_mapping == {}
    assert controller.state.review_rows == []
    assert controller.state.review_count == 0
    assert captured.get("delete_later_connected") is None


def test_step_upload_keeps_worker_until_native_thread_finishes(
    qapp, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _Signal:
        def __init__(self) -> None:
            self.callbacks = []

        def connect(self, callback) -> None:
            self.callbacks.append(callback)

        def emit(self, *args) -> None:
            for callback in list(self.callbacks):
                callback(*args)

    class _FakeWorker:
        def __init__(self, _file_path: str, *, entity_hint: str | None = None) -> None:
            self.entity_hint = entity_hint
            self.status = _Signal()
            self.error = _Signal()
            self.uploadFinished = _Signal()
            self.finished = _Signal()
            self.deleted = False

        @staticmethod
        def isRunning() -> bool:
            return False

        def deleteLater(self) -> None:
            self.deleted = True

        def start(self) -> None:
            return None

    monkeypatch.setattr("app.views.imports.step_upload.UploadWorker", _FakeWorker)

    controller = ImportWizardController()
    step = StepUpload(controller)
    step._handle_file(r"C:\imports\clients.csv")
    worker = step._worker
    assert worker is not None

    worker.uploadFinished.emit(
        {
            "session_id": "session-1",
            "task_id": "task-1",
            "file_type": "csv",
            "row_count": 1,
            "detected_entity": "client",
            "detected_columns": [{"header": "Nom", "detected_type": "family_name"}],
            "column_mapping": {"family_name": "Nom"},
            "preview_rows": [{"Nom": "Doe"}],
            "inference_summary": {"final_inference": {"bundle_mode": "single_entity"}},
        }
    )

    assert step._worker is worker
    assert controller.state.status == "mapping"

    worker.finished.emit()

    assert step._worker is None
    assert worker.deleted is True


def test_step_upload_maps_internal_api_errors_to_friendly_copy() -> None:
    message = _friendly_upload_error_message(ApiError(500, "Internal server error"))
    assert "too long to respond" in message.lower()
    assert "internal server error" not in message.lower()


def test_step_upload_maps_retryable_presign_readiness_errors_to_local_service_copy() -> None:
    message = _friendly_upload_error_message(
        ApiError(
            503,
            "storage warming up",
            code="IMPORT_STORAGE_NOT_READY",
            payload={"retryable": True, "retry_after_ms": 1500},
        )
    )
    assert "starting up" in message.lower() or "local import service" in message.lower()


def test_step_upload_maps_tls_handshake_timeout_to_local_secure_copy() -> None:
    try:
        raise TimeoutError("_ssl.c:1063: The handshake operation timed out")
    except TimeoutError as exc:
        err = RuntimeError("API request failed")
        err.__cause__ = exc

    message = _friendly_upload_error_message(err)
    assert "secure import service" in message.lower() or "starting up" in message.lower()


def test_step_upload_uses_bundle_first_copy_for_clients(qapp) -> None:
    controller = ImportWizardController()
    controller.update_state(entity_hint="client")
    step = StepUpload(controller)

    assert "clients and requests" in step.title_label.text().lower()
    assert "combined file" in step.bundle_hint_label.text().lower()


def test_step_upload_uses_bundle_first_copy_for_listings(qapp) -> None:
    controller = ImportWizardController()
    controller.update_state(entity_hint="listing")
    step = StepUpload(controller)

    assert "properties and offers" in step.title_label.text().lower()
    assert "combined file" in step.bundle_hint_label.text().lower()


def test_drag_drop_zone_accepts_supported_local_files() -> None:
    files = DragDropZone.supported_drop_files(
        [
            QUrl.fromLocalFile(r"C:\imports\owners_offers.xlsx"),
            QUrl.fromLocalFile(r"C:\imports\notes.txt"),
        ]
    )

    assert files == [
        r"C:\imports\owners_offers.xlsx",
        r"C:\imports\notes.txt",
    ]


def test_drag_drop_zone_ignores_unsupported_files() -> None:
    files = DragDropZone.supported_drop_files(
        [
            QUrl.fromLocalFile(r"C:\imports\owners_offers.pdf"),
            QUrl.fromLocalFile(r"C:\imports\archive.zip"),
        ]
    )

    assert files == []


def test_step_upload_success_keeps_parse_stage_column_mapping(qapp) -> None:
    controller = ImportWizardController()
    step = StepUpload(controller)

    step._on_success(
        {
            "session_id": "session-1",
            "task_id": "task-1",
            "file_type": "csv",
            "row_count": 1,
            "detected_entity": "client",
            "detected_columns": [
                {"header": "Nom", "detected_type": "family_name"},
                {"header": "Telephone", "detected_type": "phone"},
            ],
            "column_mapping": {
                "family_name": "Nom",
                "phone": "Telephone",
            },
            "preview_rows": [{"Nom": "Doe", "Telephone": "0555123456"}],
            "inference_summary": {
                "final_inference": {
                    "bundle_mode": "single_entity",
                    "topology_side_hint": "unknown",
                }
            },
        }
    )

    assert controller.state.column_mapping == {
        "family_name": "Nom",
        "phone": "Telephone",
    }
    assert controller.state.headers == ["Nom", "Telephone"]
    assert controller.state.status == "mapping"


def test_step_upload_success_accepts_compact_final_inference_payload(qapp) -> None:
    controller = ImportWizardController()
    step = StepUpload(controller)

    step._on_success(
        {
            "session_id": "session-2",
            "task_id": "task-2",
            "file_type": "excel",
            "row_count": 2,
            "detected_entity": "client",
            "detected_columns": [
                {"header": "Nom complet / Client", "detected_type": "name"},
                {"header": "Budget max/Prix (DZD)", "detected_type": "price"},
            ],
            "column_mapping": {
                "family_name": "Nom complet / Client",
                "budget_max": "Budget max/Prix (DZD)",
            },
            "price_dialect_summary": {"dominant_dialect": "raw_dzd"},
            "inference_summary": {
                "bundle_mode": "same_side_bundle",
                "topology_side_hint": "client_side",
                "file_model_hint": "client_lead_sheet",
                "dominant_side": "client_side",
                "dominant_side_confidence": 0.98,
                "detected_entity": "client",
            },
        }
    )

    assert controller.state.bundle_mode == "same_side_bundle"
    assert controller.state.topology_side_hint == "client_side"
    assert controller.state.file_model_hint == "client_lead_sheet"
    assert controller.state.dominant_side == "client_side"
    assert controller.state.column_mapping == {
        "family_name": "Nom complet / Client",
        "budget_max": "Budget max/Prix (DZD)",
    }
    assert controller.state.price_dialect_summary == {"dominant_dialect": "raw_dzd"}


def test_step_execution_poll_failure_escalates_to_failed(qapp) -> None:
    controller = ImportWizardController()
    step = StepExecution(controller)
    completed = {"done": False}
    step.finished.connect(lambda: completed.update(done=True))

    for _ in range(4):
        step._on_poll_error("server down")
        assert controller.state.status != "failed"
        assert "waiting for the server" in step.status_label.text().lower()

    step._on_poll_error("server down")
    assert controller.state.status == "failed"
    assert controller.state.error_message == "server down"
    assert completed["done"] is True


def test_step_execution_handles_queued_status(qapp) -> None:
    controller = ImportWizardController()
    step = StepExecution(controller)

    step._on_poll_result(
        {
            "status": "queued",
            "stage": "executing",
            "progress": 0,
            "progress_detail": {"phase": "queued"},
            "execution_profile": "red",
            "queue_name": "imports",
            "queue_position": 2,
            "agency_queue_depth": 2,
            "cancellation_state": "active",
        }
    )

    assert controller.state.status == "queued"
    assert controller.state.queue_position == 2
    assert controller.state.agency_queue_depth == 2
    assert controller.state.execution_profile == "red"
    assert "waiting its turn" in step.status_label.text().lower()
    assert "position 2 of 2" in step.detail_label.text().lower()


def test_step_execution_waiting_for_worker_exposes_escape_actions(qapp) -> None:
    controller = ImportWizardController()
    step = StepExecution(controller)
    closed = {"done": False}
    step.closeRequested.connect(lambda: closed.update(done=True))

    step._on_poll_result(
        {
            "status": "running",
            "stage": "executing",
            "progress": 0,
            "progress_detail": {"phase": "queued"},
            "wait_state": "waiting_for_worker",
            "wait_reason": "worker_pickup",
            "wait_seconds": 75,
            "stalled": True,
            "stalled_reason": "worker_not_picked_up",
            "can_cancel": True,
            "can_close": True,
            "cancellation_state": "active",
        }
    )

    assert controller.state.wait_state == "waiting_for_worker"
    assert controller.state.stalled is True
    assert step.cancel_btn.isEnabled() is True
    assert step.retry_btn.isHidden() is False
    assert (
        "starting soon" in step.status_label.text().lower()
        or "taking longer than usual" in step.status_label.text().lower()
    )

    step.close_btn.click()
    assert closed["done"] is True


def test_step_execution_polls_stable_session_id_after_execute(
    qapp, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller = ImportWizardController()
    controller.update_state(
        session_id="session-123",
        detected_entity="client",
        column_mapping={"family_name": "Nom"},
    )
    step = StepExecution(controller)

    monkeypatch.setattr(
        "app.services.api_client.api_post",
        lambda _path, _payload: {
            "session_id": "session-123",
            "task_id": "ephemeral-task-456",
            "poll_after_ms": 250,
        },
    )

    poll_id, poll_after_ms = step._trigger_execution()

    assert poll_id == "session-123"
    assert poll_after_ms == 250


def test_step_execution_uses_dynamic_poll_hint(qapp, monkeypatch: pytest.MonkeyPatch) -> None:
    controller = ImportWizardController()
    step = StepExecution(controller)
    monkeypatch.setattr(step, "_poll_status", lambda _task_id: None)
    step._start_polling("task-123", 1000)

    step._on_poll_result(
        {
            "status": "running",
            "stage": "executing",
            "progress": 10,
            "progress_detail": {"phase": "executing", "rows_total": 250},
            "poll_after_ms": 150,
        }
    )

    assert step._timer is not None
    assert step._timer.interval() == 150
    assert controller.state.status == "running"
    assert controller.state.stage == "executing"
    assert controller.state.progress == 10
    step._stop_polling()
    step.deleteLater()


def test_step_execution_starts_first_poll_immediately(
    qapp, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller = ImportWizardController()
    step = StepExecution(controller)
    polled: list[str] = []

    monkeypatch.setattr(step, "_poll_status", lambda task_id: polled.append(task_id))

    step._start_polling("task-xyz", 1000)

    assert step._timer is not None
    assert polled == ["task-xyz"]
    step._stop_polling()
    step.deleteLater()


def test_step_execution_retries_review_fetch_before_failing(
    qapp, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller = ImportWizardController()
    step = StepExecution(controller)
    requested: list[str] = []

    monkeypatch.setattr(
        "app.views.imports.step_execution.QTimer.singleShot",
        lambda _delay, callback: callback(),
    )
    monkeypatch.setattr(
        step, "_request_review_rows", lambda session_id: requested.append(session_id)
    )

    step._pending_review_session_id = "session-1"
    step._handle_review_fetch_error(RuntimeError("temporary review fetch failure"))

    assert controller.state.status != "failed"
    assert requested == ["session-1"]
    assert "loading the review details" in step.subtitle_label.text().lower()


def test_step_execution_preserves_review_overflow_counts(qapp) -> None:
    controller = ImportWizardController()
    step = StepExecution(controller)

    step._on_review_rows(
        {
            "status": "ready",
            "stage": "review",
            "review_count": 2,
            "review_overflow_count": 3,
            "review_total_count": 5,
            "review_state": "emergency_overflow",
            "overflow_blocking": True,
            "review_disabled": True,
            "review_disabled_reason": "This import produced more unresolved review items than the system can safely process in one job.",
            "review_rows": [
                {"row": 14, "entity_type": "client", "data": {"family_name": "Yacine"}},
                {"row": 15, "entity_type": "client", "data": {"family_name": "Noura"}},
            ],
        }
    )

    assert controller.state.review_count == 2
    assert controller.state.review_overflow_count == 3
    assert controller.state.review_total_count == 5
    assert controller.state.review_state == "emergency_overflow"
    assert controller.state.review_disabled is True


def test_step_execution_falls_back_to_review_filters_mode(qapp) -> None:
    controller = ImportWizardController()
    step = StepExecution(controller)

    step._on_review_rows(
        {
            "status": "ready",
            "stage": "review",
            "review_count": 1,
            "review_total_count": 1,
            "review_filters": {
                "mode": "items",
                "group_key": "group-1",
                "issue_group": "all",
                "search": "",
            },
            "review_rows": [{"row": 14, "entity_type": "client", "data": {"family_name": "Y"}}],
        }
    )

    assert controller.state.review_mode == "items"
    assert controller.state.review_pane_state.mode == "items"


def test_step_execution_uses_top_level_final_counts_when_last_result_is_missing(qapp) -> None:
    controller = ImportWizardController()
    step = StepExecution(controller)

    step._on_poll_result(
        {
            "status": "completed",
            "stage": "done",
            "progress": 100,
            "created_count": 3,
            "updated_count": 1,
            "skipped_count": 2,
            "error_count": 0,
            "result_entity_counts": {"client": 3},
            "progress_detail": {"phase": "done"},
        }
    )

    assert controller.state.status == "completed"
    assert controller.state.progress == 100
    assert controller.state.created_count == 3
    assert controller.state.updated_count == 1
    assert controller.state.skipped_count == 2
    assert controller.state.error_count == 0


def test_step_execution_marks_local_failures_as_terminal_progress(qapp) -> None:
    controller = ImportWizardController()
    step = StepExecution(controller)

    step._on_error("server down")

    assert controller.state.status == "failed"
    assert controller.state.progress == 100
    assert step.progress_bar.value() == 100


def test_import_wizard_dialog_uses_workspace_geometry(qapp) -> None:
    dialog = ImportWizardDialog()

    assert dialog.minimumWidth() == 1100
    assert dialog.minimumHeight() == 760
    assert dialog.width() >= 1100
    assert dialog.height() >= 760
    assert dialog.windowFlags() & Qt.WindowType.WindowMaximizeButtonHint
    assert "Step 1 of 5" in dialog._step_label.text()


def test_step_summary_renders_all_primary_metrics(qapp) -> None:
    controller = ImportWizardController()
    controller.update_state(
        status="completed",
        created_count=50,
        updated_count=2,
        skipped_count=3,
        error_count=0,
        result_entity_counts={"client": 10, "demande": 40},
        result_attention_summary={"needs_attention": 1, "blocking": 1},
    )
    step = StepSummary(controller)
    step.refresh()

    assert step.grid.count() == 5


def test_step_summary_auto_closes_after_clean_success(
    qapp, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller = ImportWizardController()
    controller.update_state(
        status="completed",
        created_count=10,
        updated_count=0,
        skipped_count=0,
        error_count=0,
        result_entity_counts={"client": 10, "demande": 4},
        result_attention_summary={"needs_attention": 0},
    )
    step = StepSummary(controller)
    closed: list[bool] = []
    step.closeRequested.connect(lambda: closed.append(True))
    monkeypatch.setattr(
        "app.views.imports.step_summary.QTimer.singleShot",
        lambda _delay, callback: callback(),
    )

    step.refresh()

    assert closed == [True]


def test_step_review_uses_split_workspace_and_selects_editor(qapp) -> None:
    controller = ImportWizardController()
    controller.update_state(
        detected_entity="client",
        review_rows=[
            {
                "row": 14,
                "entity_type": "client",
                "data": {"family_name": "Yacine", "phone": "0555001001"},
                "normalized_data": {"family_name": "Yacine", "phone": "0555001001"},
                "issue_group": "possible_duplicate",
                "issue_title": "Possible duplicate",
                "issue_summary": "This looks very close to an existing record.",
                "candidate_matches": [
                    {"id": 1, "row_version": 3, "family_name": "Yacine", "phone": "0555001001"}
                ],
            },
            {
                "row": 15,
                "entity_type": "client",
                "data": {"family_name": "Noura", "phone": "0600000004"},
                "normalized_data": {"family_name": "Noura", "phone": "0600000004"},
                "issue_group": "missing_information",
                "issue_title": "Missing information",
                "issue_summary": "A few important details are missing or unclear.",
            },
        ],
        review_count=2,
    )
    step = StepReview(controller)
    step.refresh()

    assert step._splitter.count() == 2
    assert step._review_table.rowCount() == 2

    step._review_table.selectRow(1)
    step._on_table_selection_changed()

    assert step._current_editor is step._row_cards[15]


def test_step_review_applies_structured_conflicts_inline(qapp) -> None:
    controller = ImportWizardController()
    controller.update_state(
        detected_entity="client",
        review_rows=[
            {
                "row": 14,
                "entity_type": "client",
                "data": {"family_name": "Yacine", "phone": "0555001001"},
                "normalized_data": {"family_name": "Yacine", "phone": "0555001001"},
                "issue_group": "possible_duplicate",
                "issue_title": "Possible duplicate",
                "issue_summary": "This looks very close to an existing record.",
            }
        ],
        review_count=1,
    )
    step = StepReview(controller)
    step.refresh()

    step._apply_conflicts(
        [
            {
                "row": 14,
                "conflict_type": "duplicate_phone",
                "field": "phone",
                "existing_id": 2,
                "existing_summary": "Existing Client (0555001001)",
                "suggested_action": "use_existing_record",
            }
        ]
    )

    assert "Existing Client" in step._row_cards[14].error_label.text()
    assert step._review_table.item(0, 4).text() == "Conflict"


def test_step_review_conflicts_map_by_entity_type_for_same_row_bundle_items(qapp) -> None:
    controller = ImportWizardController()
    controller.update_state(
        detected_entity="client",
        review_rows=[
            {
                "item_id": 201,
                "row": 14,
                "entity_type": "demande",
                "data": {"family_name": "Yacine", "action": "buy"},
                "normalized_data": {"family_name": "Yacine", "action": "buy"},
                "issue_group": "parent_match_needed",
                "issue_title": "Parent match needed",
                "issue_summary": "Needs a client match.",
            },
            {
                "item_id": 202,
                "row": 14,
                "entity_type": "client",
                "data": {"family_name": "Yacine", "phone": "0555001001"},
                "normalized_data": {"family_name": "Yacine", "phone": "0555001001"},
                "issue_group": "possible_duplicate",
                "issue_title": "Possible duplicate",
                "issue_summary": "Looks close to an existing client.",
            },
        ],
        review_count=2,
    )
    step = StepReview(controller)
    step.refresh()

    step._apply_conflicts(
        [
            {
                "row": 14,
                "entity_type": "demande",
                "conflict_type": "duplicate_phone",
                "field": "phone",
                "existing_summary": "Existing Client (0555001001)",
                "suggested_action": "use_existing_record",
            }
        ]
    )

    assert "Existing Client" in step._row_cards[201].error_label.text()
    assert step._row_cards[202].error_label.text() == ""


def test_step_review_switches_to_read_only_diagnostic_mode_on_emergency_overflow(qapp) -> None:
    controller = ImportWizardController()
    controller.update_state(
        detected_entity="client",
        review_rows=[
            {
                "row": 14,
                "entity_type": "client",
                "data": {"family_name": "Yacine", "phone": "0555001001"},
                "normalized_data": {"family_name": "Yacine", "phone": "0555001001"},
                "issue_group": "possible_duplicate",
                "issue_title": "Possible duplicate",
                "issue_summary": "This looks very close to an existing record.",
            }
        ],
        review_count=1,
        review_overflow_count=3,
        review_total_count=4,
        review_state="emergency_overflow",
        review_disabled=True,
        review_disabled_reason="This import produced more unresolved review items than the system can safely process in one job.",
    )
    step = StepReview(controller)
    step.refresh()

    assert "safe review capacity" in step.subtitle.text().lower()
    assert "3 additional lines" in step.subtitle.text().lower()
    assert step.submit_btn.isEnabled() is False
    assert "safely process" in step.status_label.text().lower()


def test_step_review_enables_group_apply_when_group_supports_it(qapp) -> None:
    controller = ImportWizardController()
    controller.update_state(
        detected_entity="client",
        review_groups=[
            review_group_from_payload(
                {
                    "group_key": "client:phone:0555001001",
                    "group_kind": "bundle_root",
                    "status": "pending",
                    "issue_group": "possible_duplicate",
                    "issue_title": "Possible duplicate",
                    "issue_summary": "This root needs review.",
                    "entity_type": "client",
                    "topology_side": "client_side",
                    "root_label": "Yacine",
                    "item_count": 2,
                    "pending_item_count": 2,
                    "blocking_item_count": 0,
                    "suggested_group_action": "update_existing",
                    "sample_rows": [1, 2],
                    "apply_to_all_allowed": True,
                    "apply_to_all_count": 2,
                    "consistent_existing_id": 42,
                    "resolution_template": {},
                    "resolved_item_count": 0,
                    "metadata": {},
                }
            )
        ],
        review_rows=[
            {
                "item_id": 101,
                "group_key": "client:phone:0555001001",
                "row": 1,
                "entity_type": "client",
                "data": {"family_name": "Yacine", "phone": "0555001001"},
                "normalized_data": {"family_name": "Yacine", "phone": "0555001001"},
                "issue_group": "possible_duplicate",
                "issue_title": "Possible duplicate",
                "issue_summary": "This looks very close to an existing record.",
                "suggested_action": "update_existing",
                "suggested_existing_id": 42,
                "candidate_matches": [{"id": 42, "row_version": 3}],
            },
            {
                "item_id": 102,
                "group_key": "client:phone:0555001001",
                "row": 2,
                "entity_type": "client",
                "data": {"family_name": "Yacine", "phone": "0555001001"},
                "normalized_data": {"family_name": "Yacine", "phone": "0555001001"},
                "issue_group": "possible_duplicate",
                "issue_title": "Possible duplicate",
                "issue_summary": "This looks very close to an existing record.",
                "suggested_action": "update_existing",
                "suggested_existing_id": 42,
                "candidate_matches": [{"id": 42, "row_version": 3}],
            },
        ],
        review_count=2,
        review_pending_group_count=1,
        review_total_count=2,
    )
    step = StepReview(controller)
    step.refresh()

    assert step._group_action_combo.isEnabled() is True
    assert "compatible lines" in step._group_action_hint.text().lower()
    assert step._group_action_buttons["create_new"].isHidden() is False
    assert step._group_action_buttons["update_existing"].isHidden() is False
    assert step._group_action_buttons["skip"].isHidden() is False

    step._group_action_buttons["create_new"].click()

    assert step._group_action_combo.currentData() == "create_new"
    assert step._group_decisions["client:phone:0555001001"]["action"] == "create_new"


def test_step_review_preserves_group_and_item_drafts_across_group_reload(
    qapp, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller = ImportWizardController()
    controller.update_state(
        session_id="session-1",
        detected_entity="client",
        review_groups=[
            review_group_from_payload(
                {
                    "group_key": "group-1",
                    "group_kind": "bundle_root",
                    "status": "pending",
                    "issue_group": "possible_duplicate",
                    "issue_title": "Possible duplicate",
                    "issue_summary": "Group 1 needs review.",
                    "entity_type": "client",
                    "topology_side": "client_side",
                    "root_label": "Group 1",
                    "item_count": 1,
                    "pending_item_count": 1,
                    "blocking_item_count": 0,
                    "suggested_group_action": "create_new",
                    "sample_rows": [1],
                    "apply_to_all_allowed": True,
                    "apply_to_all_count": 1,
                    "consistent_existing_id": 0,
                    "resolution_template": {},
                    "resolved_item_count": 0,
                    "metadata": {},
                }
            ),
            review_group_from_payload(
                {
                    "group_key": "group-2",
                    "group_kind": "single_row",
                    "status": "pending",
                    "issue_group": "missing_information",
                    "issue_title": "Missing information",
                    "issue_summary": "Group 2 needs review.",
                    "entity_type": "client",
                    "topology_side": "client_side",
                    "root_label": "Group 2",
                    "item_count": 1,
                    "pending_item_count": 1,
                    "blocking_item_count": 0,
                    "suggested_group_action": "review_ambiguous",
                    "sample_rows": [2],
                    "apply_to_all_allowed": False,
                    "apply_to_all_count": 0,
                    "consistent_existing_id": 0,
                    "resolution_template": {},
                    "resolved_item_count": 0,
                    "metadata": {},
                }
            ),
        ],
        review_rows=[
            {
                "item_id": 101,
                "group_key": "group-1",
                "row": 1,
                "entity_type": "client",
                "data": {"family_name": "Alpha", "phone": "0555001001"},
                "normalized_data": {"family_name": "Alpha", "phone": "0555001001"},
                "issue_group": "possible_duplicate",
                "issue_title": "Possible duplicate",
                "issue_summary": "Group 1 needs review.",
            }
        ],
        review_count=2,
        review_pending_group_count=2,
        review_total_count=2,
    )
    step = StepReview(controller)
    step.refresh()

    group_action_index = step._group_action_combo.findData("create_new")
    assert group_action_index >= 0
    step._group_action_combo.setCurrentIndex(group_action_index)
    step._row_cards[101]._field_widgets["family_name"].setText(  # type: ignore[index]
        "Alpha Edited"
    )

    def _fake_background(func, on_success, _on_error, *args, **kwargs):
        on_success(func(*args, **kwargs))

    def _fake_fetch(
        page: int,
        page_size: int,
        issue_group: str,
        search_text: str,
        group_key: str,
    ):
        _ = (page, page_size, issue_group, search_text)
        if group_key == "group-2":
            return {
                "status": "ready",
                "stage": "review",
                "review_count": 2,
                "review_pending_group_count": 2,
                "review_total_count": 2,
                "review_page": {
                    "page": 1,
                    "page_size": 50,
                    "total_items": 2,
                    "total_pages": 1,
                    "has_next": False,
                    "has_prev": False,
                },
                "review_filters": {
                    "group_key": "group-2",
                    "issue_group": None,
                    "search": "",
                },
                "review_groups": [
                    {
                        "group_key": "group-1",
                        "group_kind": "bundle_root",
                        "status": "pending",
                        "issue_group": "possible_duplicate",
                        "issue_title": "Possible duplicate",
                        "issue_summary": "Group 1 needs review.",
                        "entity_type": "client",
                        "topology_side": "client_side",
                        "root_label": "Group 1",
                        "item_count": 1,
                        "pending_item_count": 1,
                        "blocking_item_count": 0,
                        "suggested_group_action": "create_new",
                        "sample_rows": [1],
                        "apply_to_all_allowed": True,
                        "apply_to_all_count": 1,
                        "consistent_existing_id": 0,
                        "resolution_template": {},
                        "resolved_item_count": 0,
                    },
                    {
                        "group_key": "group-2",
                        "group_kind": "single_row",
                        "status": "pending",
                        "issue_group": "missing_information",
                        "issue_title": "Missing information",
                        "issue_summary": "Group 2 needs review.",
                        "entity_type": "client",
                        "topology_side": "client_side",
                        "root_label": "Group 2",
                        "item_count": 1,
                        "pending_item_count": 1,
                        "blocking_item_count": 0,
                        "suggested_group_action": "review_ambiguous",
                        "sample_rows": [2],
                        "apply_to_all_allowed": False,
                        "apply_to_all_count": 0,
                        "consistent_existing_id": 0,
                        "resolution_template": {},
                        "resolved_item_count": 0,
                    },
                ],
                "review_rows": [
                    {
                        "item_id": 202,
                        "group_key": "group-2",
                        "row": 2,
                        "entity_type": "client",
                        "data": {"family_name": "Beta", "phone": "0555001002"},
                        "normalized_data": {"family_name": "Beta", "phone": "0555001002"},
                        "issue_group": "missing_information",
                        "issue_title": "Missing information",
                        "issue_summary": "Group 2 needs review.",
                    }
                ],
            }
        return {
            "status": "ready",
            "stage": "review",
            "review_count": 2,
            "review_pending_group_count": 2,
            "review_total_count": 2,
            "review_page": {
                "page": 1,
                "page_size": 50,
                "total_items": 2,
                "total_pages": 1,
                "has_next": False,
                "has_prev": False,
            },
            "review_filters": {
                "group_key": "group-1",
                "issue_group": None,
                "search": "",
            },
            "review_groups": [
                {
                    "group_key": "group-1",
                    "group_kind": "bundle_root",
                    "status": "pending",
                    "issue_group": "possible_duplicate",
                    "issue_title": "Possible duplicate",
                    "issue_summary": "Group 1 needs review.",
                    "entity_type": "client",
                    "topology_side": "client_side",
                    "root_label": "Group 1",
                    "item_count": 1,
                    "pending_item_count": 1,
                    "blocking_item_count": 0,
                    "suggested_group_action": "create_new",
                    "sample_rows": [1],
                    "apply_to_all_allowed": True,
                    "apply_to_all_count": 1,
                    "consistent_existing_id": 0,
                    "resolution_template": {},
                    "resolved_item_count": 0,
                },
                {
                    "group_key": "group-2",
                    "group_kind": "single_row",
                    "status": "pending",
                    "issue_group": "missing_information",
                    "issue_title": "Missing information",
                    "issue_summary": "Group 2 needs review.",
                    "entity_type": "client",
                    "topology_side": "client_side",
                    "root_label": "Group 2",
                    "item_count": 1,
                    "pending_item_count": 1,
                    "blocking_item_count": 0,
                    "suggested_group_action": "review_ambiguous",
                    "sample_rows": [2],
                    "apply_to_all_allowed": False,
                    "apply_to_all_count": 0,
                    "consistent_existing_id": 0,
                    "resolution_template": {},
                    "resolved_item_count": 0,
                },
            ],
            "review_rows": [
                {
                    "item_id": 101,
                    "group_key": "group-1",
                    "row": 1,
                    "entity_type": "client",
                    "data": {"family_name": "Alpha", "phone": "0555001001"},
                    "normalized_data": {"family_name": "Alpha", "phone": "0555001001"},
                    "issue_group": "possible_duplicate",
                    "issue_title": "Possible duplicate",
                    "issue_summary": "Group 1 needs review.",
                }
            ],
        }

    monkeypatch.setattr("app.views.imports.step_review.run_background_result", _fake_background)
    monkeypatch.setattr(step, "_fetch_review_page", _fake_fetch)

    step._reload_review_page(group_key="group-2")

    assert step._group_decisions["group-1"]["action"] == "create_new"
    assert step._item_drafts[101]["payload"]["family_name"] == "Alpha Edited"

    step._reload_review_page(group_key="group-1")

    assert (
        step._row_cards[101]._field_widgets["family_name"].text()  # type: ignore[union-attr]
        == "Alpha Edited"
    )
    assert step._group_action_combo.currentData() == "create_new"


def test_step_review_updates_review_mode_from_refreshed_payload(qapp) -> None:
    controller = ImportWizardController()
    controller.update_state(
        detected_entity="client",
        review_mode="groups",
        review_groups=[
            review_group_from_payload(
                {
                    "group_key": "group-1",
                    "group_kind": "single_row",
                    "status": "pending",
                    "issue_group": "missing_information",
                    "issue_title": "Missing information",
                    "issue_summary": "Group 1 needs review.",
                    "entity_type": "client",
                    "topology_side": "client_side",
                    "root_label": "Group 1",
                    "item_count": 1,
                    "pending_item_count": 1,
                    "blocking_item_count": 0,
                    "suggested_group_action": "review_ambiguous",
                    "sample_rows": [1],
                    "apply_to_all_allowed": False,
                    "apply_to_all_count": 0,
                    "consistent_existing_id": 0,
                    "resolution_template": {},
                    "resolved_item_count": 0,
                    "metadata": {},
                }
            )
        ],
        review_rows=[
            {
                "item_id": 101,
                "group_key": "group-1",
                "row": 1,
                "entity_type": "client",
                "data": {"family_name": "Alpha"},
                "normalized_data": {"family_name": "Alpha"},
                "issue_group": "missing_information",
                "issue_title": "Missing information",
                "issue_summary": "Group 1 needs review.",
            }
        ],
        review_count=1,
    )
    step = StepReview(controller)

    step._on_review_page_result(
        {
            "status": "ready",
            "stage": "review",
            "review_mode": "items",
            "review_count": 1,
            "review_pending_group_count": 1,
            "review_total_count": 1,
            "review_page": {
                "page": 1,
                "page_size": 50,
                "total_items": 1,
                "total_pages": 1,
                "has_next": False,
                "has_prev": False,
            },
            "review_filters": {
                "mode": "items",
                "group_key": "group-1",
                "issue_group": "all",
                "search": "",
            },
            "review_groups": [
                {
                    "group_key": "group-1",
                    "group_kind": "single_row",
                    "status": "pending",
                    "issue_group": "missing_information",
                    "issue_title": "Missing information",
                    "issue_summary": "Group 1 needs review.",
                    "entity_type": "client",
                    "topology_side": "client_side",
                    "root_label": "Group 1",
                    "item_count": 1,
                    "pending_item_count": 1,
                    "blocking_item_count": 0,
                    "suggested_group_action": "review_ambiguous",
                    "sample_rows": [1],
                    "apply_to_all_allowed": False,
                    "apply_to_all_count": 0,
                    "consistent_existing_id": 0,
                    "resolution_template": {},
                    "resolved_item_count": 0,
                }
            ],
            "review_rows": [
                {
                    "item_id": 101,
                    "group_key": "group-1",
                    "row": 1,
                    "entity_type": "client",
                    "data": {"family_name": "Alpha"},
                    "normalized_data": {"family_name": "Alpha"},
                    "issue_group": "missing_information",
                    "issue_title": "Missing information",
                    "issue_summary": "Group 1 needs review.",
                }
            ],
        }
    )

    assert controller.state.review_mode == "items"
    assert controller.state.review_pane_state.mode == "items"


def test_step_review_submit_includes_hidden_group_draft_choices(
    qapp, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller = ImportWizardController()
    controller.update_state(
        session_id="session-1",
        detected_entity="client",
        review_groups=[
            review_group_from_payload(
                {
                    "group_key": "group-1",
                    "group_kind": "single_row",
                    "status": "pending",
                    "issue_group": "missing_information",
                    "issue_title": "Missing information",
                    "issue_summary": "Group 1 needs review.",
                    "entity_type": "client",
                    "topology_side": "client_side",
                    "root_label": "Group 1",
                    "item_count": 1,
                    "pending_item_count": 1,
                    "blocking_item_count": 0,
                    "suggested_group_action": "create_new",
                    "sample_rows": [1],
                    "apply_to_all_allowed": False,
                    "apply_to_all_count": 0,
                    "consistent_existing_id": 0,
                    "resolution_template": {},
                    "resolved_item_count": 0,
                    "metadata": {},
                }
            ),
            review_group_from_payload(
                {
                    "group_key": "group-2",
                    "group_kind": "single_row",
                    "status": "pending",
                    "issue_group": "missing_information",
                    "issue_title": "Missing information",
                    "issue_summary": "Group 2 needs review.",
                    "entity_type": "client",
                    "topology_side": "client_side",
                    "root_label": "Group 2",
                    "item_count": 1,
                    "pending_item_count": 1,
                    "blocking_item_count": 0,
                    "suggested_group_action": "review_ambiguous",
                    "sample_rows": [2],
                    "apply_to_all_allowed": False,
                    "apply_to_all_count": 0,
                    "consistent_existing_id": 0,
                    "resolution_template": {},
                    "resolved_item_count": 0,
                    "metadata": {},
                }
            ),
        ],
        review_rows=[
            {
                "item_id": 101,
                "group_key": "group-1",
                "row": 1,
                "entity_type": "client",
                "data": {"family_name": "Alpha", "phone": "0555001001"},
                "normalized_data": {"family_name": "Alpha", "phone": "0555001001"},
                "issue_group": "missing_information",
                "issue_title": "Missing information",
                "issue_summary": "Group 1 needs review.",
            }
        ],
        review_count=2,
        review_pending_group_count=2,
        review_total_count=2,
    )
    step = StepReview(controller)
    step.refresh()

    step._row_cards[101].action_combo.setCurrentIndex(
        step._row_cards[101].action_combo.findData("create")
    )
    step._row_cards[101]._field_widgets["family_name"].setText(  # type: ignore[index]
        "Alpha Edited"
    )

    def _fake_background(func, on_success, _on_error, *args, **kwargs):
        on_success(func(*args, **kwargs))

    def _fake_fetch(
        _page: int,
        _page_size: int,
        _issue_group: str,
        _search: str,
        _group_key: str,
    ):
        return {
            "status": "ready",
            "stage": "review",
            "review_count": 2,
            "review_pending_group_count": 2,
            "review_total_count": 2,
            "review_page": {
                "page": 1,
                "page_size": 50,
                "total_items": 2,
                "total_pages": 1,
                "has_next": False,
                "has_prev": False,
            },
            "review_filters": {
                "group_key": "group-2",
                "issue_group": None,
                "search": "",
            },
            "review_groups": [
                {
                    "group_key": "group-1",
                    "group_kind": "single_row",
                    "status": "pending",
                    "issue_group": "missing_information",
                    "issue_title": "Missing information",
                    "issue_summary": "Group 1 needs review.",
                    "entity_type": "client",
                    "topology_side": "client_side",
                    "root_label": "Group 1",
                    "item_count": 1,
                    "pending_item_count": 1,
                    "blocking_item_count": 0,
                    "suggested_group_action": "create_new",
                    "sample_rows": [1],
                    "apply_to_all_allowed": False,
                    "apply_to_all_count": 0,
                    "consistent_existing_id": 0,
                    "resolution_template": {},
                    "resolved_item_count": 0,
                },
                {
                    "group_key": "group-2",
                    "group_kind": "single_row",
                    "status": "pending",
                    "issue_group": "missing_information",
                    "issue_title": "Missing information",
                    "issue_summary": "Group 2 needs review.",
                    "entity_type": "client",
                    "topology_side": "client_side",
                    "root_label": "Group 2",
                    "item_count": 1,
                    "pending_item_count": 1,
                    "blocking_item_count": 0,
                    "suggested_group_action": "review_ambiguous",
                    "sample_rows": [2],
                    "apply_to_all_allowed": False,
                    "apply_to_all_count": 0,
                    "consistent_existing_id": 0,
                    "resolution_template": {},
                    "resolved_item_count": 0,
                },
            ],
            "review_rows": [
                {
                    "item_id": 202,
                    "group_key": "group-2",
                    "row": 2,
                    "entity_type": "client",
                    "data": {"family_name": "Beta", "phone": "0555001002"},
                    "normalized_data": {"family_name": "Beta", "phone": "0555001002"},
                    "issue_group": "missing_information",
                    "issue_title": "Missing information",
                    "issue_summary": "Group 2 needs review.",
                }
            ],
        }

    monkeypatch.setattr("app.views.imports.step_review.run_background_result", _fake_background)
    monkeypatch.setattr(step, "_fetch_review_page", _fake_fetch)
    step._reload_review_page(group_key="group-2")

    step._row_cards[202].action_combo.setCurrentIndex(
        step._row_cards[202].action_combo.findData("review")
    )

    captured: dict[str, object] = {}

    def _fake_submit(
        item_decisions: dict[str, dict[str, object]],
        group_decisions: dict[str, dict[str, object]],
        skip_item_ids: list[int],
        bulk_operations: list[dict[str, object]],
    ) -> dict[str, object]:
        captured["item_decisions"] = dict(item_decisions)
        captured["group_decisions"] = dict(group_decisions)
        captured["skip_item_ids"] = list(skip_item_ids)
        captured["bulk_operations"] = list(bulk_operations)
        return {
            "job_status": "completed",
            "stage": "done",
            "result_summary": {
                "created_count": 2,
                "updated_count": 0,
                "skipped_count": 0,
                "error_count": 0,
            },
            "still_review": [],
            "review_groups": [],
            "result_entity_counts": {"client": 2},
            "result_auto_fix_summary": {},
            "result_attention_summary": {},
        }

    monkeypatch.setattr(step, "_perform_submit", _fake_submit)

    step._submit_review()

    item_decisions = dict(captured["item_decisions"])
    assert "101" in item_decisions
    assert item_decisions["101"]["action"] == "create_new"
    assert item_decisions["101"]["corrections"]["family_name"] == "Alpha Edited"
    assert item_decisions["202"]["action"] == "review_ambiguous"


def test_step_review_group_decision_overrides_untouched_row_default_and_keeps_corrections(
    qapp, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller = ImportWizardController()
    controller.update_state(
        session_id="session-1",
        detected_entity="client",
        review_groups=[
            review_group_from_payload(
                {
                    "group_key": "group-1",
                    "group_kind": "bundle_root",
                    "status": "pending",
                    "issue_group": "missing_information",
                    "issue_title": "Missing information",
                    "issue_summary": "Group 1 needs review.",
                    "entity_type": "client",
                    "topology_side": "client_side",
                    "root_label": "Group 1",
                    "item_count": 1,
                    "pending_item_count": 1,
                    "blocking_item_count": 0,
                    "suggested_group_action": "review_ambiguous",
                    "sample_rows": [1],
                    "apply_to_all_allowed": True,
                    "apply_to_all_count": 1,
                    "consistent_existing_id": 0,
                    "resolution_template": {},
                    "resolved_item_count": 0,
                    "metadata": {},
                }
            )
        ],
        review_rows=[
            {
                "item_id": 101,
                "group_key": "group-1",
                "row": 1,
                "entity_type": "client",
                "data": {"family_name": "Alpha123", "phone": "0555001001"},
                "normalized_data": {"family_name": "Alpha123", "phone": "0555001001"},
                "issue_group": "missing_information",
                "issue_title": "Missing information",
                "issue_summary": "Group 1 needs review.",
                "suggested_action": "review_ambiguous",
            }
        ],
        review_count=1,
        review_pending_group_count=1,
        review_total_count=1,
    )
    step = StepReview(controller)
    step.refresh()

    group_action_index = step._group_action_combo.findData("create_new")
    assert group_action_index >= 0
    step._group_action_combo.setCurrentIndex(group_action_index)
    step._row_cards[101]._field_widgets["family_name"].setText(  # type: ignore[index]
        "Alpha Edited"
    )

    monkeypatch.setattr(
        "app.views.imports.step_review.run_background_result",
        lambda func, on_success, _on_error, *args, **kwargs: on_success(func(*args, **kwargs)),
    )

    captured: dict[str, object] = {}

    def _fake_submit(
        item_decisions: dict[str, dict[str, object]],
        group_decisions: dict[str, dict[str, object]],
        skip_item_ids: list[int],
        bulk_operations: list[dict[str, object]],
    ) -> dict[str, object]:
        captured["item_decisions"] = dict(item_decisions)
        captured["group_decisions"] = dict(group_decisions)
        captured["skip_item_ids"] = list(skip_item_ids)
        captured["bulk_operations"] = list(bulk_operations)
        return {
            "job_status": "completed",
            "stage": "done",
            "result_summary": {
                "created_count": 1,
                "updated_count": 0,
                "skipped_count": 0,
                "error_count": 0,
            },
            "still_review": [],
            "review_groups": [],
            "result_entity_counts": {"client": 1},
            "result_auto_fix_summary": {},
            "result_attention_summary": {},
        }

    monkeypatch.setattr(step, "_perform_submit", _fake_submit)

    step._submit_review()

    assert captured["group_decisions"] == {
        "group-1": {
            "action": "create_new",
            "entity_type": "client",
        }
    }
    item_decisions = dict(captured["item_decisions"])
    assert item_decisions["101"] == {
        "corrections": {
            "family_name": "Alpha Edited",
            "phone": "0555001001",
        }
    }
    assert captured["skip_item_ids"] == []
    assert captured["bulk_operations"] == []


def test_review_row_card_update_payload_includes_row_version(qapp) -> None:
    entry = {
        "row": 4,
        "data": {"family_name": "Updated Name", "phone": "0555123456"},
        "candidate_matches": [
            {
                "id": 22,
                "row_version": 7,
                "family_name": "Existing Name",
                "phone": "0555123456",
                "status": "active",
            }
        ],
    }
    card = _ReviewRowCard(entry)
    card.action_combo.setCurrentIndex(card.action_combo.findData("update"))
    card.candidate_combo.setCurrentIndex(1)

    payload, error = card.to_payload()

    assert error is None
    assert payload is not None
    assert payload["existing_id"] == 22
    assert payload["row_version"] == 7


def test_review_row_card_requires_row_version_for_update(qapp) -> None:
    entry = {
        "row": 5,
        "data": {"family_name": "Updated Name", "phone": "0555123456"},
        "candidate_matches": [
            {
                "id": 22,
                "row_version": 0,
                "family_name": "Existing Name",
                "phone": "0555123456",
                "status": "active",
            }
        ],
    }
    card = _ReviewRowCard(entry)
    card.action_combo.setCurrentIndex(card.action_combo.findData("update"))
    card.candidate_combo.setCurrentIndex(1)

    payload, error = card.to_payload()

    assert payload is None
    assert error is not None
    assert "missing version information" in error.lower()


def test_review_row_card_applies_suggested_update_defaults(qapp) -> None:
    entry = {
        "row": 6,
        "data": {"family_name": "Hasna Amrani", "phone": "0555123456"},
        "candidate_matches": [
            {
                "id": 22,
                "row_version": 7,
                "family_name": "Hasna Amrani",
                "phone": "0555123456",
                "status": "active",
                "match_confidence": 0.97,
                "match_reasons": ["same phone", "same name"],
            }
        ],
        "suggested_action": "update",
        "suggested_existing_id": 22,
        "suggested_confidence": 0.97,
        "suggested_reasons": ["same phone", "same name"],
    }
    card = _ReviewRowCard(entry)

    assert card.action_combo.currentData() == "update"
    assert card.candidate_combo.currentData() == 22
    assert "Suggested:" in card.hint_label.text()
    assert "same phone" in card.hint_label.text()


def test_review_row_card_keeps_review_when_match_is_ambiguous(qapp) -> None:
    entry = {
        "row": 7,
        "data": {"family_name": "Imported Name", "phone": "0555123456"},
        "candidate_matches": [
            {
                "id": 22,
                "row_version": 7,
                "family_name": "Existing Name",
                "phone": "0555123456",
                "status": "active",
                "match_confidence": 0.78,
                "match_reasons": ["same phone"],
            }
        ],
        "suggested_action": "review",
        "suggested_existing_id": 22,
        "suggested_confidence": 0.78,
        "suggested_reasons": ["same phone"],
    }
    card = _ReviewRowCard(entry)

    assert card.action_combo.currentData() == "review"
    assert card.candidate_combo.currentData() == 22
    assert "keep this for a quick review" in card.hint_label.text().lower()


def test_review_row_card_respects_suggested_skip_without_candidates(qapp) -> None:
    entry = {
        "row": 71,
        "entity_type": "client",
        "data": {"family_name": "Duplicate Root", "phone": "0555001001"},
        "normalized_data": {"family_name": "Duplicate Root", "phone": "0555001001"},
        "suggested_action": "skip",
        "suggested_reasons": ["Duplicate root key in this file."],
    }
    card = _ReviewRowCard(entry)

    assert card.action_combo.currentData() == "skip"

    payload, error = card.to_payload()

    assert error is None
    assert payload is not None
    assert payload["action"] == "skip"


def test_review_row_card_accepts_explicit_review_action(qapp) -> None:
    entry = {
        "row": 8,
        "data": {"family_name": "Imported Name", "phone": "0555123456"},
        "candidate_matches": [
            {
                "id": 22,
                "row_version": 7,
                "family_name": "Existing Name",
                "phone": "0555123456",
                "status": "active",
                "match_confidence": 0.78,
                "match_reasons": ["same phone"],
            }
        ],
        "suggested_action": "review",
        "suggested_existing_id": 22,
        "suggested_confidence": 0.78,
        "suggested_reasons": ["same phone"],
    }
    card = _ReviewRowCard(entry)
    card.action_combo.setCurrentIndex(card.action_combo.findData("review"))

    payload, error = card.to_payload()

    assert error is None
    assert payload is not None
    assert payload["action"] == "review"


def test_review_row_card_rejects_invalid_numeric_edits(qapp) -> None:
    entry = {
        "row": 72,
        "entity_type": "demande",
        "data": {"beds_min": 2, "budget_min": 1200000},
        "normalized_data": {"beds_min": 2, "budget_min": 1200000},
        "suggested_action": "review",
    }
    card = _ReviewRowCard(entry)
    beds_widget = card._field_widgets["beds_min"]
    assert hasattr(beds_widget, "setText")
    beds_widget.setText("two")  # type: ignore[call-arg]

    payload, error = card.to_payload()

    assert payload is None
    assert error is not None
    assert "numeric fields" in error.lower()


def test_review_row_card_renders_field_diffs_for_selected_candidate(qapp) -> None:
    entry = {
        "row": 9,
        "data": {"family_name": "Hasna Amrani", "phone": "0555123456", "remarks": "from-import"},
        "candidate_matches": [
            {
                "id": 22,
                "row_version": 7,
                "family_name": "Hasna Amrani",
                "phone": "0555123456",
                "status": "active",
                "match_confidence": 0.97,
                "match_reasons": ["same phone", "same name"],
                "field_diffs": [
                    {"field": "remarks", "incoming": "from-import", "existing": "existing"}
                ],
            }
        ],
        "suggested_action": "update",
        "suggested_existing_id": 22,
        "suggested_confidence": 0.97,
        "suggested_reasons": ["same phone", "same name"],
    }
    card = _ReviewRowCard(entry)

    assert "notes" in card.diff_label.text().lower()
    assert "from-import" in card.diff_label.text()
    assert "existing" in card.diff_label.text()


def test_review_row_card_shows_truncated_candidate_scope_hint(qapp) -> None:
    entry = {
        "row": 73,
        "data": {"family_name": "Imported Name", "phone": "0555123456"},
        "candidate_matches": [
            {
                "id": 22,
                "row_version": 7,
                "family_name": "Existing Name",
                "phone": "0555123456",
                "status": "active",
                "match_confidence": 0.78,
                "match_reasons": ["same phone"],
            }
        ],
        "candidate_total_count": 7,
        "candidate_matches_truncated": True,
        "suggested_action": "review",
        "suggested_existing_id": 22,
        "suggested_confidence": 0.78,
        "suggested_reasons": ["same phone"],
    }
    card = _ReviewRowCard(entry)

    assert "showing 1 of 7 matching records" in card.candidate_scope_label.text().lower()


def test_review_row_card_renders_recovery_metadata(qapp) -> None:
    entry = {
        "row": 10,
        "data": {"location": "Ben Ak"},
        "recoverability_class": "review_recoverable",
        "recovered_fields": [
            {
                "field": "wilaya",
                "value": "16",
                "reason": "location Hydra belongs to wilaya Alger",
            }
        ],
        "recovery_candidates": [
            {
                "field": "location",
                "candidate_label": "Ben Aknoun",
                "confidence": 0.78,
            }
        ],
        "blocking_reasons": ["Missing parent anchor"],
    }
    card = _ReviewRowCard(entry)

    labels = [widget.text() for widget in card.findChildren(QLabel) if widget.text()]
    combined = " ".join(labels)
    assert "Recovered fields" in combined
    assert "Ben Aknoun" in combined
    assert "Blocking reasons" in combined


def test_review_row_card_quick_fix_updates_payload(qapp) -> None:
    entry = {
        "row": 11,
        "data": {"location": "Ben Ak", "type": "apartment"},
        "quick_fix_actions": [
            {
                "field": "location",
                "label": "Use Ben Aknoun",
                "candidate_value": "16022",
            }
        ],
    }
    card = _ReviewRowCard(entry)

    card._apply_quick_fix(entry["quick_fix_actions"][0])

    assert '"location": "16022"' in card.editor.toPlainText()


def test_review_row_card_bulk_fix_emits_operation(qapp) -> None:
    entry = {
        "row": 12,
        "data": {"location": "Ben Ak"},
        "bulk_fix_groups": [
            {
                "group_key": "location:ben ak",
                "field": "location",
                "source_value": "Ben Ak",
                "occurrence_count": 3,
                "suggested_candidate_label": "Ben Aknoun",
                "suggested_candidate_value": "16022",
                "target_rows": [12, 13, 14],
            }
        ],
    }
    card = _ReviewRowCard(entry)
    captured: list[dict[str, object]] = []
    card.bulkOperationQueued.connect(lambda payload: captured.append(dict(payload)))
    card._queue_bulk_fix(entry["bulk_fix_groups"][0])

    assert captured == [
        {
            "operation": "replace_value_in_import",
            "field": "location",
            "source_value": "Ben Ak",
            "replacement_value": "16022",
            "target_rows": [12, 13, 14],
            "group_key": "location:ben ak",
        }
    ]
    assert "queued:" in card.error_label.text().lower()
