import os

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.utils.i18n import tr_factory
from app.views.imports.import_experience import ImportExperienceSummary, SummaryMetric
from app.views.imports.wizard_state import ImportWizardController

_TR = tr_factory("ImportWizardStepSummary")
_AUTO_CLOSE_DELAY_MS = 1200
_AUTO_CLOSE_ENABLED = os.environ.get("IMMOAPP_E2E_TEST_MODE") != "1"


class StatCard(QFrame):
    def __init__(self, label: str, value: int, state: str, icon: str = "") -> None:
        super().__init__()
        self.setObjectName("StatCard")
        self.setProperty("immoState", state)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(4)

        # Value
        val_label = QLabel(f"{value}")
        val_label.setObjectName("StatValue")
        val_label.setProperty("immoState", state)

        # Label with Icon
        txt_label = QLabel(f"{icon} {label}")
        txt_label.setObjectName("StatLabel")

        layout.addWidget(val_label)
        layout.addWidget(txt_label)


class StepSummary(QWidget):
    closeRequested = Signal()

    def __init__(self, controller: ImportWizardController) -> None:
        super().__init__()
        self.setObjectName("importStepSummary")
        self.controller = controller
        self._auto_close_token = 0
        self._layout = QVBoxLayout(self)
        self._layout.setSpacing(16)
        self._layout.setContentsMargins(0, 8, 0, 8)

        # Header Status
        self.header_container = QWidget()
        h_layout = QVBoxLayout(self.header_container)
        h_layout.setSpacing(8)

        self.title_label = QLabel(_TR("Your import is complete"))
        self.title_label.setObjectName("StepTitle")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        self.subtitle_label = QLabel(_TR("Your file is now in your agency."))
        self.subtitle_label.setObjectName("StepDescription")
        self.subtitle_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.subtitle_label.setWordWrap(True)

        h_layout.addWidget(self.title_label)
        h_layout.addWidget(self.subtitle_label)

        self._layout.addWidget(self.header_container)

        # Stats Grid (2x2 centered)
        stats_container = QWidget()
        stats_layout = QHBoxLayout(stats_container)
        stats_layout.setSpacing(12)

        self.grid = QGridLayout()
        self.grid.setSpacing(12)

        self.card_created = StatCard(_TR("Added"), 0, "success")
        self.card_updated = StatCard(_TR("Updated"), 0, "info")
        self.card_errors = StatCard(_TR("Needs attention"), 0, "error")
        self.card_skipped = StatCard(_TR("Not imported"), 0, "muted")

        self.grid.addWidget(self.card_created, 0, 0)
        self.grid.addWidget(self.card_updated, 0, 1)
        self.grid.addWidget(self.card_errors, 1, 0)
        self.grid.addWidget(self.card_skipped, 1, 1)

        stats_layout.addLayout(self.grid)

        self._layout.addWidget(stats_container)

        self.automation_list = QListWidget()
        self.automation_list.setVisible(False)
        self._layout.addWidget(self.automation_list)

        self.attention_list = QListWidget()
        self.attention_list.setVisible(False)
        self._layout.addWidget(self.attention_list)

        # Actions
        actions = QHBoxLayout()
        actions.addStretch()
        self.close_btn = QPushButton(_TR("Finish"))
        self.close_btn.setObjectName("importSummaryFinishButton")
        self.close_btn.setProperty("immoVariant", "primary")
        self.close_btn.setMinimumWidth(120)
        self.close_btn.clicked.connect(self.closeRequested.emit)
        actions.addWidget(self.close_btn)
        actions.addStretch()

        self._layout.addLayout(actions)

    def refresh(self) -> None:
        state = self.controller.state
        summary = state.experience_summary

        if summary is None:
            summary = ImportExperienceSummary(
                tone="success",
                headline=_TR("Your import is complete"),
                supporting_text=_TR("Your file is now in your agency."),
                primary_counts=[],
                automation_points=[],
                attention_points=[],
                detail_lines=[],
            )
        self.title_label.setText(summary.headline)
        self.subtitle_label.setText(summary.supporting_text)

        # Re-create cards to update values
        # (Alternatively, could add set_value method to StatCard)
        for i in reversed(range(self.grid.count())):
            item = self.grid.itemAt(i)
            widget = item.widget() if item else None
            if widget is not None:
                widget.setParent(None)

        metrics = summary.primary_counts or [
            SummaryMetric(_TR("Added"), state.created_count, "success"),
            SummaryMetric(_TR("Updated"), state.updated_count, "success"),
            SummaryMetric(_TR("Needs attention"), state.error_count, "warning"),
            SummaryMetric(_TR("Not imported"), state.skipped_count, "muted"),
        ]
        cards = [StatCard(metric.label, metric.value, metric.kind) for metric in metrics]
        for index, card in enumerate(cards):
            self.grid.addWidget(card, index // 2, index % 2)

        self.automation_list.clear()
        for line in summary.automation_points:
            self.automation_list.addItem(QListWidgetItem(line))
        self.automation_list.setVisible(bool(summary.automation_points))

        self.attention_list.clear()
        for line in summary.attention_points:
            self.attention_list.addItem(QListWidgetItem(line))
        self.attention_list.setVisible(bool(summary.attention_points))
        self._arm_auto_close(summary=summary, status=str(state.status or ""))

    def _arm_auto_close(self, *, summary: ImportExperienceSummary, status: str) -> None:
        should_auto_close = (
            _AUTO_CLOSE_ENABLED and status == "completed" and summary.tone == "success"
        )
        self._auto_close_token += 1
        if not should_auto_close:
            return
        current_token = self._auto_close_token
        QTimer.singleShot(
            _AUTO_CLOSE_DELAY_MS,
            lambda token=current_token: self._emit_auto_close_if_current(token),
        )

    def _emit_auto_close_if_current(self, token: int) -> None:
        if token != self._auto_close_token:
            return
        self.closeRequested.emit()
