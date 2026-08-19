"""UI helpers to trigger diagnostics export/sign/verify flows."""

from __future__ import annotations

from typing import cast
from uuid import uuid4

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QApplication, QMessageBox, QWidget

from app.constants import APP, ORG
from app.services.diagnostics_reporter import DiagnosticsReportResult, send_diagnostics_report
from app.utils.i18n import tr_factory
from app.utils.qt_async import run_background_result

_TR = tr_factory("DiagnosticsActions")
_DEVICE_ID_KEY = "diagnostics/device_id"
_SIGNATURE_KEY_ID_KEY = "diagnostics/signature_key_id"


def _ensure_identity() -> tuple[str, str]:
    settings = QSettings(ORG, APP)
    device_id = str(settings.value(_DEVICE_ID_KEY, "", str) or "").strip()
    if not device_id:
        device_id = f"desktop-{uuid4().hex[:16]}"
        settings.setValue(_DEVICE_ID_KEY, device_id)

    signature_key_id = str(settings.value(_SIGNATURE_KEY_ID_KEY, "", str) or "").strip()
    if not signature_key_id:
        signature_key_id = "desktop-key-v1"
        settings.setValue(_SIGNATURE_KEY_ID_KEY, signature_key_id)

    settings.sync()
    return device_id, signature_key_id


def _restore_cursor() -> None:
    app_instance = QApplication.instance()
    if not isinstance(app_instance, QApplication):
        return
    app = cast(QApplication, app_instance)
    while app.overrideCursor() is not None:
        app.restoreOverrideCursor()


def send_diagnostics_interactive(
    parent: QWidget | None,
    *,
    route_name: str,
    normalized_route: str,
    policy_id: str,
    error_code: str,
) -> None:
    device_id, signature_key_id = _ensure_identity()
    app_instance = QApplication.instance()
    if isinstance(app_instance, QApplication):
        app = cast(QApplication, app_instance)
        app.setOverrideCursor(Qt.CursorShape.WaitCursor)

    def _work() -> DiagnosticsReportResult:
        return send_diagnostics_report(
            route_name=route_name,
            normalized_route=normalized_route,
            policy_id=policy_id,
            error_code=error_code,
            device_id=device_id,
            signature_key_id=signature_key_id,
        )

    def _on_success(result: DiagnosticsReportResult) -> None:
        _restore_cursor()
        if result.valid:
            QMessageBox.information(
                parent,
                _TR("Report Sent"),
                _TR("Thanks! We'll look into this."),
            )
            return

        detail = result.detail
        if result.code == "SIGNING_KEY_NOT_FOUND":
            detail = _TR(
                "This device is not ready to send reports yet. Ask your manager to activate it."
            )
        QMessageBox.warning(
            parent,
            _TR("Report Failed"),
            _TR("We couldn't send your report right now ({code}).\n{detail}").format(
                code=result.code,
                detail=detail,
            ),
        )

    def _on_error(exc: Exception) -> None:
        _restore_cursor()
        QMessageBox.warning(
            parent,
            _TR("Report Failed"),
            _TR("Report failed to send: {error}").format(error=str(exc)),
        )

    run_background_result(_work, _on_success, _on_error)


def show_error_with_diagnostics(
    parent: QWidget | None,
    *,
    title: str,
    message: str,
    route_name: str,
    normalized_route: str,
    policy_id: str,
    error_code: str,
    critical: bool = False,
) -> None:
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setIcon(QMessageBox.Icon.Critical if critical else QMessageBox.Icon.Warning)
    box.setText(message)
    send_button = box.addButton(_TR("Report a Problem"), QMessageBox.ButtonRole.ActionRole)
    box.addButton(QMessageBox.StandardButton.Ok)
    box.exec()
    if box.clickedButton() is send_button:
        send_diagnostics_interactive(
            parent,
            route_name=route_name,
            normalized_route=normalized_route,
            policy_id=policy_id,
            error_code=error_code,
        )


__all__ = ["send_diagnostics_interactive", "show_error_with_diagnostics"]
