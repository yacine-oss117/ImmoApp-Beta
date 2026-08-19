"""UI builder for first-launch setup wizard."""

from __future__ import annotations

from typing import Protocol, cast

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from app.utils.i18n import tr_factory

_TR = tr_factory("SetupWizard")


class _SetupWizardAccess(Protocol):
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

    def _connect_found(self) -> None: ...
    def _connect_manual(self) -> None: ...
    def _retry_discovery(self) -> None: ...
    def _open_server_help(self) -> None: ...
    def _toggle_technical_details(self) -> None: ...


def setup_setup_wizard(dialog: QDialog) -> None:
    ui = cast(_SetupWizardAccess, dialog)
    dialog.setWindowTitle(_TR("Let's get started"))
    dialog.setObjectName("immoSetupWizardDialog")
    dialog.setMinimumWidth(520)

    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(16, 16, 16, 16)
    layout.setSpacing(12)

    title = QLabel(_TR("Connect to your office Hub"), dialog)
    title.setObjectName("immoDialogTitle")
    layout.addWidget(title)

    intro = QLabel(
        _TR("We will try to find your office Hub automatically. This takes a few seconds."),
        dialog,
    )
    intro.setWordWrap(True)
    layout.addWidget(intro)

    discovery_title = QLabel(_TR("Find your office Hub"), dialog)
    discovery_title.setObjectName("setupWizardDiscoveryTitle")
    discovery_title.setStyleSheet("font-weight: 700;")
    layout.addWidget(discovery_title)

    ui._status = QLabel(_TR("Checking your network..."), dialog)
    ui._status.setObjectName("setupWizardStatus")
    ui._status.setWordWrap(True)
    layout.addWidget(ui._status)

    ui._found_label = QLabel("", dialog)
    ui._found_label.setObjectName("setupWizardFoundCard")
    ui._found_label.setWordWrap(True)
    ui._found_label.setMinimumHeight(64)
    layout.addWidget(ui._found_label)

    ui._technical_label = QLabel("", dialog)
    ui._technical_label.setObjectName("setupWizardTechnicalDetailsLabel")
    ui._technical_label.setWordWrap(True)
    ui._technical_label.setProperty("immoState", "muted")
    layout.addWidget(ui._technical_label)

    ui._btn_technical_details = QPushButton(_TR("Technical details"), dialog)
    ui._btn_technical_details.setObjectName("setupWizardTechnicalDetailsButton")
    ui._btn_technical_details.setProperty("immoVariant", "ghost")
    ui._btn_technical_details.setVisible(False)
    layout.addWidget(ui._btn_technical_details)

    found_row = QHBoxLayout()
    ui._btn_use_found = QPushButton(_TR("Connect now"), dialog)
    ui._btn_use_found.setObjectName("setupWizardUseFoundButton")
    ui._btn_use_found.setProperty("immoVariant", "primary")
    ui._btn_retry = QPushButton(_TR("Try again"), dialog)
    ui._btn_retry.setObjectName("setupWizardRetryButton")
    ui._btn_retry.setProperty("immoVariant", "ghost")
    found_row.addWidget(ui._btn_use_found)
    found_row.addWidget(ui._btn_retry)
    layout.addLayout(found_row)

    ui._troubleshooting_label = QLabel(
        _TR(
            "Can't find your Hub? Make sure this computer is on the same office Wi-Fi "
            "or Ethernet network. Guest Wi-Fi, client isolation, firewall rules, or a "
            "different VLAN/subnet can block discovery. Do not use backend/internal "
            "ports. Ask your manager for Hub Manager > Connection details."
        ),
        dialog,
    )
    ui._troubleshooting_label.setObjectName("setupWizardTroubleshootingLabel")
    ui._troubleshooting_label.setWordWrap(True)
    ui._troubleshooting_label.setProperty("immoState", "muted")
    layout.addWidget(ui._troubleshooting_label)

    manual_label = QLabel(_TR("If nothing appears, type the office Hub address"), dialog)
    layout.addWidget(manual_label)
    ui._manual_url = QLineEdit(dialog)
    ui._manual_url.setObjectName("setupWizardManualUrlInput")
    ui._manual_url.setPlaceholderText(_TR("http://main-office.local:8000"))
    ui._manual_url.setMinimumHeight(38)
    layout.addWidget(ui._manual_url)
    ui._local_hub_checkbox = QCheckBox(_TR("This computer is the Hub"), dialog)
    ui._local_hub_checkbox.setObjectName("setupWizardLocalHubCheckbox")
    layout.addWidget(ui._local_hub_checkbox)

    row = QHBoxLayout()
    ui._btn_manual = QPushButton(_TR("Use this address"), dialog)
    ui._btn_manual.setObjectName("setupWizardManualConnectButton")
    ui._btn_manual.setProperty("immoVariant", "primary")
    ui._btn_server_help = QPushButton(_TR("Need server help?"), dialog)
    ui._btn_server_help.setObjectName("setupWizardHelpButton")
    row.addWidget(ui._btn_manual)
    row.addWidget(ui._btn_server_help)
    layout.addLayout(row)

    actions = QHBoxLayout()
    btn_skip = QPushButton(_TR("Cancel"), dialog)
    actions.addStretch(1)
    actions.addWidget(btn_skip)
    layout.addLayout(actions)

    ui._btn_use_found.clicked.connect(ui._connect_found)
    ui._btn_manual.clicked.connect(ui._connect_manual)
    ui._btn_retry.clicked.connect(ui._retry_discovery)
    ui._btn_server_help.clicked.connect(ui._open_server_help)
    ui._btn_technical_details.clicked.connect(ui._toggle_technical_details)
    btn_skip.clicked.connect(dialog.reject)


__all__ = ["setup_setup_wizard"]
