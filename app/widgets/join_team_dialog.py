"""Team invite acceptance dialog."""

from __future__ import annotations

import logging

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QWidget,
)

from app.services.api_client import ApiError, set_session_access_token, set_session_credentials
from app.services.api_config import clear_api_token, set_api_config
from app.services.onboarding_analytics import record_onboarding_event
from app.services.onboarding_drafts import (
    JOIN_TEAM_DRAFT_KEY,
    clear_onboarding_draft,
    has_onboarding_draft,
    load_onboarding_draft,
    save_onboarding_draft,
)
from app.services.registration_repository import accept_invite
from app.utils.i18n import tr_factory
from app.utils.qt_async import run_blocking
from app.widgets.join_team_dialog_ui import setup_join_team_dialog

logger = logging.getLogger(__name__)
_TR = tr_factory("JoinTeamDialog")


class JoinTeamDialog(QDialog):
    """Invite-code onboarding for agents/managers."""

    _stack: QStackedWidget
    _status: QLabel
    _btn_back: QPushButton
    _btn_discard: QPushButton
    _btn_next: QPushButton
    _invite_code: QLineEdit
    _email: QLineEdit
    _password: QLineEdit
    _password_confirm: QLineEdit
    _summary: QLabel

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._done = False
        self._agency_name = ""
        self._busy = False
        self._restoring_draft = False
        self._resumed_from_draft = False
        self._draft_timer = QTimer(self)
        self._draft_timer.setSingleShot(True)
        self._draft_timer.timeout.connect(self._save_draft)
        setup_join_team_dialog(self)
        self._bind_field_state_reset()
        self._restore_draft()
        self._sync_actions()
        record_onboarding_event("join_dialog_opened", step="join", outcome="viewed")

    def _bind_field_state_reset(self) -> None:
        for field in (
            self._invite_code,
            self._email,
            self._password,
            self._password_confirm,
        ):
            field.textChanged.connect(lambda _text, widget=field: self._set_field_state(widget, ""))
        self._invite_code.textChanged.connect(lambda _text: self._schedule_draft_save())
        self._email.textChanged.connect(lambda _text: self._schedule_draft_save())

    def _current_step(self) -> int:
        return int(self._stack.currentIndex())

    def _set_step(self, step: int) -> None:
        self._stack.setCurrentIndex(max(0, min(2, int(step))))
        self._sync_actions()
        self._save_draft()

    def _set_status(self, text: str, *, state: str | None = None) -> None:
        self._status.setVisible(bool(text))
        self._status.setText(text)
        self._status.setProperty("immoState", state or "")
        style = self._status.style()
        if style is not None:
            style.unpolish(self._status)
            style.polish(self._status)

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        can_edit = not busy and not self._done
        self._btn_back.setEnabled(self._current_step() > 0 and can_edit)
        self._btn_next.setEnabled(not busy)
        self._btn_discard.setEnabled(has_onboarding_draft(JOIN_TEAM_DRAFT_KEY) and can_edit)
        for field in (
            self._invite_code,
            self._email,
            self._password,
            self._password_confirm,
        ):
            field.setEnabled(can_edit)

    @staticmethod
    def _set_field_state(widget: QWidget, state: str) -> None:
        widget.setProperty("immoState", state)
        style = widget.style()
        if style is not None:
            style.unpolish(widget)
            style.polish(widget)

    def _clear_field_states(self) -> None:
        for field in (
            self._invite_code,
            self._email,
            self._password,
            self._password_confirm,
        ):
            self._set_field_state(field, "")

    @staticmethod
    def _normalize_code(raw: str) -> str:
        return "".join(ch for ch in raw.upper() if ch.isalnum())

    @staticmethod
    def _friendly_api_error(exc: ApiError) -> str:
        status = int(exc.status_code or 0)
        if status == 400:
            return _TR("Please check your invite code, email, and password.")
        if status == 403:
            return _TR("This invite code is not valid anymore. Ask for a new one.")
        if status == 404:
            return _TR("We could not find this invite. Check the code and email.")
        if status == 409:
            return _TR("This invite was already used. Sign in with your account.")
        if status == 429:
            return _TR("Too many tries. Please wait a little and try again.")
        if status >= 500:
            return _TR("The service is busy right now. Please try again soon.")
        return _TR("We could not join your team right now. Please try again.")

    def _draft_payload(self) -> dict[str, object]:
        return {
            "invite_code": self._normalize_code((self._invite_code.text() or "").strip()),
            "email": (self._email.text() or "").strip(),
            "step": self._current_step(),
        }

    def _restore_draft(self) -> None:
        draft = load_onboarding_draft(JOIN_TEAM_DRAFT_KEY)
        if not draft:
            return
        self._restoring_draft = True
        try:
            self._invite_code.setText(self._normalize_code(str(draft.get("invite_code") or "")))
            self._email.setText(str(draft.get("email") or ""))
            step_obj = draft.get("step")
            step = int(step_obj) if isinstance(step_obj, (int, float, str)) else 0
            self._stack.setCurrentIndex(max(0, min(1, step)))
            self._resumed_from_draft = True
            self._set_status(_TR("We restored your previous progress."), state="loading")
            record_onboarding_event("join_resume_loaded", step="join", outcome="resumed")
        except Exception:
            logger.debug("Failed to restore join draft", exc_info=True)
        finally:
            self._restoring_draft = False

    def _schedule_draft_save(self) -> None:
        if self._done or self._restoring_draft:
            return
        self._draft_timer.start(250)

    def _save_draft(self) -> None:
        if self._done or self._restoring_draft:
            return
        payload = self._draft_payload()
        if self._has_meaningful_draft(payload):
            save_onboarding_draft(JOIN_TEAM_DRAFT_KEY, payload)
        else:
            clear_onboarding_draft(JOIN_TEAM_DRAFT_KEY)
        self._sync_actions()

    @staticmethod
    def _has_meaningful_draft(payload: dict[str, object]) -> bool:
        step = payload.get("step")
        if isinstance(step, int) and step > 0:
            return True
        return bool(
            str(payload.get("invite_code") or "").strip() or str(payload.get("email") or "").strip()
        )

    def _clear_form(self) -> None:
        self._invite_code.clear()
        self._email.clear()
        self._password.clear()
        self._password_confirm.clear()
        self._summary.clear()
        self._clear_field_states()

    def _sync_actions(self) -> None:
        step = self._current_step()
        self._btn_back.setEnabled(step > 0 and not self._done and not self._busy)
        self._btn_next.setEnabled(not self._busy)
        self._btn_discard.setEnabled(
            has_onboarding_draft(JOIN_TEAM_DRAFT_KEY)
            and not self._done
            and not self._busy
            and step < 2
        )
        if step == 2:
            self._btn_next.setText(_TR("Continue"))
        elif step == 1:
            self._btn_next.setText(_TR("Join team"))
        else:
            self._btn_next.setText(_TR("Continue"))

    def _go_back(self) -> None:
        if self._busy:
            return
        if self._current_step() > 0 and not self._done:
            self._set_step(self._current_step() - 1)
            self._set_status("")

    def _go_next(self) -> None:
        if self._busy:
            return
        step = self._current_step()
        if step == 2:
            self.accept()
            return
        if step == 0:
            self._clear_field_states()
            invite_code = self._normalize_code((self._invite_code.text() or "").strip())
            if not invite_code:
                self._set_field_state(self._invite_code, "error")
                self._set_status(_TR("Invite code is required."), state="error")
                return
            if len(invite_code) != 6:
                self._set_field_state(self._invite_code, "error")
                self._set_status(_TR("Invite code must be 6 characters."), state="error")
                return
            self._invite_code.setText(invite_code)
            self._set_step(1)
            return
        self._submit()

    def _discard_saved_progress(self) -> None:
        if self._busy or self._done or not has_onboarding_draft(JOIN_TEAM_DRAFT_KEY):
            return
        confirm = QMessageBox.question(
            self,
            _TR("Discard saved progress"),
            _TR("Remove saved progress and start this setup from the beginning?"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        self._draft_timer.stop()
        clear_onboarding_draft(JOIN_TEAM_DRAFT_KEY)
        self._resumed_from_draft = False
        self._clear_form()
        self._set_step(0)
        self._set_status(_TR("Saved progress removed."), state="success")
        record_onboarding_event("join_resume_discarded", step="join", outcome="discarded")

    def _persist_draft_before_close(self) -> None:
        if self._done or self._restoring_draft:
            return
        if self._draft_timer.isActive():
            self._draft_timer.stop()
        self._save_draft()

    def reject(self) -> None:
        if not self._done:
            record_onboarding_event(
                "join_abandoned",
                step="join",
                outcome=f"step_{self._current_step()}",
            )
        self._persist_draft_before_close()
        super().reject()

    def _submit(self) -> None:
        self._clear_field_states()
        invite_code = self._normalize_code((self._invite_code.text() or "").strip())
        email = (self._email.text() or "").strip()
        password = self._password.text()
        password_confirm = self._password_confirm.text()
        if not email or not password or not password_confirm:
            if not email:
                self._set_field_state(self._email, "error")
            if not password:
                self._set_field_state(self._password, "error")
            if not password_confirm:
                self._set_field_state(self._password_confirm, "error")
            self._set_status(_TR("Please fill in all required fields."), state="error")
            return
        if password != password_confirm:
            self._set_field_state(self._password, "error")
            self._set_field_state(self._password_confirm, "error")
            self._set_status(_TR("Passwords do not match."), state="error")
            return

        payload: dict[str, object] = {
            "invite_code": invite_code,
            "email": email,
            "password": password,
            "password_confirm": password_confirm,
        }
        record_onboarding_event("join_submitted", step="join", outcome="submitted")

        def _call() -> dict[str, object]:
            return accept_invite(payload)

        self._set_busy(True)
        self._set_status(_TR("Joining your team..."), state="loading")
        try:
            response = run_blocking(_call, timeout_ms=20000)
        except TimeoutError:
            self._set_status(
                _TR("Server is taking too long. Please try again in a moment."),
                state="error",
            )
            record_onboarding_event("join_failed", step="join", outcome="timeout")
            self._set_busy(False)
            return
        except ApiError as exc:
            self._set_status(self._friendly_api_error(exc), state="error")
            record_onboarding_event(
                "join_failed",
                step="join",
                outcome=f"http_{int(exc.status_code or 0)}",
            )
            self._set_busy(False)
            return
        except Exception:
            logger.error("Join team failed", exc_info=True)
            self._set_status(
                _TR("We could not join your team. Please check your connection."),
                state="error",
            )
            record_onboarding_event("join_failed", step="join", outcome="network_error")
            self._set_busy(False)
            return

        tokens = response.get("tokens")
        if isinstance(tokens, dict):
            access = str(tokens.get("access") or "")
            if access:
                set_session_access_token(access)
            set_session_credentials(email, password)
            clear_api_token()
            set_api_config(username=email, remember_session=True)
        self._agency_name = str(response.get("agency_name") or "")

        self._done = True
        self._summary.setText(
            _TR("Welcome! You're part of {agency_name}.").format(
                agency_name=self._agency_name or _TR("your agency")
            )
        )
        self._set_step(2)
        self._draft_timer.stop()
        clear_onboarding_draft(JOIN_TEAM_DRAFT_KEY)
        self._set_status(_TR("You're all set!"), state="success")
        record_onboarding_event("join_succeeded", step="join", outcome="completed")
        if self._resumed_from_draft:
            record_onboarding_event("join_resume_completed", step="join", outcome="completed")
            self._resumed_from_draft = False
        self._set_busy(False)


__all__ = ["JoinTeamDialog"]
