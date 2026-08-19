"""UI builder for agency settings dialog."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.utils.i18n import tr_factory

_TR = tr_factory("AgencySettingsDialog")

if TYPE_CHECKING:
    from app.views.dialogs.agency_settings_dialog import AgencySettingsDialog


def setup_agency_settings_ui(dialog: AgencySettingsDialog) -> None:
    """Build UI controls and attach them to the dialog."""
    dialog.setWindowTitle(_TR("Agency Profile"))
    dialog.resize(960, 760)
    dialog.setMinimumSize(680, 520)
    dialog.setModal(True)
    dialog.setObjectName("immoDialog")

    layout = QVBoxLayout(dialog)
    layout.setSpacing(20)

    scroll = QScrollArea(dialog)
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setProperty("immoRole", "editorScroll")
    scroll.setAccessibleName(_TR("Agency settings form"))
    scroll.setAccessibleDescription(_TR("Scrollable agency profile settings form."))
    dialog._scroll_area = scroll
    layout.addWidget(scroll, 1)

    content = QWidget(scroll)
    scroll.setWidget(content)

    content_layout = QVBoxLayout(content)
    content_layout.setSpacing(20)

    info_group = QGroupBox(_TR("Agency Information"))
    info_layout = QFormLayout(info_group)

    dialog._name_edit = QLineEdit(dialog)
    dialog._name_edit.setObjectName("agencySettingsNameInput")
    dialog._name_edit.setPlaceholderText(_TR("Example: Century 21 Algiers"))
    dialog._name_edit.setAccessibleName(_TR("Agency name"))
    dialog._name_edit.setMinimumHeight(38)
    info_layout.addRow(_TR("Agency name:"), dialog._name_edit)

    dialog._prefix_edit = QLineEdit(dialog)
    dialog._prefix_edit.setObjectName("agencySettingsPrefixInput")
    dialog._prefix_edit.setPlaceholderText(_TR("Example: C21"))
    dialog._prefix_edit.setMaximumWidth(100)
    dialog._prefix_edit.setAccessibleName(_TR("Contract prefix"))
    dialog._prefix_edit.setMinimumHeight(38)
    info_layout.addRow(_TR("Contract prefix:"), dialog._prefix_edit)

    content_layout.addWidget(info_group)

    logo_group = QGroupBox(_TR("Agency Logo"))
    logo_layout = QVBoxLayout(logo_group)

    dialog._logo_preview = QLabel(dialog)
    dialog._logo_preview.setFixedSize(150, 150)
    dialog._logo_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
    dialog._logo_preview.setObjectName("agencyAssetPreview")
    dialog._logo_preview.setProperty("previewRole", "logo")
    dialog._logo_preview.setText(_TR("No logo"))
    dialog._logo_preview.setAccessibleName(_TR("Agency logo preview"))
    dialog._logo_preview.setAccessibleDescription(
        _TR("Preview of the agency logo used as a watermark in contracts.")
    )

    logo_btn_layout = QHBoxLayout()

    upload_logo_btn = QPushButton(_TR("Upload Logo"))
    upload_logo_btn.clicked.connect(dialog._on_upload_logo)
    upload_logo_btn.setAccessibleName(_TR("Upload logo"))
    upload_logo_btn.setProperty("immoVariant", "secondary")

    remove_logo_btn = QPushButton(_TR("Remove"))
    remove_logo_btn.clicked.connect(dialog._on_remove_logo)
    remove_logo_btn.setAccessibleName(_TR("Remove logo"))
    remove_logo_btn.setProperty("immoVariant", "ghost")

    logo_btn_layout.addWidget(upload_logo_btn)
    logo_btn_layout.addWidget(remove_logo_btn)
    logo_btn_layout.addStretch()

    logo_layout.addWidget(dialog._logo_preview, alignment=Qt.AlignmentFlag.AlignCenter)
    logo_layout.addLayout(logo_btn_layout)

    content_layout.addWidget(logo_group)

    sig_group = QGroupBox(_TR("Agency Signature"))
    sig_layout = QVBoxLayout(sig_group)

    dialog._sig_preview = QLabel(dialog)
    dialog._sig_preview.setFixedSize(200, 80)
    dialog._sig_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
    dialog._sig_preview.setObjectName("agencyAssetPreview")
    dialog._sig_preview.setProperty("previewRole", "signature")
    dialog._sig_preview.setText(_TR("No signature"))
    dialog._sig_preview.setAccessibleName(_TR("Agency signature preview"))
    dialog._sig_preview.setAccessibleDescription(
        _TR("Preview of the agency signature image used in contracts.")
    )

    sig_btn_layout = QHBoxLayout()

    upload_sig_btn = QPushButton(_TR("Upload Signature"))
    upload_sig_btn.clicked.connect(dialog._on_upload_signature)
    upload_sig_btn.setAccessibleName(_TR("Upload signature"))
    upload_sig_btn.setProperty("immoVariant", "secondary")

    remove_sig_btn = QPushButton(_TR("Remove"))
    remove_sig_btn.clicked.connect(dialog._on_remove_signature)
    remove_sig_btn.setAccessibleName(_TR("Remove signature"))
    remove_sig_btn.setProperty("immoVariant", "ghost")

    sig_btn_layout.addWidget(upload_sig_btn)
    sig_btn_layout.addWidget(remove_sig_btn)
    sig_btn_layout.addStretch()

    sig_layout.addWidget(dialog._sig_preview, alignment=Qt.AlignmentFlag.AlignCenter)
    sig_layout.addLayout(sig_btn_layout)

    content_layout.addWidget(sig_group)

    onboarding_group = QGroupBox(_TR("Onboarding Preferences"))
    onboarding_layout = QVBoxLayout(onboarding_group)

    dialog._analytics_opt_in = QCheckBox(
        _TR("Help improve first setup with anonymous local usage data."),
        onboarding_group,
    )
    dialog._analytics_opt_in.setObjectName("agencySettingsAnalyticsOptIn")
    dialog._analytics_opt_in.setAccessibleName(_TR("Onboarding analytics"))
    onboarding_layout.addWidget(dialog._analytics_opt_in)

    onboarding_hint = QLabel(
        _TR("Only simple step events are saved on this device. No personal data is stored."),
        onboarding_group,
    )
    onboarding_hint.setWordWrap(True)
    onboarding_hint.setProperty("immoState", "muted")
    onboarding_layout.addWidget(onboarding_hint)

    onboarding_btns = QHBoxLayout()
    open_welcome_btn = QPushButton(_TR("Open Welcome Guide"))
    open_welcome_btn.setProperty("immoVariant", "secondary")
    open_welcome_btn.clicked.connect(dialog._on_open_welcome_guide)
    open_welcome_btn.setAccessibleName(_TR("Open welcome guide"))

    reset_welcome_btn = QPushButton(_TR("Reset Welcome Guide"))
    reset_welcome_btn.setProperty("immoVariant", "ghost")
    reset_welcome_btn.clicked.connect(dialog._on_reset_welcome_guide)
    reset_welcome_btn.setAccessibleName(_TR("Reset welcome guide"))

    onboarding_btns.addWidget(open_welcome_btn)
    onboarding_btns.addWidget(reset_welcome_btn)
    onboarding_btns.addStretch()
    onboarding_layout.addLayout(onboarding_btns)

    content_layout.addWidget(onboarding_group)

    health_group = QGroupBox(_TR("Onboarding Progress"))
    health_layout = QVBoxLayout(health_group)

    dialog._onboarding_health_summary = QLabel("", health_group)
    dialog._onboarding_health_summary.setWordWrap(True)
    dialog._onboarding_health_summary.setAccessibleName(_TR("Onboarding progress summary"))
    health_layout.addWidget(dialog._onboarding_health_summary)

    dialog._onboarding_funnel_summary = QLabel("", health_group)
    dialog._onboarding_funnel_summary.setWordWrap(True)
    dialog._onboarding_funnel_summary.setProperty("immoState", "muted")
    dialog._onboarding_funnel_summary.setAccessibleName(_TR("Onboarding 7-day summary"))
    health_layout.addWidget(dialog._onboarding_funnel_summary)

    health_btns = QHBoxLayout()
    dialog._btn_continue_saved_setup = QPushButton(_TR("Continue saved setup"), health_group)
    dialog._btn_continue_saved_setup.setObjectName("agencySettingsContinueSetupButton")
    dialog._btn_continue_saved_setup.setProperty("immoVariant", "secondary")
    dialog._btn_continue_saved_setup.clicked.connect(dialog._on_continue_saved_setup)
    dialog._btn_continue_saved_setup.setAccessibleName(_TR("Continue saved setup"))

    dialog._btn_discard_saved_setup = QPushButton(_TR("Discard saved progress"), health_group)
    dialog._btn_discard_saved_setup.setObjectName("agencySettingsDiscardSetupButton")
    dialog._btn_discard_saved_setup.setProperty("immoVariant", "ghost")
    dialog._btn_discard_saved_setup.clicked.connect(dialog._on_discard_saved_setup)
    dialog._btn_discard_saved_setup.setAccessibleName(_TR("Discard saved progress"))

    refresh_health_btn = QPushButton(_TR("Refresh"), health_group)
    refresh_health_btn.setProperty("immoVariant", "ghost")
    refresh_health_btn.clicked.connect(dialog._refresh_onboarding_health)
    refresh_health_btn.setAccessibleName(_TR("Refresh onboarding progress"))

    health_btns.addWidget(dialog._btn_continue_saved_setup)
    health_btns.addWidget(dialog._btn_discard_saved_setup)
    health_btns.addWidget(refresh_health_btn)
    health_btns.addStretch()
    health_layout.addLayout(health_btns)

    content_layout.addWidget(health_group)

    note = QLabel(
        _TR(
            "The logo appears as a watermark on all generated contracts.\n"
            "Use a PNG image with a transparent background for best results."
        )
    )
    note.setWordWrap(True)
    note.setProperty("immoState", "muted")
    note.setObjectName("agencySettingsNote")
    content_layout.addWidget(note)
    content_layout.addStretch(1)

    dialog._status = QLabel("", dialog)
    dialog._status.setObjectName("agencySettingsStatus")
    dialog._status.setVisible(False)
    dialog._status.setWordWrap(True)
    layout.addWidget(dialog._status)

    btn_layout = QHBoxLayout()

    save_btn = QPushButton(_TR("Save"))
    save_btn.setObjectName("agencySettingsSaveButton")
    save_btn.clicked.connect(dialog._on_save)
    save_btn.setAccessibleName(_TR("Save agency settings"))
    save_btn.setProperty("immoVariant", "primary")

    cancel_btn = QPushButton(_TR("Cancel"))
    cancel_btn.setObjectName("agencySettingsCancelButton")
    cancel_btn.clicked.connect(dialog.reject)
    cancel_btn.setAccessibleName(_TR("Cancel"))
    cancel_btn.setProperty("immoVariant", "ghost")

    btn_layout.addStretch()
    btn_layout.addWidget(save_btn)
    btn_layout.addWidget(cancel_btn)

    layout.addLayout(btn_layout)

    dialog.setTabOrder(dialog._name_edit, dialog._prefix_edit)
    dialog.setTabOrder(dialog._prefix_edit, upload_logo_btn)
    dialog.setTabOrder(upload_logo_btn, remove_logo_btn)
    dialog.setTabOrder(remove_logo_btn, upload_sig_btn)
    dialog.setTabOrder(upload_sig_btn, remove_sig_btn)
    dialog.setTabOrder(remove_sig_btn, save_btn)
    dialog.setTabOrder(save_btn, cancel_btn)
    dialog.setTabOrder(cancel_btn, dialog._analytics_opt_in)
    dialog.setTabOrder(dialog._analytics_opt_in, open_welcome_btn)
    dialog.setTabOrder(open_welcome_btn, reset_welcome_btn)
    dialog.setTabOrder(reset_welcome_btn, dialog._btn_continue_saved_setup)
    dialog.setTabOrder(dialog._btn_continue_saved_setup, dialog._btn_discard_saved_setup)
    dialog.setTabOrder(dialog._btn_discard_saved_setup, refresh_health_btn)
