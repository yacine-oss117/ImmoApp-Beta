"""Contract dialog UI."""

from app.constants import BUDGET_RANGE
from app.shared_types import ContractData
from app.utils.i18n import tr_factory
from app.utils.text_safety import set_label_plain_text
from app.views.base import (
    QComboBox,
    QDate,
    QDateEdit,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

_TR = tr_factory("ContractDialog")


class ContractDialog(QDialog):
    """Dialog for creating a contract."""

    def __init__(
        self,
        client_id: int,
        listing_id: int,
        contract_type: str = "buy",
        client_phone: str = "",
        listing_location: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.client_id = client_id
        self.listing_id = listing_id
        self.contract_data: ContractData | None = None

        self.setWindowTitle(
            _TR("Create {type} Contract").format(type=self._contract_type_label(contract_type))
        )
        self.setMinimumWidth(550)
        self.setObjectName("contractDialog")

        layout = QVBoxLayout()

        # Info section - convert int IDs to str for display
        info_layout = QFormLayout()
        client_id_label = QLabel()
        set_label_plain_text(client_id_label, str(client_id))
        info_layout.addRow(QLabel(_TR("<b>Client ID:</b>")), client_id_label)

        client_phone_label = QLabel()
        set_label_plain_text(client_phone_label, client_phone or _TR("N/A"))
        info_layout.addRow(QLabel(_TR("<b>Client Phone:</b>")), client_phone_label)

        listing_id_label = QLabel()
        set_label_plain_text(listing_id_label, str(listing_id))
        info_layout.addRow(QLabel(_TR("<b>Listing ID:</b>")), listing_id_label)

        listing_location_label = QLabel()
        set_label_plain_text(listing_location_label, listing_location or _TR("N/A"))
        info_layout.addRow(QLabel(_TR("<b>Location:</b>")), listing_location_label)

        layout.addLayout(info_layout)

        # Separator
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(separator)

        # Form
        form = QFormLayout()

        # Contract type
        self.contract_type = QComboBox()
        self.contract_type.setObjectName("contractTypeCombo")
        self.contract_type.setAccessibleName(_TR("Contract type"))
        self.contract_type.addItem(_TR("Buy"), "buy")
        self.contract_type.addItem(_TR("Rent"), "rent")
        index = self.contract_type.findData(contract_type)
        if index >= 0:
            self.contract_type.setCurrentIndex(index)
        self.contract_type.currentIndexChanged.connect(self._on_type_changed)
        form.addRow(_TR("Contract Type:"), self.contract_type)

        # Amount
        self.amount = QDoubleSpinBox()
        self.amount.setObjectName("contractAmountInput")
        self.amount.setAccessibleName(_TR("Amount"))
        self.amount.setRange(*BUDGET_RANGE)
        self.amount.setGroupSeparatorShown(True)
        self.amount.setSuffix(_TR(" DA"))
        self.amount.lineEdit().setObjectName("contractAmountInputEdit")
        self.amount.lineEdit().setAccessibleName(_TR("Amount"))
        form.addRow(_TR("Amount:"), self.amount)

        # Deposit
        self.deposit = QDoubleSpinBox()
        self.deposit.setObjectName("contractDepositInput")
        self.deposit.setAccessibleName(_TR("Deposit"))
        self.deposit.setRange(*BUDGET_RANGE)
        self.deposit.setGroupSeparatorShown(True)
        self.deposit.setSuffix(_TR(" DA"))
        self.deposit.lineEdit().setObjectName("contractDepositInputEdit")
        self.deposit.lineEdit().setAccessibleName(_TR("Deposit"))
        form.addRow(_TR("Deposit:"), self.deposit)

        # Start date
        self.start_date = QDateEdit()
        self.start_date.setObjectName("contractStartDateInput")
        self.start_date.setAccessibleName(_TR("Start date"))
        self.start_date.setCalendarPopup(True)
        self.start_date.setDisplayFormat("yyyy-MM-dd")
        self.start_date.setDate(QDate.currentDate())
        self.start_date.lineEdit().setObjectName("contractStartDateInputEdit")
        self.start_date.lineEdit().setAccessibleName(_TR("Start date"))
        form.addRow(_TR("Start Date:"), self.start_date)

        # End date (for rent only)
        self.end_date_label = QLabel(_TR("End Date:"))
        self.end_date = QDateEdit()
        self.end_date.setObjectName("contractEndDateInput")
        self.end_date.setAccessibleName(_TR("End date"))
        self.end_date.setCalendarPopup(True)
        self.end_date.setDisplayFormat("yyyy-MM-dd")
        self.end_date.setDate(QDate.currentDate().addMonths(12))  # Default 1 year
        self.end_date.lineEdit().setObjectName("contractEndDateInputEdit")
        self.end_date.lineEdit().setAccessibleName(_TR("End date"))
        form.addRow(self.end_date_label, self.end_date)

        # Terms
        self.terms = QTextEdit()
        self.terms.setObjectName("contractTermsInput")
        self.terms.setAccessibleName(_TR("Terms"))
        self.terms.setAccessibleDescription(_TR("Contract terms and clauses."))
        self.terms.setPlaceholderText(_TR("Contract terms and conditions..."))
        self.terms.setMinimumHeight(96)
        form.addRow(_TR("Terms:"), self.terms)

        # Notes
        self.notes = QTextEdit()
        self.notes.setObjectName("contractNotesInput")
        self.notes.setAccessibleName(_TR("Notes"))
        self.notes.setAccessibleDescription(_TR("Additional internal notes."))
        self.notes.setPlaceholderText(_TR("Additional notes..."))
        self.notes.setMinimumHeight(84)
        form.addRow(_TR("Notes:"), self.notes)

        layout.addLayout(form)

        # Set initial visibility
        self._on_type_changed(self.contract_type.currentIndex())

        # Buttons
        btn_layout = QHBoxLayout()
        self.save_btn = QPushButton(_TR("Create Contract"))
        self.save_btn.setObjectName("contractCreateButton")
        self.save_btn.clicked.connect(self.accept_contract)
        self.save_btn.setAccessibleName(_TR("Create contract"))
        self.save_btn.setProperty("immoVariant", "primary")

        cancel_btn = QPushButton(_TR("Cancel"))
        cancel_btn.setObjectName("contractCancelButton")
        cancel_btn.clicked.connect(self.reject)
        cancel_btn.setAccessibleName(_TR("Cancel"))
        cancel_btn.setProperty("immoVariant", "ghost")

        btn_layout.addStretch()
        btn_layout.addWidget(cancel_btn)
        btn_layout.addWidget(self.save_btn)

        layout.addLayout(btn_layout)
        self.setLayout(layout)
        self.setTabOrder(self.contract_type, self.amount)
        self.setTabOrder(self.amount, self.deposit)
        self.setTabOrder(self.deposit, self.start_date)
        self.setTabOrder(self.start_date, self.end_date)
        self.setTabOrder(self.end_date, self.terms)
        self.setTabOrder(self.terms, self.notes)
        self.setTabOrder(self.notes, cancel_btn)
        self.setTabOrder(cancel_btn, self.save_btn)

    def _on_type_changed(self, _index: int) -> None:
        """Show/hide end date based on contract type."""
        is_rent = self.contract_type.currentData() == "rent"
        self.end_date_label.setVisible(is_rent)
        self.end_date.setVisible(is_rent)

    def accept_contract(self) -> None:
        """Validate and accept the contract."""
        contract_type_obj = self.contract_type.currentData()
        contract_type = (
            str(contract_type_obj)
            if isinstance(contract_type_obj, str) and contract_type_obj
            else "buy"
        )
        start_date = self.start_date.date().toString("yyyy-MM-dd")
        end_date = self.end_date.date().toString("yyyy-MM-dd") if contract_type == "rent" else None

        self.contract_data = {
            "client_id": self.client_id,
            "listing_id": self.listing_id,
            "contract_type": contract_type,
            "amount": self.amount.value(),
            "deposit": self.deposit.value(),
            "start_date": start_date,
            "end_date": end_date,
            "terms": self.terms.toPlainText().strip(),
            "notes": self.notes.toPlainText().strip(),
        }

        self.accept()

    def get_contract_data(self) -> ContractData | None:
        """Return the contract data if accepted."""
        return self.contract_data

    @staticmethod
    def _contract_type_label(contract_type: str) -> str:
        """Return a translated label for the contract type value."""
        return {
            "buy": _TR("Buy"),
            "rent": _TR("Rent"),
        }.get(contract_type, contract_type)
