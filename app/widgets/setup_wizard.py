"""First-launch server setup wizard."""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QLabel,
    QLineEdit,
    QPushButton,
    QWidget,
)

from app.services.api_config import set_verified_api_config
from app.services.onboarding_analytics import record_onboarding_event
from app.services.server_discovery import discover_servers
from app.utils.i18n import tr_factory
from app.utils.qt_async import run_background_result
from app.widgets.setup_wizard_ui import setup_setup_wizard

_TR = tr_factory("SetupWizard")
_VERIFY_FAILURE = _TR(
    "This does not look like an ImmoApp Hub. Ask your manager to open Hub Manager and copy the workstation connection address."
)


class SetupWizardDialog(QDialog):
    """Select discovered server or configure URL manually."""

    _status: QLabel
    _found_label: QLabel
    _technical_label: QLabel
    _troubleshooting_label: QLabel
    _manual_url: QLineEdit
    _local_hub_checkbox: QCheckBox
    _btn_use_found: QPushButton
    _btn_manual: QPushButton
    _btn_retry: QPushButton
    _btn_server_help: QPushButton
    _btn_technical_details: QPushButton

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._found_server: dict[str, Any] | None = None
        self._technical_details_text = ""
        self._technical_details_visible = False
        self._discovery_busy = False
        setup_setup_wizard(self)
        record_onboarding_event(
            "setup_wizard_opened",
            step="setup_wizard",
            outcome="viewed",
        )
        self._retry_discovery()

    def _set_status(self, text: str, *, state: str | None = None) -> None:
        self._status.setText(text)
        self._status.setProperty("immoState", state or "")
        style = self._status.style()
        if style is not None:
            style.unpolish(self._status)
            style.polish(self._status)

    def _set_discovery_busy(self, busy: bool) -> None:
        self._discovery_busy = busy
        self._btn_retry.setEnabled(not busy)
        self._btn_use_found.setEnabled(
            (not busy)
            and self._found_server is not None
            and self._is_connectable(self._found_server)
        )
        self._btn_manual.setEnabled(True)
        self._btn_server_help.setEnabled(True)

    def _set_technical_details(self, text: str) -> None:
        self._technical_details_text = text.strip()
        self._technical_details_visible = False
        self._technical_label.setText("")
        self._btn_technical_details.setVisible(bool(self._technical_details_text))
        self._btn_technical_details.setEnabled(bool(self._technical_details_text))

    def _toggle_technical_details(self) -> None:
        self._technical_details_visible = not self._technical_details_visible
        self._technical_label.setText(
            self._technical_details_text if self._technical_details_visible else ""
        )

    def _is_connectable(self, server: dict[str, Any]) -> bool:
        return (
            bool(server.get("connectable"))
            and str(server.get("proof_scope") or "") != "internal_only"
            and bool(str(server.get("front_door_url") or "").strip())
        )

    def _server_technical_details(self, server: dict[str, Any], url: str) -> str:
        port = str(server.get("front_door_port") or server.get("port") or "").strip()
        details = [
            _TR("Address: {url}").format(url=url or _TR("not provided")),
            _TR("Front-door port: {port}").format(port=port or _TR("not provided")),
            _TR("Source: {source}").format(source=str(server.get("source") or "unknown")),
            _TR("Proof scope: {scope}").format(scope=str(server.get("proof_scope") or "unknown")),
        ]
        hostname = str(server.get("machine_hostname_readonly") or "").strip()
        if hostname:
            details.append(_TR("Hostname: {hostname}").format(hostname=hostname))
        return "\n".join(details)

    def _on_discovery_success(self, servers: list[dict[str, Any]]) -> None:
        self._set_discovery_busy(False)
        if servers:
            self._found_server = next(
                (server for server in servers if self._is_connectable(server)), servers[0]
            )
            hub_name = str(
                self._found_server.get("hub_display_name")
                or self._found_server.get("agency")
                or _TR("Office Hub")
            )
            front_door_url = str(self._found_server.get("front_door_url") or "")
            ip = str(self._found_server.get("ip") or "")
            port = int(self._found_server.get("port") or 8000)
            if not front_door_url and ip:
                front_door_url = f"http://{ip}:{port}"
            connectable = self._is_connectable(self._found_server)
            self._set_technical_details(
                self._server_technical_details(self._found_server, front_door_url)
            )
            if connectable:
                self._set_status(_TR("Good news. We found your Hub."), state="success")
                self._found_label.setText(
                    _TR(
                        "{hub_name}\n"
                        "Verified ImmoApp Hub\n"
                        "Ready to connect. Address details are hidden unless you open Technical details."
                    ).format(hub_name=hub_name)
                )
                self._btn_use_found.setEnabled(True)
                self._btn_use_found.setText(_TR("Connect to {hub_name}").format(hub_name=hub_name))
            else:
                self._set_status(
                    _TR("A server was found, but it is not available for workstation setup."),
                    state="error",
                )
                self._found_label.setText(
                    _TR(
                        "{hub_name}\n"
                        "Not available for workstation setup.\n"
                        "Ask your manager for Hub Manager > Connection details."
                    ).format(hub_name=hub_name)
                )
                self._btn_use_found.setEnabled(False)
                self._btn_use_found.setText(_TR("Connect now"))
            record_onboarding_event(
                "setup_discovery_finished",
                step="setup_wizard",
                outcome="found",
            )
            return
        self._found_server = None
        self._set_status(_TR("We could not find a server yet."), state="error")
        self._found_label.setText(_TR("Type the office Hub address below, then continue."))
        self._set_technical_details("")
        self._btn_use_found.setText(_TR("Connect now"))
        self._btn_use_found.setEnabled(False)
        record_onboarding_event(
            "setup_discovery_finished",
            step="setup_wizard",
            outcome="not_found",
        )

    def _on_discovery_error(self, _exc: Exception) -> None:
        self._set_discovery_busy(False)
        self._found_server = None
        self._set_status(_TR("Automatic search is not available right now."), state="error")
        self._found_label.setText(_TR("Type your office Hub address below, then continue."))
        self._set_technical_details("")
        self._btn_use_found.setText(_TR("Connect now"))
        self._btn_use_found.setEnabled(False)
        record_onboarding_event(
            "setup_discovery_finished",
            step="setup_wizard",
            outcome="error",
        )

    def _save_url(self, url: str, *, hub_display_name: str = "", source: str = "manual") -> bool:
        del hub_display_name
        try:
            local_hub_selected = self._local_hub_checkbox.isChecked()
            verified = set_verified_api_config(
                base_url=url,
                allow_local_hub=local_hub_selected,
                connection_source=source,
            )
        except Exception:
            self._set_status(_VERIFY_FAILURE, state="error")
            self._manual_url.setFocus()
            record_onboarding_event(
                "setup_server_address_failed",
                step="setup_wizard",
                outcome="verification_failed",
            )
            return False
        display_name = str(verified.get("hub_display_name") or _TR("Office Hub"))
        self._set_status(
            _TR("{hub_name} saved. You can continue.").format(hub_name=display_name),
            state="success",
        )
        record_onboarding_event(
            "setup_server_address_saved",
            step="setup_wizard",
            outcome="saved",
        )
        return True

    def _retry_discovery(self) -> None:
        if self._discovery_busy:
            return
        self._set_status(_TR("Checking your network..."), state="loading")
        self._found_label.setText(_TR("Looking for your office Hub..."))
        self._set_technical_details("")
        self._set_discovery_busy(True)
        record_onboarding_event(
            "setup_discovery_started",
            step="setup_wizard",
            outcome="started",
        )
        run_background_result(
            lambda: discover_servers(3.0),
            self._on_discovery_success,
            self._on_discovery_error,
        )

    def _connect_found(self) -> None:
        if not self._found_server or not self._is_connectable(self._found_server):
            return
        hub_name = str(
            self._found_server.get("hub_display_name") or self._found_server.get("agency") or ""
        )
        front_door_url = str(self._found_server.get("front_door_url") or "")
        ip = str(self._found_server.get("ip") or "")
        port = int(self._found_server.get("port") or 8000)
        url = front_door_url or f"http://{ip}:{port}"
        if self._save_url(url, hub_display_name=hub_name, source="discovery"):
            record_onboarding_event(
                "setup_finished",
                step="setup_wizard",
                outcome="connected_found",
            )
            self.accept()

    def _connect_manual(self) -> None:
        if self._save_url(self._manual_url.text(), source="manual"):
            record_onboarding_event(
                "setup_finished",
                step="setup_wizard",
                outcome="connected_manual",
            )
            self.accept()

    def _open_server_help(self) -> None:
        self._set_status(
            _TR(
                "Ask your manager to open Hub Manager > Connection details. Use localhost only when this computer is the Hub."
            ),
            state="muted",
        )
        record_onboarding_event(
            "setup_help_opened",
            step="setup_wizard",
            outcome="shown",
        )


def ensure_setup_wizard() -> bool:
    """Run setup wizard when no API base URL is configured."""
    from app.services.api_config import get_api_base_url

    if get_api_base_url():
        return True
    dialog = SetupWizardDialog()
    return int(dialog.exec()) == int(QDialog.DialogCode.Accepted)


__all__ = ["SetupWizardDialog", "ensure_setup_wizard"]
