"""Time settings dialog UI."""

from __future__ import annotations

import logging

from app.utils.i18n import tr_factory
from app.views.base import (
    APP,
    ORG,
    QApplication,
    QCheckBox,
    QDateTime,
    QDateTimeEdit,
    QDialog,
    QDialogButtonBox,
    QFont,
    QFormLayout,
    QHBoxLayout,
    QPushButton,
    QSettings,
    Qt,
    QVBoxLayout,
    QWidget,
    SearchableComboBox,
)
from app.widgets.diagnostics_actions import send_diagnostics_interactive

logger = logging.getLogger(__name__)
_TR = tr_factory("TimeSettingsDialog")
try:
    import zoneinfo

    _ZONES = sorted(zoneinfo.available_timezones())
except ImportError:
    logger.warning("Zoneinfo unavailable", exc_info=True)
    _ZONES = []


class TimeSettingsDialog(QDialog):
    """Dialog for configuring time and timezone settings."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # Enforce a sane font early to avoid point-size warnings from child widgets
        f = QFont(QApplication.font())
        if f.pointSize() <= 0:
            f.setPointSize(10)
        QApplication.setFont(f)
        self.setFont(f)
        self.setWindowTitle(_TR("Date & Time"))
        self.setModal(True)
        # Guard against -1 point size warnings by enforcing a sane dialog font
        f = QFont(QApplication.font())
        if f.pointSize() <= 0:
            f.setPointSize(10)
        self.setFont(f)

        s = QSettings(ORG, APP)
        use_ntp = s.value("time/use_ntp", True, bool)
        use_ntp_local = s.value("time/use_ntp_local", True, bool)
        auto_tz = s.value("time/auto_detect_tz", True, bool)
        force_manual_tz = s.value("time/force_manual_tz", False, bool)
        manual_tz = str(s.value("time/manual_tz", "", str) or "")
        manual_clock_enabled = s.value("time/manual_clock_enabled", False, bool)
        offline_mode = s.value("time/offline_mode", False, bool)

        root = QVBoxLayout(self)

        # --- Time source ---
        grp_time = QVBoxLayout()
        self.chk_ntp = QCheckBox(_TR("Use network time (NTP)"))
        self.chk_ntp.setChecked(bool(use_ntp))
        self.chk_ntp.setAccessibleName(_TR("Use network time (NTP)"))
        self.chk_ntp_local = QCheckBox(_TR("Allow local reseed when NTP unavailable"))
        self.chk_ntp_local.setChecked(bool(use_ntp_local))
        self.chk_ntp_local.setAccessibleName(_TR("Allow local NTP reseed"))
        self.chk_offline = QCheckBox(_TR("Offline mode (skip network time and TZ)"))
        self.chk_offline.setChecked(bool(offline_mode))
        self.chk_offline.setAccessibleName(_TR("Offline mode"))
        grp_time.addWidget(self.chk_ntp)
        grp_time.addWidget(self.chk_ntp_local)
        grp_time.addWidget(self.chk_offline)
        root.addLayout(grp_time)

        # --- Timezone ---
        grp_tz = QFormLayout()
        self.chk_auto_tz = QCheckBox(_TR("Auto-detect timezone"))
        self.chk_auto_tz.setChecked(bool(auto_tz))
        self.chk_auto_tz.setAccessibleName(_TR("Auto-detect timezone"))
        self.chk_force_manual_tz = QCheckBox(_TR("Use manual TZ (override)"))
        self.chk_force_manual_tz.setChecked(bool(force_manual_tz))
        self.chk_force_manual_tz.setAccessibleName(_TR("Use manual timezone"))

        # Use SearchableComboBox for timezone - shows dropdown, case-insensitive search
        self.ed_manual_tz = SearchableComboBox()
        self.ed_manual_tz.setEditable(True)
        self.ed_manual_tz.setAccessibleName(_TR("Manual timezone"))
        self.ed_manual_tz.setAccessibleDescription(_TR("Manual IANA timezone entry."))
        if _ZONES:
            self.ed_manual_tz.addItems(_ZONES)
        # Set current value if exists
        if manual_tz:
            idx = self.ed_manual_tz.findText(manual_tz, Qt.MatchFlag.MatchFixedString)
            if idx >= 0:
                self.ed_manual_tz.setCurrentIndex(idx)
            else:
                self.ed_manual_tz.setEditText(manual_tz)

        grp_tz.addRow(self.chk_auto_tz)
        grp_tz.addRow(self.chk_force_manual_tz)
        grp_tz.addRow(_TR("Manual IANA TZ:"), self.ed_manual_tz)
        root.addLayout(grp_tz)

        # --- Manual clock ---
        grp_clock = QFormLayout()
        self.chk_manual_clock = QCheckBox(_TR("Enable manual clock fallback"))
        self.chk_manual_clock.setChecked(bool(manual_clock_enabled))
        self.chk_manual_clock.setAccessibleName(_TR("Enable manual clock"))
        grp_clock.addRow(self.chk_manual_clock)

        row_clock = QHBoxLayout()
        self.dt_manual = QDateTimeEdit(QDateTime.currentDateTime())
        self.dt_manual.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        self.dt_manual.setCalendarPopup(True)
        self.dt_manual.setAccessibleName(_TR("Manual date and time"))
        self.dt_manual.setAccessibleDescription(_TR("Manual date/time override value."))
        btn_set_clock = QPushButton(_TR("Set manual clock"))
        btn_set_clock.setAccessibleName(_TR("Set manual clock"))
        btn_clear_clock = QPushButton(_TR("Clear manual clock"))
        btn_clear_clock.setAccessibleName(_TR("Clear manual clock"))
        row_clock.addWidget(self.dt_manual)
        row_clock.addWidget(btn_set_clock)
        row_clock.addWidget(btn_clear_clock)
        grp_clock.addRow(_TR("Manual date and time:"), row_clock)
        root.addLayout(grp_clock)

        # Buttons
        diagnostics_btn = QPushButton(_TR("Report a Problem"))
        diagnostics_btn.setAccessibleName(_TR("Report a problem"))
        diagnostics_btn.clicked.connect(self._send_diagnostics)
        root.addWidget(diagnostics_btn)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        root.addWidget(buttons)

        self.setTabOrder(self.chk_ntp, self.chk_ntp_local)
        self.setTabOrder(self.chk_ntp_local, self.chk_offline)
        self.setTabOrder(self.chk_offline, self.chk_auto_tz)
        self.setTabOrder(self.chk_auto_tz, self.chk_force_manual_tz)
        self.setTabOrder(self.chk_force_manual_tz, self.ed_manual_tz)
        self.setTabOrder(self.ed_manual_tz, self.chk_manual_clock)
        self.setTabOrder(self.chk_manual_clock, self.dt_manual)
        self.setTabOrder(self.dt_manual, btn_set_clock)
        self.setTabOrder(btn_set_clock, btn_clear_clock)
        self.setTabOrder(btn_clear_clock, diagnostics_btn)

        # Wire actions
        from app.utils.time_service import (
            _normalize_iana_id,
            clear_manual_clock,
            set_manual_clock_from_local,
        )

        btn_set_clock.clicked.connect(
            lambda: set_manual_clock_from_local(
                self.dt_manual.dateTime().toString("yyyy-MM-dd HH:mm:ss")
            )
        )
        btn_clear_clock.clicked.connect(clear_manual_clock)
        # Removed blocking resync call - MainWindow already handles async resync

        # Persist on accept
        def on_accept() -> None:
            s = QSettings(ORG, APP)
            raw = self.ed_manual_tz.currentText().strip()
            norm = _normalize_iana_id(raw) or raw
            s.setValue("time/force_manual_tz", bool(self.chk_force_manual_tz.isChecked()))
            s.setValue("time/auto_detect_tz", bool(self.chk_auto_tz.isChecked()))
            s.setValue("time/use_ntp", bool(self.chk_ntp.isChecked()))
            s.setValue("time/use_ntp_local", bool(self.chk_ntp_local.isChecked()))
            s.setValue("time/manual_clock_enabled", bool(self.chk_manual_clock.isChecked()))
            s.setValue("time/offline_mode", bool(self.chk_offline.isChecked()))
            s.setValue("time/manual_tz", norm)
            s.sync()
            try:
                from app.services.offline_state import set_offline_mode

                set_offline_mode(bool(self.chk_offline.isChecked()))
            except RuntimeError:
                logger.warning("Failed to persist offline mode flag", exc_info=True)
            # Attempt immediate TZ refresh if auto-detect is on and offline is off
            try:
                from app.utils.time_service import refresh_auto_tz_if_due

                refresh_auto_tz_if_due(force=True)
            except (RuntimeError, ValueError):
                logger.warning("Failed to refresh timezone", exc_info=True)
            self.accept()

        buttons.accepted.connect(on_accept)
        buttons.rejected.connect(self.reject)

    def _send_diagnostics(self) -> None:
        send_diagnostics_interactive(
            self,
            route_name="desktop.time_settings.dialog",
            normalized_route="/desktop/settings/time",
            policy_id="desktop.settings.time",
            error_code="MANUAL_TIME_SETTINGS_DIAGNOSTICS",
        )
