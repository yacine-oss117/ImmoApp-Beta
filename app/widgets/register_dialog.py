"""Agency registration dialog."""

from __future__ import annotations

import logging

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QWidget,
)

from app.services.api_client import ApiError
from app.services.onboarding_analytics import record_onboarding_event
from app.services.onboarding_drafts import (
    REGISTER_DRAFT_KEY,
    clear_onboarding_draft,
    has_onboarding_draft,
    load_onboarding_draft,
    save_onboarding_draft,
)
from app.services.registration_repository import submit_registration
from app.utils.i18n import tr_factory
from app.utils.qt_async import run_blocking
from app.widgets.register_dialog_ui import setup_register_dialog

logger = logging.getLogger(__name__)
_TR = tr_factory("RegisterDialog")


class RegisterDialog(QDialog):
    """Three-step agency registration flow."""

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

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._submitted = False
        self._busy = False
        self._restoring_draft = False
        self._resumed_from_draft = False
        self._draft_timer = QTimer(self)
        self._draft_timer.setSingleShot(True)
        self._draft_timer.timeout.connect(self._save_draft)
        setup_register_dialog(self)
        self._bind_field_state_reset()
        self._restore_draft()
        self._sync_actions()
        record_onboarding_event("register_dialog_opened", step="register", outcome="viewed")

    def _bind_field_state_reset(self) -> None:
        for field in (
            self._agency_name,
            self._legal_name,
            self._registry_number,
            self._agency_address,
            self._agency_city,
            self._agency_postal_code,
            self._owner_first_name,
            self._owner_last_name,
            self._owner_email,
            self._owner_phone,
        ):
            field.textChanged.connect(lambda _text, widget=field: self._set_field_state(widget, ""))
            field.textChanged.connect(lambda _text: self._schedule_draft_save())
        self._terms_accepted.toggled.connect(
            lambda _checked: self._set_field_state(self._terms_accepted, "")
        )
        self._terms_accepted.toggled.connect(lambda _checked: self._schedule_draft_save())

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
        enabled = not busy and not self._submitted
        self._btn_back.setEnabled(self._current_step() > 0 and enabled)
        self._btn_next.setEnabled(not busy)
        self._btn_discard.setEnabled(has_onboarding_draft(REGISTER_DRAFT_KEY) and enabled)
        for field in (
            self._agency_name,
            self._legal_name,
            self._registry_number,
            self._agency_address,
            self._agency_city,
            self._agency_postal_code,
            self._owner_first_name,
            self._owner_last_name,
            self._owner_email,
            self._owner_phone,
            self._terms_accepted,
        ):
            field.setEnabled(enabled)

    @staticmethod
    def _set_field_state(widget: QWidget, state: str) -> None:
        widget.setProperty("immoState", state)
        style = widget.style()
        if style is not None:
            style.unpolish(widget)
            style.polish(widget)

    def _clear_field_states(self) -> None:
        for field in (
            self._agency_name,
            self._legal_name,
            self._registry_number,
            self._agency_address,
            self._agency_city,
            self._agency_postal_code,
            self._owner_first_name,
            self._owner_last_name,
            self._owner_email,
            self._owner_phone,
            self._terms_accepted,
        ):
            self._set_field_state(field, "")

    @staticmethod
    def _friendly_api_error(exc: ApiError) -> str:
        code = str(exc.code or "").strip().upper()
        if code == "REGISTRATION_UNAVAILABLE":
            return _TR("Registration is not available right now.")
        if code == "EMAIL_QUEUE_UNAVAILABLE":
            return _TR("Email delivery is temporarily unavailable. Please try again shortly.")
        status = int(exc.status_code or 0)
        if status == 400:
            return _TR("Please check your information and try again.")
        if status == 409:
            return _TR("This email is already used. Try a different email.")
        if status == 429:
            return _TR("Too many tries. Please wait a little and try again.")
        if status >= 500:
            return _TR("The service is busy right now. Please try again soon.")
        return _TR("We could not send your request. Please try again.")

    def _current_step(self) -> int:
        return int(self._stack.currentIndex())

    def _set_step(self, index: int) -> None:
        self._stack.setCurrentIndex(max(0, min(2, int(index))))
        self._sync_actions()
        self._save_draft()

    def _sync_actions(self) -> None:
        step = self._current_step()
        self._btn_back.setEnabled(step > 0 and not self._submitted and not self._busy)
        self._btn_next.setEnabled(not self._busy)
        self._btn_discard.setEnabled(
            has_onboarding_draft(REGISTER_DRAFT_KEY)
            and not self._submitted
            and not self._busy
            and step < 2
        )
        if step == 2:
            self._btn_next.setText(_TR("Close") if self._submitted else _TR("Send request"))
        elif step == 1:
            self._btn_next.setText(_TR("Send request"))
        else:
            self._btn_next.setText(_TR("Next"))

    def _payload(self) -> dict[str, object]:
        return {
            "agency_name": (self._agency_name.text() or "").strip(),
            "legal_name": (self._legal_name.text() or "").strip(),
            "registry_number": (self._registry_number.text() or "").strip(),
            "agency_address": (self._agency_address.text() or "").strip(),
            "agency_city": (self._agency_city.text() or "").strip(),
            "agency_postal_code": (self._agency_postal_code.text() or "").strip(),
            "owner_first_name": (self._owner_first_name.text() or "").strip(),
            "owner_last_name": (self._owner_last_name.text() or "").strip(),
            "owner_email": (self._owner_email.text() or "").strip(),
            "owner_phone": (self._owner_phone.text() or "").strip(),
            "terms_accepted": bool(self._terms_accepted.isChecked()),
        }

    def _draft_payload(self) -> dict[str, object]:
        payload = self._payload()
        payload["step"] = self._current_step()
        return payload

    def _restore_draft(self) -> None:
        draft = load_onboarding_draft(REGISTER_DRAFT_KEY)
        if not draft:
            return
        self._restoring_draft = True
        try:
            self._agency_name.setText(str(draft.get("agency_name") or ""))
            self._legal_name.setText(str(draft.get("legal_name") or ""))
            self._registry_number.setText(str(draft.get("registry_number") or ""))
            self._agency_address.setText(str(draft.get("agency_address") or ""))
            self._agency_city.setText(str(draft.get("agency_city") or ""))
            self._agency_postal_code.setText(str(draft.get("agency_postal_code") or ""))
            self._owner_first_name.setText(str(draft.get("owner_first_name") or ""))
            self._owner_last_name.setText(str(draft.get("owner_last_name") or ""))
            self._owner_email.setText(str(draft.get("owner_email") or ""))
            self._owner_phone.setText(str(draft.get("owner_phone") or ""))
            self._terms_accepted.setChecked(bool(draft.get("terms_accepted")))
            step_obj = draft.get("step")
            step = int(step_obj) if isinstance(step_obj, (int, float, str)) else 0
            self._stack.setCurrentIndex(max(0, min(1, step)))
            self._resumed_from_draft = True
            self._set_status(_TR("We restored your previous progress."), state="loading")
            record_onboarding_event("register_resume_loaded", step="register", outcome="resumed")
        except Exception:
            logger.debug("Failed to restore register draft", exc_info=True)
        finally:
            self._restoring_draft = False

    def _schedule_draft_save(self) -> None:
        if self._submitted or self._restoring_draft:
            return
        self._draft_timer.start(250)

    def _save_draft(self) -> None:
        if self._submitted or self._restoring_draft:
            return
        payload = self._draft_payload()
        if self._has_meaningful_draft(payload):
            save_onboarding_draft(REGISTER_DRAFT_KEY, payload)
        else:
            clear_onboarding_draft(REGISTER_DRAFT_KEY)
        self._sync_actions()

    @staticmethod
    def _has_meaningful_draft(payload: dict[str, object]) -> bool:
        step = payload.get("step")
        if isinstance(step, int) and step > 0:
            return True
        for key in (
            "agency_name",
            "legal_name",
            "registry_number",
            "agency_address",
            "agency_city",
            "agency_postal_code",
            "owner_first_name",
            "owner_last_name",
            "owner_email",
            "owner_phone",
        ):
            if str(payload.get(key) or "").strip():
                return True
        return bool(payload.get("terms_accepted"))

    def _clear_form(self) -> None:
        self._agency_name.clear()
        self._legal_name.clear()
        self._registry_number.clear()
        self._agency_address.clear()
        self._agency_city.clear()
        self._agency_postal_code.clear()
        self._owner_first_name.clear()
        self._owner_last_name.clear()
        self._owner_email.clear()
        self._owner_phone.clear()
        self._terms_accepted.setChecked(False)
        self._summary.clear()
        self._clear_field_states()

    def _discard_saved_progress(self) -> None:
        if self._busy or self._submitted or not has_onboarding_draft(REGISTER_DRAFT_KEY):
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
        clear_onboarding_draft(REGISTER_DRAFT_KEY)
        self._resumed_from_draft = False
        self._clear_form()
        self._set_step(0)
        self._set_status(_TR("Saved progress removed."), state="success")
        record_onboarding_event("register_resume_discarded", step="register", outcome="discarded")

    def _persist_draft_before_close(self) -> None:
        if self._submitted or self._restoring_draft:
            return
        if self._draft_timer.isActive():
            self._draft_timer.stop()
        self._save_draft()

    def reject(self) -> None:
        if not self._submitted:
            record_onboarding_event(
                "register_abandoned",
                step="register",
                outcome=f"step_{self._current_step()}",
            )
        self._persist_draft_before_close()
        super().reject()

    def _validate_step(self, step: int) -> bool:
        self._clear_field_states()
        payload = self._payload()
        required: tuple[str, ...]
        if step == 0:
            required = (
                "agency_name",
                "legal_name",
                "registry_number",
                "agency_address",
                "agency_city",
                "agency_postal_code",
            )
        else:
            required = ("owner_first_name", "owner_last_name", "owner_email", "owner_phone")
        missing = [field for field in required if not payload.get(field)]
        if missing:
            field_map: dict[str, QWidget] = {
                "agency_name": self._agency_name,
                "legal_name": self._legal_name,
                "registry_number": self._registry_number,
                "agency_address": self._agency_address,
                "agency_city": self._agency_city,
                "agency_postal_code": self._agency_postal_code,
                "owner_first_name": self._owner_first_name,
                "owner_last_name": self._owner_last_name,
                "owner_email": self._owner_email,
                "owner_phone": self._owner_phone,
            }
            first = field_map.get(missing[0])
            if first is not None:
                first.setFocus()
            for key in missing:
                widget = field_map.get(key)
                if widget is not None:
                    self._set_field_state(widget, "error")
            self._set_status(_TR("Please fill in all required fields."), state="error")
            return False
        if step == 1:
            email = str(payload.get("owner_email") or "")
            phone = str(payload.get("owner_phone") or "")
            if "@" not in email or "." not in email.split("@")[-1]:
                self._set_field_state(self._owner_email, "error")
                self._owner_email.setFocus()
                self._set_status(_TR("Please enter a valid email address."), state="error")
                return False
            digits = "".join(ch for ch in phone if ch.isdigit())
            if len(digits) < 8:
                self._set_field_state(self._owner_phone, "error")
                self._owner_phone.setFocus()
                self._set_status(_TR("Please enter a valid phone number."), state="error")
                return False
        if step == 1 and not payload.get("terms_accepted"):
            self._set_field_state(self._terms_accepted, "error")
            self._set_status(_TR("Please accept the terms to continue."), state="error")
            return False
        return True

    def _go_back(self) -> None:
        if self._busy:
            return
        if self._current_step() > 0 and not self._submitted:
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
            if not self._validate_step(0):
                return
            self._set_step(1)
            self._set_status("")
            return
        if step == 1:
            if not self._validate_step(1):
                return
            self._submit()

    def _submit(self) -> None:
        payload = self._payload()
        record_onboarding_event("register_submitted", step="register", outcome="submitted")

        def _call() -> dict[str, object]:
            return submit_registration(payload)

        self._set_busy(True)
        self._set_status(_TR("Sending your request..."), state="loading")
        try:
            response = run_blocking(_call, timeout_ms=20000)
        except TimeoutError:
            self._set_status(
                _TR("Server is taking too long. Please try again in a moment."),
                state="error",
            )
            record_onboarding_event("register_failed", step="register", outcome="timeout")
            self._set_busy(False)
            return
        except ApiError as exc:
            self._set_status(self._friendly_api_error(exc), state="error")
            record_onboarding_event(
                "register_failed",
                step="register",
                outcome=f"http_{int(exc.status_code or 0)}",
            )
            self._set_busy(False)
            return
        except Exception as exc:
            logger.error("Registration submit failed", exc_info=True)
            message = _TR("We could not send your request. Please check your connection.")
            if "circuit open" in str(exc).lower() or "circuit half-open" in str(exc).lower():
                message = _TR("The service is busy right now. Please try again soon.")
            self._set_status(
                message,
                state="error",
            )
            record_onboarding_event("register_failed", step="register", outcome="network_error")
            self._set_busy(False)
            return

        self._submitted = True
        message = str(response.get("message") or "")
        email = str(payload.get("owner_email") or "")
        self._summary.setText(
            message
            or _TR(
                "Your request has been submitted. We'll review it within 24 hours. You'll receive an email at {email}."
            ).format(email=email)
        )
        self._set_step(2)
        self._draft_timer.stop()
        clear_onboarding_draft(REGISTER_DRAFT_KEY)
        self._set_status(_TR("Request sent."), state="success")
        record_onboarding_event("register_succeeded", step="register", outcome="queued")
        if self._resumed_from_draft:
            record_onboarding_event(
                "register_resume_completed", step="register", outcome="completed"
            )
            self._resumed_from_draft = False
        self._set_busy(False)


__all__ = ["RegisterDialog"]
