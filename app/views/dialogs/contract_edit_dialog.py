"""Contract detail edit dialog."""

from __future__ import annotations

from app.constants import BUDGET_RANGE
from app.models import Contract
from app.shared_types import ContractUpdateData
from app.utils.i18n import tr_factory
from app.views.base import (
    QDate,
    QDateEdit,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

_TR = tr_factory("ContractEditDialog")


class ContractEditDialog(QDialog):
    """Edit mutable contract details without bypassing lifecycle status actions."""

    def __init__(self, contract: Contract, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._contract = contract
        self._contract_data: ContractUpdateData | None = None
        self._is_rent_contract = str(contract.contract_type or "").strip().lower() == "rent"

        self.setWindowTitle(_TR("Edit Contract Details"))
        self.setMinimumWidth(560)
        self.setObjectName("contractEditDialog")

        layout = QVBoxLayout(self)

        info = QLabel(
            _TR("Contract #{id} - {status}").format(
                id=int(contract.id),
                status=str(contract.status or "draft").replace("_", " "),
            ),
            self,
        )
        info.setObjectName("contractEditSummaryLabel")
        layout.addWidget(info)

        form = QFormLayout()

        self.amount = QDoubleSpinBox(self)
        self.amount.setObjectName("contractEditAmountInput")
        self.amount.setAccessibleName(_TR("Amount"))
        self.amount.setRange(*BUDGET_RANGE)
        self.amount.setGroupSeparatorShown(True)
        self.amount.setSuffix(_TR(" DA"))
        self.amount.setValue(float(contract.amount or 0))
        self.amount.lineEdit().setObjectName("contractEditAmountInputEdit")
        self.amount.lineEdit().setAccessibleName(_TR("Amount"))
        form.addRow(_TR("Amount:"), self.amount)

        self.deposit = QDoubleSpinBox(self)
        self.deposit.setObjectName("contractEditDepositInput")
        self.deposit.setAccessibleName(_TR("Deposit"))
        self.deposit.setRange(*BUDGET_RANGE)
        self.deposit.setGroupSeparatorShown(True)
        self.deposit.setSuffix(_TR(" DA"))
        self.deposit.setValue(float(contract.deposit or 0))
        self.deposit.lineEdit().setObjectName("contractEditDepositInputEdit")
        self.deposit.lineEdit().setAccessibleName(_TR("Deposit"))
        form.addRow(_TR("Deposit:"), self.deposit)

        self.start_date = QDateEdit(self)
        self.start_date.setObjectName("contractEditStartDateInput")
        self.start_date.setAccessibleName(_TR("Start date"))
        self.start_date.setCalendarPopup(True)
        self.start_date.setDisplayFormat("yyyy-MM-dd")
        self.start_date.setDate(_date_from_iso(contract.start_date))
        self.start_date.lineEdit().setObjectName("contractEditStartDateInputEdit")
        self.start_date.lineEdit().setAccessibleName(_TR("Start date"))
        form.addRow(_TR("Start Date:"), self.start_date)

        self.end_date = QDateEdit(self)
        self.end_date.setObjectName("contractEditEndDateInput")
        self.end_date.setAccessibleName(_TR("End date"))
        self.end_date.setCalendarPopup(True)
        self.end_date.setDisplayFormat("yyyy-MM-dd")
        self.end_date.setDate(
            _date_from_iso(contract.end_date) if self._is_rent_contract else QDate.currentDate()
        )
        self.end_date.lineEdit().setObjectName("contractEditEndDateInputEdit")
        self.end_date.lineEdit().setAccessibleName(_TR("End date"))
        self.end_date_label = QLabel(_TR("End Date:"), self)
        form.addRow(self.end_date_label, self.end_date)
        self.end_date.setEnabled(self._is_rent_contract)
        self.end_date.setVisible(self._is_rent_contract)
        self.end_date_label.setVisible(self._is_rent_contract)

        self.terms = QTextEdit(self)
        self.terms.setObjectName("contractEditTermsInput")
        self.terms.setAccessibleName(_TR("Terms"))
        self.terms.setMinimumHeight(96)
        self.terms.setPlainText(contract.terms or "")
        form.addRow(_TR("Terms:"), self.terms)

        self.notes = QTextEdit(self)
        self.notes.setObjectName("contractEditNotesInput")
        self.notes.setAccessibleName(_TR("Notes"))
        self.notes.setMinimumHeight(84)
        self.notes.setPlainText(contract.notes or "")
        form.addRow(_TR("Notes:"), self.notes)

        layout.addLayout(form)

        buttons = QHBoxLayout()
        cancel_btn = QPushButton(_TR("Cancel"), self)
        cancel_btn.setObjectName("contractEditCancelButton")
        cancel_btn.setAccessibleName(_TR("Cancel"))
        cancel_btn.setProperty("immoVariant", "ghost")
        cancel_btn.clicked.connect(self.reject)

        self.save_btn = QPushButton(_TR("Save Details"), self)
        self.save_btn.setObjectName("contractEditSaveButton")
        self.save_btn.setAccessibleName(_TR("Save contract details"))
        self.save_btn.setProperty("immoVariant", "primary")
        self.save_btn.clicked.connect(self.accept_contract)

        buttons.addStretch()
        buttons.addWidget(cancel_btn)
        buttons.addWidget(self.save_btn)
        layout.addLayout(buttons)

        self.setTabOrder(self.amount, self.deposit)
        self.setTabOrder(self.deposit, self.start_date)
        self.setTabOrder(self.start_date, self.end_date)
        self.setTabOrder(self.end_date, self.terms)
        self.setTabOrder(self.terms, self.notes)
        self.setTabOrder(self.notes, cancel_btn)
        self.setTabOrder(cancel_btn, self.save_btn)

    def accept_contract(self) -> None:
        """Collect update payload including concurrency token."""
        self._contract_data = {
            "row_version": int(self._contract.row_version),
            "amount": float(self.amount.value()),
            "deposit": float(self.deposit.value()),
            "start_date": self.start_date.date().toString("yyyy-MM-dd"),
            "end_date": (
                self.end_date.date().toString("yyyy-MM-dd") if self._is_rent_contract else None
            ),
            "terms": self.terms.toPlainText().strip(),
            "notes": self.notes.toPlainText().strip(),
        }
        self.accept()

    def get_contract_data(self) -> ContractUpdateData | None:
        """Return update data after the dialog is accepted."""
        return self._contract_data


def _date_from_iso(value: str | None) -> QDate:
    text = str(value or "").strip()
    parsed = QDate.fromString(text, "yyyy-MM-dd") if text else QDate()
    return parsed if parsed.isValid() else QDate.currentDate()
