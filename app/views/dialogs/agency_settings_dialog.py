"""
Agency Profile Dialog - Configure agency branding.

Allows users to:
- Set agency name
- Upload agency logo (for contract watermarks)
- Upload agency signature
- Configure contract serial prefix
"""

import logging
import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QWidget,
)

from app.services.agency_settings_repository import (
    get_agency_logo_path,
    get_agency_name,
    get_agency_signature_path,
    get_contract_serial_prefix,
    set_agency_logo,
    set_agency_name,
    set_agency_setting,
    set_agency_signature,
)
from app.services.onboarding_analytics import (
    get_onboarding_funnel_snapshot,
    is_onboarding_analytics_enabled,
    reset_next_steps_card,
    reset_quick_start_seen,
    set_onboarding_analytics_enabled,
)
from app.services.onboarding_drafts import (
    ACTIVATE_DRAFT_KEY,
    JOIN_TEAM_DRAFT_KEY,
    REGISTER_DRAFT_KEY,
    clear_all_onboarding_drafts,
    get_onboarding_draft_statuses,
    resolve_resume_target,
)
from app.utils.i18n import tr_factory
from app.utils.time_humanize import humanize_relative
from app.views.dialogs.agency_settings_ui import setup_agency_settings_ui
from app.widgets.workspace_dialog import WorkspaceDialogSpec, apply_workspace_dialog

logger = logging.getLogger(__name__)
_TR = tr_factory("AgencySettingsDialog")


