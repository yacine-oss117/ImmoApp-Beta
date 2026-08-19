"""First-run quick-start chooser for onboarding."""

from __future__ import annotations

from typing import Final

from PySide6.QtWidgets import QDialog, QLabel, QPushButton, QWidget

from app.services.onboarding_analytics import (
    mark_quick_start_seen,
    record_onboarding_event,
    should_show_quick_start,
)
from app.utils.i18n import tr_factory
from app.widgets.quick_start_dialog_ui import setup_quick_start_dialog
from app.widgets.workspace_dialog import DialogSurfaceSpec, apply_dialog_surface

_TR = tr_factory("QuickStartDialog")

CHOICE_SIGN_IN: Final[str] = "sign_in"
CHOICE_REGISTER: Final[str] = "register"
CHOICE_JOIN: Final[str] = "join"


class QuickStartDialog(QDialog):
    """Simple first-run chooser to guide users into the right onboarding path."""

    _title: QLabel
    _hint: QLabel
    _status: QLabel
    _btn_sign_in: QPushButton
    _btn_register: QPushButton
    _btn_join: QPushButton

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._choice = CHOICE_SIGN_IN
        self.setWindowTitle(_TR("Get started"))
        self.setModal(True)
        apply_dialog_surface(
            self,
            DialogSurfaceSpec(
                settings_key=None,
                default_width=560,
                default_height=400,
                min_width=500,
                min_height=360,
                allow_maximize=False,
                persist_geometry=False,
                density="dialog",
            ),
        )
        setup_quick_start_dialog(self)

    @property
    def choice(self) -> str:
        return self._choice

    def _choose_sign_in(self) -> None:
        self._choice = CHOICE_SIGN_IN
        self.accept()

    def _choose_register(self) -> None:
        self._choice = CHOICE_REGISTER
        self.accept()

    def _choose_join(self) -> None:
        self._choice = CHOICE_JOIN
        self.accept()


def run_quick_start_flow(parent: QWidget | None = None, *, force: bool = False) -> str:
    """
    Run the first-run quick-start chooser and optional onboarding sub-flows.

    Returns the selected top-level choice.
    """
    if not force and not should_show_quick_start():
        return CHOICE_SIGN_IN

    outcome = "manual" if force else "shown"
    record_onboarding_event("quick_start_viewed", step="quick_start", outcome=outcome)
    dialog = QuickStartDialog(parent)
    result = int(dialog.exec())
    mark_quick_start_seen(seen=True)

    if result != int(QDialog.DialogCode.Accepted):
        record_onboarding_event("quick_start_closed", step="quick_start", outcome="dismissed")
        return CHOICE_SIGN_IN

    choice = dialog.choice
    record_onboarding_event("quick_start_selected", step="quick_start", outcome=choice)
    _run_choice_flow(choice, parent=parent)
    return choice


def _run_choice_flow(choice: str, *, parent: QWidget | None) -> None:
    if choice == CHOICE_REGISTER:
        from app.widgets.register_dialog import RegisterDialog

        register_dialog = RegisterDialog(parent)
        result = int(register_dialog.exec())
        outcome = "completed" if result == int(QDialog.DialogCode.Accepted) else "abandoned"
        record_onboarding_event("register_flow_finished", step="register", outcome=outcome)
        return

    if choice == CHOICE_JOIN:
        from app.widgets.join_team_dialog import JoinTeamDialog

        join_dialog = JoinTeamDialog(parent)
        result = int(join_dialog.exec())
        outcome = "completed" if result == int(QDialog.DialogCode.Accepted) else "abandoned"
        record_onboarding_event("join_flow_finished", step="join", outcome=outcome)
        return

    record_onboarding_event("sign_in_flow_selected", step="sign_in", outcome="continue")


__all__ = [
    "CHOICE_JOIN",
    "CHOICE_REGISTER",
    "CHOICE_SIGN_IN",
    "QuickStartDialog",
    "run_quick_start_flow",
]
