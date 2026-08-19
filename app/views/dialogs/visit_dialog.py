"""Visit scheduling dialog UI."""

from app.shared_types import VisitData
from app.utils.i18n import tr_factory
from app.views.base import (
    QDate,
    QDateEdit,
    QDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QTime,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

_TR = tr_factory("VisitDialog")


class VisitDialog(QDialog):
    """Dialog for scheduling a visit."""

    def __init__(
        self,
        client_id: int,
        listing_id: int,
        client_phone: str = "",
        listing_location: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.client_id = client_id
        self.listing_id = listing_id
        self.visit_data: VisitData | None = None

        self.setWindowTitle(_TR("Schedule Visit"))
        self.setMinimumWidth(500)
        self.setObjectName("immoDialog")

        layout = QVBoxLayout()

        # Info section - convert int IDs to str for display
        info_layout = QFormLayout()
        info_layout.addRow(QLabel(_TR("<b>Client ID:</b>")), QLabel(str(client_id)))
        info_layout.addRow(QLabel(_TR("<b>Client Phone:</b>")), QLabel(client_phone or _TR("N/A")))
        info_layout.addRow(QLabel(_TR("<b>Listing ID:</b>")), QLabel(str(listing_id)))
        info_layout.addRow(QLabel(_TR("<b>Location:</b>")), QLabel(listing_location or _TR("N/A")))

        layout.addLayout(info_layout)

        # Separator
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(separator)

        # Form
        form = QFormLayout()

        # Date picker
        self.date_edit = QDateEdit()
        self.date_edit.setAccessibleName(_TR("Visit date"))
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDate(QDate.currentDate())
        self.date_edit.setMinimumDate(QDate.currentDate())
        form.addRow(_TR("Visit Date:"), self.date_edit)

        # Time picker
        self.time_edit = QTimeEdit()
        self.time_edit.setAccessibleName(_TR("Visit time"))
        self.time_edit.setTime(QTime(10, 0))  # Default 10:00 AM
        self.time_edit.setDisplayFormat("HH:mm")
        form.addRow(_TR("Visit Time:"), self.time_edit)

        # Notes
        self.notes = QTextEdit()
        self.notes.setAccessibleName(_TR("Visit notes"))
        self.notes.setAccessibleDescription(_TR("Notes about the visit."))
        self.notes.setPlaceholderText(_TR("Add any notes about the visit..."))
        self.notes.setMinimumHeight(104)
        form.addRow(_TR("Notes:"), self.notes)

        layout.addLayout(form)

        # Buttons
        btn_layout = QHBoxLayout()
        self.save_btn = QPushButton(_TR("Schedule Visit"))
        self.save_btn.clicked.connect(self.accept_visit)
        self.save_btn.setAccessibleName(_TR("Schedule visit"))
        self.save_btn.setProperty("immoVariant", "success")

        cancel_btn = QPushButton(_TR("Cancel"))
        cancel_btn.clicked.connect(self.reject)
        cancel_btn.setAccessibleName(_TR("Cancel"))
        cancel_btn.setProperty("immoVariant", "ghost")

        btn_layout.addStretch()
        btn_layout.addWidget(cancel_btn)
        btn_layout.addWidget(self.save_btn)

        layout.addLayout(btn_layout)
        self.setLayout(layout)
        self.setTabOrder(self.date_edit, self.time_edit)
        self.setTabOrder(self.time_edit, self.notes)
        self.setTabOrder(self.notes, cancel_btn)
        self.setTabOrder(cancel_btn, self.save_btn)

    def accept_visit(self) -> None:
        """Validate and accept the visit."""
        date = self.date_edit.date().toString("yyyy-MM-dd")
        time = self.time_edit.time().toString("HH:mm")
        notes = self.notes.toPlainText().strip()

        self.visit_data = {
            "client_id": self.client_id,
            "listing_id": self.listing_id,
            "scheduled_date": date,
            "scheduled_time": time,
            "notes": notes,
            "status": "scheduled",
        }

        self.accept()

    def get_visit_data(self) -> VisitData | None:
        """Return the visit data if accepted."""
        return self.visit_data
