"""UI builder for agency registration dialog."""

from __future__ import annotations

from typing import Protocol, cast

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.utils.i18n import tr_factory

_TR = tr_factory("RegisterDialog")


class _RegisterDialogAccess(Protocol):
    _stack: QStackedWidget
    _status: QLabel
    _btn_back: QPushButton
    _btn_discard: QPushButton
    _btn_next: QPushButton
    _agency_name: QLineEdit
    _legal_name: QLineEdit
    _registry_number: QLineEdit
    _agency_address: QLineEdit
    _agency_city: QLineEdit
    _agency_postal_code: QLineEdit
    _owner_first_name: QLineEdit
    _owner_last_name: QLineEdit
    _owner_email: QLineEdit
    _owner_phone: QLineEdit
    _terms_accepted: QCheckBox
    _summary: QLabel

    def _go_back(self) -> None: ...
    def _go_next(self) -> None: ...
    def _discard_saved_progress(self) -> None: ...


def _line(parent: QWidget, placeholder: str) -> QLineEdit:
    line = QLineEdit(parent)
    line.setPlaceholderText(placeholder)
    line.setMinimumHeight(38)
    return line


def setup_register_dialog(dialog: QDialog) -> None:
    ui = cast(_RegisterDialogAccess, dialog)
    dialog.setWindowTitle(_TR("Create your agency"))
    dialog.setObjectName("immoRegisterDialog")
    dialog.setMinimumWidth(560)

    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(16, 16, 16, 16)
    layout.setSpacing(10)

    title = QLabel(_TR("Create your agency in 3 easy steps"), dialog)
    title.setObjectName("immoDialogTitle")
    layout.addWidget(title)

    ui._stack = QStackedWidget(dialog)
    layout.addWidget(ui._stack, 1)

    page_one = QWidget(ui._stack)
    page_one_layout = QVBoxLayout(page_one)
    page_one_layout.setSpacing(8)
    page_one_layout.addWidget(QLabel(_TR("Step 1 of 3 - About the agency"), page_one))
    ui._agency_name = _line(page_one, _TR("Agency name"))
    ui._agency_name.setObjectName("registerAgencyNameInput")
    ui._legal_name = _line(page_one, _TR("Legal name"))
    ui._legal_name.setObjectName("registerLegalNameInput")
    ui._registry_number = _line(page_one, _TR("Registry number"))
    ui._registry_number.setObjectName("registerRegistryNumberInput")
    ui._agency_address = _line(page_one, _TR("Address"))
    ui._agency_address.setObjectName("registerAgencyAddressInput")
    ui._agency_city = _line(page_one, _TR("City"))
    ui._agency_city.setObjectName("registerAgencyCityInput")
    ui._agency_postal_code = _line(page_one, _TR("Postal code"))
    ui._agency_postal_code.setObjectName("registerAgencyPostalCodeInput")
    for field in (
        ui._agency_name,
        ui._legal_name,
        ui._registry_number,
        ui._agency_address,
        ui._agency_city,
        ui._agency_postal_code,
    ):
        page_one_layout.addWidget(field)
    page_one_layout.addStretch(1)
    ui._stack.addWidget(page_one)

    page_two = QWidget(ui._stack)
    page_two_layout = QVBoxLayout(page_two)
    page_two_layout.setSpacing(8)
    page_two_layout.addWidget(QLabel(_TR("Step 2 of 3 - About you"), page_two))
    ui._owner_first_name = _line(page_two, _TR("First name"))
    ui._owner_first_name.setObjectName("registerOwnerFirstNameInput")
    ui._owner_last_name = _line(page_two, _TR("Last name"))
    ui._owner_last_name.setObjectName("registerOwnerLastNameInput")
    ui._owner_email = _line(page_two, _TR("Email"))
    ui._owner_email.setObjectName("registerOwnerEmailInput")
    ui._owner_phone = _line(page_two, _TR("Phone with country code (+213...)"))
    ui._owner_phone.setObjectName("registerOwnerPhoneInput")
    ui._terms_accepted = QCheckBox(_TR("I accept the terms"), page_two)
    ui._terms_accepted.setObjectName("registerTermsAcceptedCheckbox")
    for field in (
        ui._owner_first_name,
        ui._owner_last_name,
        ui._owner_email,
        ui._owner_phone,
    ):
        page_two_layout.addWidget(field)
    page_two_layout.addWidget(ui._terms_accepted)
    page_two_layout.addStretch(1)
    ui._stack.addWidget(page_two)

    page_three = QWidget(ui._stack)
    page_three_layout = QVBoxLayout(page_three)
    page_three_layout.setSpacing(8)
    page_three_layout.addWidget(QLabel(_TR("Step 3 of 3 - Confirm"), page_three))
    ui._summary = QLabel("", page_three)
    ui._summary.setWordWrap(True)
    page_three_layout.addWidget(ui._summary)
    page_three_layout.addStretch(1)
    ui._stack.addWidget(page_three)

    ui._status = QLabel("", dialog)
    ui._status.setObjectName("registerStatusLabel")
    ui._status.setWordWrap(True)
    ui._status.setVisible(False)
    layout.addWidget(ui._status)

    actions = QHBoxLayout()
    ui._btn_back = QPushButton(_TR("Back"), dialog)
    ui._btn_back.setObjectName("registerBackButton")
    ui._btn_discard = QPushButton(_TR("Discard saved progress"), dialog)
    ui._btn_discard.setObjectName("registerDiscardButton")
    ui._btn_discard.setProperty("immoVariant", "ghost")
    btn_cancel = QPushButton(_TR("Cancel"), dialog)
    btn_cancel.setObjectName("registerCancelButton")
    ui._btn_next = QPushButton(_TR("Next"), dialog)
    ui._btn_next.setObjectName("registerNextButton")
    ui._btn_next.setProperty("immoVariant", "primary")
    actions.addWidget(ui._btn_back)
    actions.addWidget(ui._btn_discard)
    actions.addStretch(1)
    actions.addWidget(btn_cancel)
    actions.addWidget(ui._btn_next)
    layout.addLayout(actions)

    ui._btn_back.clicked.connect(ui._go_back)
    ui._btn_discard.clicked.connect(ui._discard_saved_progress)
    ui._btn_next.clicked.connect(ui._go_next)
    btn_cancel.clicked.connect(dialog.reject)


__all__ = ["setup_register_dialog"]
