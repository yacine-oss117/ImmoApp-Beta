"""
Dialog and menu actions for the main window.
"""

from __future__ import annotations

import logging
from typing import cast

from PySide6.QtWidgets import QFileDialog, QInputDialog, QMessageBox, QStatusBar, QWidget

from app.core_app.paths import tmp_dir
from app.utils.i18n import tr_factory
from app.views.time_settings_dialog import TimeSettingsDialog
from app.widgets.diagnostics_actions import (
    send_diagnostics_interactive,
    show_error_with_diagnostics,
)

logger = logging.getLogger(__name__)
_TR = tr_factory("MainWindowDialogs")


class MainWindowDialogsMixin:
    """Mixin providing dialog open/close helpers for MainWindow."""

    status_bar: QStatusBar

    def _kickoff_tz_refresh_async(
        self, force: bool = False
    ) -> None:  # pragma: no cover - implemented by MainWindow
        raise NotImplementedError

    def _update_status_bar(self) -> None:  # pragma: no cover - implemented by MainWindow
        raise NotImplementedError

    def _refresh_all_tabs(self) -> None:  # pragma: no cover - implemented by MainWindow
        raise NotImplementedError

    def _parent_widget(self) -> QWidget:
        return cast(QWidget, getattr(self, "_host", self))

    def _open_time_settings(self) -> None:
        dlg = TimeSettingsDialog(self._parent_widget())
        if dlg.exec():
            self._kickoff_tz_refresh_async(force=True)
            self._update_status_bar()

    def _open_simulation(self) -> None:
        from app.views.dialogs.simulation_dialog import SimulationDialog

        dlg = SimulationDialog(self._parent_widget())
        dlg.exec()

    def _open_wa_templates(self) -> None:
        """Open message templates dialog."""
        from app.views.dialogs.wa_templates_dialog import WaTemplatesDialog

        dlg = WaTemplatesDialog(self._parent_widget())
        dlg.exec()

    def _open_agency_settings(self) -> None:
        """Open agency profile dialog."""
        from app.views.dialogs.agency_settings_dialog import AgencySettingsDialog

        dlg = AgencySettingsDialog(self._parent_widget())
        dlg.exec()

    def _open_user_management(self) -> None:
        """Open team members dialog."""
        from app.views.dialogs.user_management_dialog import UserManagementDialog

        dlg = UserManagementDialog(self._parent_widget())
        dlg.exec()

    def _open_security_settings(self) -> None:
        """Open account security dialog if available in this build."""
        try:
            from app.widgets.mfa_settings_dialog import MFASettingsDialog
        except Exception:
            QMessageBox.information(
                self._parent_widget(),
                _TR("Security"),
                _TR(
                    "Security settings will be available after the security UX package is installed."
                ),
            )
            return
        dlg = MFASettingsDialog(self._parent_widget())
        dlg.exec()

    def _open_session_manager(self) -> None:
        """Open device/session manager dialog if available in this build."""
        try:
            from app.widgets.session_manager_dialog import SessionManagerDialog
        except Exception:
            QMessageBox.information(
                self._parent_widget(),
                _TR("Your Devices"),
                _TR(
                    "Device management will be available after the security UX package is installed."
                ),
            )
            return
        dlg = SessionManagerDialog(self._parent_widget())
        dlg.exec()

    def _open_contract_builder(self) -> None:
        """Open contract builder dialog."""
        from app.views.dialogs.contract_builder_dialog import ContractBuilderDialog

        dlg = ContractBuilderDialog(self._parent_widget())
        dlg.exec()

    def _open_communes_manager(self) -> None:
        """Open locations manager dialog."""
        from app.widgets.location_manager_dialog import ManageLocationsDialog

        dlg = ManageLocationsDialog(self._parent_widget())
        dlg.exec()

    def _open_trash_dialog(self) -> None:
        """Open the recently deleted dialog."""
        from app.views.dialogs.trash_dialog import TrashDialog

        dlg = TrashDialog(self._parent_widget())
        dlg.exec()

    def _open_audit_logs(self) -> None:
        """Open activity history viewer."""
        from app.views.dialogs.audit_logs_dialog import AuditLogsDialog

        dlg = AuditLogsDialog(self._parent_widget())
        dlg.exec()

    def _open_audit_settings(self) -> None:
        """Open the audit settings dialog."""
        from app.views.dialogs.audit_settings_dialog import AuditSettingsDialog

        dlg = AuditSettingsDialog(self._parent_widget())
        dlg.exec()

    def _open_health_dialog(self) -> None:
        """Open connection status dialog."""
        from app.views.dialogs.health_dialog import HealthDialog

        dlg = HealthDialog(self._parent_widget())
        dlg.exec()

    def _open_sync_issues(self) -> None:
        """Open offline sync issues dialog."""
        from app.views.dialogs.sync_issues_dialog import SyncIssuesDialog

        dlg = SyncIssuesDialog(self._parent_widget())
        dlg.exec()

    def _open_storage_delete(self) -> None:
        """Delete a storage object by ID (non-media attachments/admin)."""
        storage_id, ok = QInputDialog.getText(
            self._parent_widget(),
            _TR("Delete Storage Object"),
            _TR("Paste storage_id to delete:"),
        )
        if not ok:
            return
        storage_id = str(storage_id or "").strip()
        if not storage_id:
            return

        confirm = QMessageBox.question(
            self._parent_widget(),
            _TR("Confirm Delete"),
            _TR("Soft-delete this storage object? This cannot be undone."),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        from app.services.storage_repository import delete_storage_object

        try:
            deleted_bytes = delete_storage_object(storage_id)
        except Exception as exc:
            show_error_with_diagnostics(
                self._parent_widget(),
                title=_TR("Delete Failed"),
                message=_TR("Delete failed: {error}").format(error=str(exc)),
                route_name="desktop.storage.delete",
                normalized_route="/desktop/tools/storage-delete",
                policy_id="desktop.storage",
                error_code="STORAGE_DELETE_FAILED",
                critical=True,
            )
            return

        QMessageBox.information(
            self._parent_widget(),
            _TR("Deleted"),
            _TR("Storage object marked deleted ({bytes} bytes).").format(bytes=deleted_bytes),
        )

    def _backup_database_manual(self) -> None:
        """Create a manual backup of the active database."""
        QMessageBox.information(
            self._parent_widget(),
            _TR("Backups Managed by Server"),
            _TR("Backups run automatically on the server."),
        )

    def _open_send_diagnostics(self) -> None:
        send_diagnostics_interactive(
            self._parent_widget(),
            route_name="desktop.tools.send_diagnostics",
            normalized_route="/desktop/tools/send-diagnostics",
            policy_id="desktop.manual_diagnostics",
            error_code="MANUAL_REPORT",
        )

    def _open_support_bundle(self) -> None:
        """Export local logs and sanitized runtime metadata for support."""
        default_dir = str(tmp_dir() / "support_bundles")
        output_dir = QFileDialog.getExistingDirectory(
            self._parent_widget(),
            _TR("Export Support Bundle"),
            default_dir,
        )
        if not output_dir:
            return

        try:
            from app.services.support_bundle import create_support_bundle

            bundle_path = create_support_bundle(output_dir=output_dir)
        except Exception as exc:
            logger.exception("Failed to export support bundle")
            QMessageBox.warning(
                self._parent_widget(),
                _TR("Export Support Bundle"),
                _TR("Could not export the support bundle: {error}").format(error=str(exc)),
            )
            return

        QMessageBox.information(
            self._parent_widget(),
            _TR("Export Support Bundle"),
            _TR("Support bundle created:\n{path}").format(path=str(bundle_path)),
        )

    def _open_security_controls(self) -> None:
        from app.views.dialogs.security_controls_dialog import SecurityControlsDialog

        dlg = SecurityControlsDialog(self._parent_widget())
        dlg.exec()

    def _open_welcome_guide(self) -> None:
        """Open the onboarding quick-start guide on demand."""
        try:
            from app.widgets.quick_start_dialog import run_quick_start_flow

            run_quick_start_flow(self._parent_widget(), force=True)
        except Exception:
            logger.exception("Failed to open welcome guide")
            QMessageBox.warning(
                self._parent_widget(),
                _TR("Welcome Guide"),
                _TR("Could not open the welcome guide right now."),
            )
