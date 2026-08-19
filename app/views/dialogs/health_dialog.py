"""Connection status dialog for non-technical users."""

from __future__ import annotations

import logging

from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.services.health_status import fetch_health_snapshot
from app.utils.i18n import tr_factory
from app.utils.time_humanize import humanize_relative
from app.widgets.diagnostics_actions import (
    send_diagnostics_interactive,
    show_error_with_diagnostics,
)

_TR = tr_factory("HealthDialog")
logger = logging.getLogger(__name__)


class HealthDialog(QDialog):
    """Display plain-language connection status."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(_TR("Connection Status"))
        self.setMinimumWidth(520)
        self.setModal(True)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self._server_status = QLabel("")
        self._last_sync = QLabel("")
        self._backup_status = QLabel("")
        self._activity = QLabel("")

        self._server_status.setAccessibleName(_TR("Server status value"))
        self._last_sync.setAccessibleName(_TR("Last sync value"))
        self._backup_status.setAccessibleName(_TR("Backup status value"))
        self._activity.setAccessibleName(_TR("Recent activity value"))

        form.addRow(_TR("Server"), self._server_status)
        form.addRow(_TR("Last sync"), self._last_sync)
        form.addRow(_TR("Backups"), self._backup_status)
        form.addRow(_TR("Recent activity"), self._activity)
        layout.addLayout(form)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        refresh_btn = QPushButton(_TR("Refresh"))
        refresh_btn.clicked.connect(self._refresh)
        refresh_btn.setAccessibleName(_TR("Refresh connection status"))
        report_btn = QPushButton(_TR("Report a Problem"))
        report_btn.clicked.connect(self._send_report)
        report_btn.setAccessibleName(_TR("Report a problem"))
        close_btn = QPushButton(_TR("Close"))
        close_btn.clicked.connect(self.accept)
        close_btn.setAccessibleName(_TR("Close"))
        btn_row.addWidget(refresh_btn)
        btn_row.addWidget(report_btn)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

        self.setTabOrder(refresh_btn, report_btn)
        self.setTabOrder(report_btn, close_btn)
        self._refresh()

    def _refresh(self) -> None:
        try:
            snapshot = fetch_health_snapshot()
        except (OSError, RuntimeError, ValueError) as exc:
            logger.error("Failed to refresh health snapshot", exc_info=True)
            show_error_with_diagnostics(
                self,
                title=_TR("Connection Status"),
                message=_TR("Couldn't load status right now: {error}").format(error=exc),
                route_name="desktop.health.refresh",
                normalized_route="/desktop/settings/connection-status",
                policy_id="desktop.settings.health",
                error_code="HEALTH_REFRESH_FAILED",
            )
            return

        if snapshot.active_connections >= 0:
            self._server_status.setText(_TR("Everything is working"))
        else:
            self._server_status.setText(_TR("Connection issues"))

        last_sync = humanize_relative(snapshot.last_repair)
        self._last_sync.setText(last_sync or _TR("No recent sync information"))

        if snapshot.last_backup_ts:
            self._backup_status.setText(
                _TR("Last backup: {when}").format(when=humanize_relative(snapshot.last_backup_ts))
            )
        else:
            self._backup_status.setText(_TR("No backup information available"))

        if snapshot.audit_actor:
            self._activity.setText(_TR("Updated by {name}").format(name=snapshot.audit_actor))
        else:
            self._activity.setText(_TR("No recent activity details"))

    def _send_report(self) -> None:
        send_diagnostics_interactive(
            self,
            route_name="desktop.health.dialog",
            normalized_route="/desktop/settings/connection-status",
            policy_id="desktop.settings.health",
            error_code="MANUAL_HEALTH_DIAGNOSTICS",
        )