class AgencySettingsDialog(QDialog):
    """Dialog for configuring agency profile settings."""

    _name_edit: QLineEdit
    _prefix_edit: QLineEdit
    _logo_preview: QLabel
    _sig_preview: QLabel
    _scroll_area: QScrollArea
    _analytics_opt_in: QCheckBox
    _onboarding_health_summary: QLabel
    _onboarding_funnel_summary: QLabel
    _btn_continue_saved_setup: QPushButton
    _btn_discard_saved_setup: QPushButton
    _status: QLabel

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        setup_agency_settings_ui(self)
        self.setObjectName("agencySettingsDialog")
        apply_workspace_dialog(
            self,
            WorkspaceDialogSpec(
                settings_key="dialogs/agency_settings_geometry",
                default_width=1120,
                default_height=860,
                min_width=860,
                min_height=640,
                allow_maximize=True,
            ),
        )
        self._load_settings()

    def _set_status(self, message: str, *, state: str | None = None) -> None:
        self._status.setVisible(bool(message))
        self._status.setText(message)
        self._status.setProperty("immoState", state or "")
        style = self._status.style()
        if style is not None:
            style.unpolish(self._status)
            style.polish(self._status)

    def _load_settings(self) -> None:
        """Load current settings into the form."""
        self._name_edit.setText(get_agency_name())
        self._prefix_edit.setText(get_contract_serial_prefix())
        self._analytics_opt_in.setChecked(is_onboarding_analytics_enabled())
        self._refresh_onboarding_health()

        # Load logo preview
        logo_path = get_agency_logo_path()
        if logo_path and os.path.exists(logo_path):
            pixmap = QPixmap(logo_path)
            self._logo_preview.setPixmap(
                pixmap.scaled(
                    140,
                    140,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )

        # Load signature preview
        sig_path = get_agency_signature_path()
        if sig_path and os.path.exists(sig_path):
            pixmap = QPixmap(sig_path)
            self._sig_preview.setPixmap(
                pixmap.scaled(
                    190,
                    70,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )

    def _on_upload_logo(self) -> None:
        """Handle logo upload."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            _TR("Select Logo"),
            "",
            _TR("Images (*.png *.jpg *.jpeg *.bmp)"),
        )

        if file_path:
            try:
                dest_path = set_agency_logo(file_path)
                pixmap = QPixmap(dest_path)
                self._logo_preview.setPixmap(
                    pixmap.scaled(
                        140,
                        140,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
                self._set_status(_TR("Logo imported."), state="success")
            except (OSError, RuntimeError, ValueError) as e:
                logger.error("Agency settings action failed", exc_info=True)
                self._set_status(
                    _TR("Import failed: {error}").format(error=e),
                    state="error",
                )

    def _on_remove_logo(self) -> None:
        """Remove the agency logo."""
        set_agency_setting("agency_logo_path", "")
        self._logo_preview.clear()
        self._logo_preview.setText(_TR("No logo"))
        self._set_status(_TR("Logo removed."), state="success")

    def _on_upload_signature(self) -> None:
        """Handle signature upload."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            _TR("Select Signature"),
            "",
            _TR("Images (*.png *.jpg *.jpeg *.bmp)"),
        )

        if file_path:
            try:
                dest_path = set_agency_signature(file_path)
                pixmap = QPixmap(dest_path)
                self._sig_preview.setPixmap(
                    pixmap.scaled(
                        190,
                        70,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
                self._set_status(_TR("Signature imported."), state="success")
            except (OSError, RuntimeError, ValueError) as e:
                logger.error("Agency settings action failed", exc_info=True)
                self._set_status(
                    _TR("Import failed: {error}").format(error=e),
                    state="error",
                )

    def _on_remove_signature(self) -> None:
        """Remove the agency signature."""
        set_agency_setting("agency_signature_path", "")
        self._sig_preview.clear()
        self._sig_preview.setText(_TR("No signature"))
        self._set_status(_TR("Signature removed."), state="success")

    def _on_open_welcome_guide(self) -> None:
        try:
            from app.widgets.quick_start_dialog import run_quick_start_flow

            run_quick_start_flow(self, force=True)
            self._set_status(_TR("Welcome guide opened."), state="success")
        except Exception:
            logger.error("Failed to open welcome guide", exc_info=True)
            self._set_status(
                _TR("Could not open the welcome guide right now."),
                state="error",
            )

    def _on_reset_welcome_guide(self) -> None:
        reset_quick_start_seen()
        reset_next_steps_card()
        self._set_status(
            _TR("Welcome guide and tips reset. They will appear on next launch."),
            state="success",
        )

    def _refresh_onboarding_health(self) -> None:
        statuses = get_onboarding_draft_statuses()

        def _line(label: str, key: str) -> str:
            raw = statuses.get(key, {})
            exists = bool(raw.get("exists"))
            updated_at = str(raw.get("updated_at") or "")
            if not exists:
                return _TR("{label}: No saved progress").format(label=label)
            when = humanize_relative(updated_at) if updated_at else _TR("recently")
            return _TR("{label}: Ready to continue ({when})").format(label=label, when=when)

        self._onboarding_health_summary.setText(
            "\n".join(
                (
                    _line(_TR("Agency setup"), REGISTER_DRAFT_KEY),
                    _line(_TR("Activation"), ACTIVATE_DRAFT_KEY),
                    _line(_TR("Team join"), JOIN_TEAM_DRAFT_KEY),
                )
            )
        )

        target = resolve_resume_target()
        if target == ACTIVATE_DRAFT_KEY:
            self._btn_continue_saved_setup.setText(_TR("Continue activation"))
            self._btn_continue_saved_setup.setEnabled(True)
        elif target == JOIN_TEAM_DRAFT_KEY:
            self._btn_continue_saved_setup.setText(_TR("Continue team join"))
            self._btn_continue_saved_setup.setEnabled(True)
        elif target == REGISTER_DRAFT_KEY:
            self._btn_continue_saved_setup.setText(_TR("Continue agency setup"))
            self._btn_continue_saved_setup.setEnabled(True)
        else:
            self._btn_continue_saved_setup.setText(_TR("No saved setup to continue"))
            self._btn_continue_saved_setup.setEnabled(False)

        any_saved = any(
            bool(statuses.get(key, {}).get("exists"))
            for key in (REGISTER_DRAFT_KEY, ACTIVATE_DRAFT_KEY, JOIN_TEAM_DRAFT_KEY)
        )
        self._btn_discard_saved_setup.setEnabled(any_saved)

        funnel = get_onboarding_funnel_snapshot(lookback_days=7)
        self._onboarding_funnel_summary.setText(
            _TR(
                "Last 7 days: setup {r_start}/{r_done}, activation {a_start}/{a_done}, "
                "team join {j_start}/{j_done}. Drop-offs: {r_drop}/{a_drop}/{j_drop}."
            ).format(
                r_start=funnel.get("register_started", 0),
                r_done=funnel.get("register_completed", 0),
                a_start=funnel.get("activate_started", 0),
                a_done=funnel.get("activate_completed", 0),
                j_start=funnel.get("join_started", 0),
                j_done=funnel.get("join_completed", 0),
                r_drop=funnel.get("register_abandoned", 0),
                a_drop=funnel.get("activate_abandoned", 0),
                j_drop=funnel.get("join_abandoned", 0),
            )
        )

    def _on_continue_saved_setup(self) -> None:
        target = resolve_resume_target()
        if target == REGISTER_DRAFT_KEY:
            from app.widgets.register_dialog import RegisterDialog

            register_dialog = RegisterDialog(self)
            register_dialog.exec()
            self._refresh_onboarding_health()
            return
        if target == ACTIVATE_DRAFT_KEY:
            from app.widgets.activate_dialog import ActivateDialog

            activate_dialog = ActivateDialog(self)
            activate_dialog.exec()
            self._refresh_onboarding_health()
            return
        if target == JOIN_TEAM_DRAFT_KEY:
            from app.widgets.join_team_dialog import JoinTeamDialog

            join_team_dialog = JoinTeamDialog(self)
            join_team_dialog.exec()
            self._refresh_onboarding_health()
            return
        self._set_status(_TR("No saved setup found."), state="muted")
        self._refresh_onboarding_health()

    def _on_discard_saved_setup(self) -> None:
        statuses = get_onboarding_draft_statuses()
        any_saved = any(
            bool(statuses.get(key, {}).get("exists"))
            for key in (REGISTER_DRAFT_KEY, ACTIVATE_DRAFT_KEY, JOIN_TEAM_DRAFT_KEY)
        )
        if not any_saved:
            self._set_status(_TR("No saved setup found."), state="muted")
            self._refresh_onboarding_health()
            return
        confirm = QMessageBox.question(
            self,
            _TR("Discard saved progress"),
            _TR("Remove all saved setup progress on this device?"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        clear_all_onboarding_drafts()
        self._set_status(_TR("Saved setup progress removed."), state="success")
        self._refresh_onboarding_health()

    def _on_save(self) -> None:
        """Save all settings."""
        name = self._name_edit.text().strip()
        prefix = self._prefix_edit.text().strip()

        if not name:
            self._set_status(_TR("Agency name is required."), state="error")
            self._name_edit.setFocus()
            return

        try:
            set_agency_name(name)
            set_onboarding_analytics_enabled(self._analytics_opt_in.isChecked())
            if prefix:
                set_agency_setting("contract_serial_prefix", prefix)
            else:
                set_agency_setting("contract_serial_prefix", "")
        except Exception:
            logger.error("Failed to save agency profile settings", exc_info=True)
            self._set_status(_TR("Could not save settings right now."), state="error")
            return
        self._set_status(_TR("Settings saved."), state="success")
        self.accept()
