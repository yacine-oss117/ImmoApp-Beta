from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QLabel, QStackedWidget, QVBoxLayout, QWidget

from app.utils.i18n import tr_factory
from app.views.imports.step_execution import StepExecution
from app.views.imports.step_mapping import StepMapping
from app.views.imports.step_review import StepReview
from app.views.imports.step_summary import StepSummary
from app.views.imports.step_upload import StepUpload
from app.views.imports.wizard_state import ImportSessionState, ImportWizardController
from app.widgets.workspace_dialog import (
    WorkspaceDialogSpec,
    apply_workspace_dialog,
    workspace_margins,
)

_TR = tr_factory("ImportWizardDialog")


class ImportWizardDialog(QDialog):
    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        entity_type_hint: str | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(_TR("Import Data"))
        self.setObjectName("immoImportDialog")
        apply_workspace_dialog(
            self,
            WorkspaceDialogSpec(
                settings_key="dialogs/import_wizard_geometry",
                default_width=1360,
                default_height=900,
                min_width=1100,
                min_height=760,
                allow_maximize=True,
            ),
        )
        self.setModal(True)

        self.controller = ImportWizardController(self)
        if entity_type_hint:
            self.controller.update_state(entity_hint=entity_type_hint)

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)

        # Main Container with rounded background
        container = QWidget()
        container.setObjectName("WizardContent")
        c_layout = QVBoxLayout(container)
        c_layout.setContentsMargins(*workspace_margins())
        c_layout.setSpacing(10)

        self._step_label = QLabel("")
        self._step_label.setObjectName("importWizardStepLabel")
        self._step_label.setProperty("immoRole", "stepDescription")
        self._step_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        c_layout.addWidget(self._step_label)

        self.stack = QStackedWidget()
        self.stack.setObjectName("importWizardStack")

        # Steps
        self.step_upload = StepUpload(self.controller)
        self.step_mapping = StepMapping(self.controller)
        self.step_execution = StepExecution(self.controller)
        self.step_review = StepReview(self.controller)
        self.step_summary = StepSummary(self.controller)

        self.stack.addWidget(self.step_upload)
        self.stack.addWidget(self.step_mapping)
        self.stack.addWidget(self.step_execution)
        self.stack.addWidget(self.step_review)
        self.stack.addWidget(self.step_summary)

        c_layout.addWidget(self.stack)
        self._layout.addWidget(container)

        # Connections
        self.step_upload.nextRequested.connect(self.go_to_mapping)
        self.step_mapping.backRequested.connect(self.go_to_upload)
        self.step_mapping.nextRequested.connect(self.go_to_execution)
        self.step_execution.reviewRequested.connect(self.go_to_review)
        self.step_execution.finished.connect(self.go_to_summary)
        self.step_execution.closeRequested.connect(self.reject)
        self.step_review.finished.connect(self.go_to_summary)
        self.step_summary.closeRequested.connect(self.accept)
        self.stack.currentChanged.connect(self._refresh_step_label)
        self._refresh_step_label()

    def final_state(self) -> ImportSessionState:
        return self.controller.state

    def go_to_upload(self) -> None:
        self.stack.setCurrentWidget(self.step_upload)

    def go_to_mapping(self) -> None:
        self.stack.setCurrentWidget(self.step_mapping)

    def go_to_execution(self) -> None:
        self.stack.setCurrentWidget(self.step_execution)
        self.step_execution.start_import()

    def go_to_review(self) -> None:
        self.step_review.refresh()
        self.stack.setCurrentWidget(self.step_review)

    def go_to_summary(self) -> None:
        self.step_summary.refresh()
        self.stack.setCurrentWidget(self.step_summary)

    def _refresh_step_label(self) -> None:
        index = self.stack.currentIndex() + 1
        total = self.stack.count()
        step_titles = {
            1: _TR("Bring in your file"),
            2: _TR("Review your columns"),
            3: _TR("Prepare your import"),
            4: _TR("Review a few details"),
            5: _TR("Import summary"),
        }
        self._step_label.setText(
            _TR("Step {current} of {total}").format(current=index, total=total)
            + f"  •  {step_titles.get(index, '')}"
        )


def open_import_wizard(
    parent: QWidget | None = None,
    *,
    entity_type_hint: str | None = None,
) -> ImportSessionState | None:
    dialog = ImportWizardDialog(parent, entity_type_hint=entity_type_hint)
    if dialog.exec():
        return dialog.final_state()
    return None
