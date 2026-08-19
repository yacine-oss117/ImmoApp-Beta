"""Login dialog for API-first thin client."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFrame,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QWidget,
)

from app.services.api_client import (
    ApiError,
    clear_persisted_session,
    get_access_token,
    reset_api_session,
    set_session_credentials,
)
from app.services.api_config import (
    clear_api_token,
    get_api_config,
    normalize_api_base_url,
    set_api_config,
)
from app.services.network_sync import flush_pending_network_work
from app.services.onboarding_analytics import record_onboarding_event
from app.services.onboarding_drafts import (
    ACTIVATE_DRAFT_KEY,
    JOIN_TEAM_DRAFT_KEY,
    REGISTER_DRAFT_KEY,
    resolve_resume_target,
)
from app.utils.i18n import tr_factory
from app.utils.qt_async import run_blocking
from app.widgets.diagnostics_actions import show_error_with_diagnostics
from app.widgets.login_dialog_ui import setup_login_dialog
from app.widgets.workspace_dialog import DialogSurfaceSpec, apply_dialog_surface

logger = logging.getLogger(__name__)
_TR = tr_factory("LoginDialog")

# Backward-compatible import target for smoke tooling that still patches the old
# login post-auth sync hook name.
flush_pending_media_uploads = flush_pending_network_work

if TYPE_CHECKING:
    from PySide6.QtWidgets import QApplication


class LoginDialog(QDialog):
    """A polished login screen to configure API credentials."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(_TR("Sign in"))
        self.setModal(True)
        apply_dialog_surface(
            self,
            DialogSurfaceSpec(
                settings_key=None,
                default_width=920,
                default_height=560,
                min_width=840,
                min_height=520,
                allow_maximize=False,
                persist_geometry=False,
                density="dialog",
            ),
        )
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        self._base_url = QLineEdit(self)
        self._username = QLineEdit(self)
        self._password = QLineEdit(self)
        self._security_code = QLineEdit(self)
        self._remember = QCheckBox(_TR("Remember server & username"), self)
        self._remember.setObjectName("immoLoginRememberCheckbox")
        self._remember_session = QCheckBox(_TR("Keep me signed in"), self)
        self._remember_session.setObjectName("immoLoginRememberSessionCheckbox")
        self._status = QLabel("", self)
        self._step_one_panel = QFrame(self)
        self._step_two_panel = QFrame(self)
        self._server_settings_panel = QFrame(self)
        self._btn_server_settings = QPushButton(self)
        self._btn_back = QPushButton(self)
        self._btn_primary = QPushButton(self)
        self._btn_register = QPushButton(self)
        self._btn_join_team = QPushButton(self)
        self._btn_activate = QPushButton(self)
        self._btn_resume_setup = QPushButton(self)
        self._resume_badge = QLabel(self)
        self._resume_hint = QLabel(self)
        self._step_two_active = False
        self._pending_username = ""
        self._pending_password = ""
        self._resume_target: str | None = None
        self._resume_announced_target: str | None = None

        setup_login_dialog(self)
        self._load_defaults()
        self._refresh_resume_setup_action()

    def _load_defaults(self) -> None:
        config = get_api_config()
        if config.base_url:
            self._base_url.setText(config.base_url)
        else:
            self._server_settings_panel.setVisible(True)
        if config.username:
            self._username.setText(config.username)
        self._remember.setChecked(True)
        self._remember_session.setChecked(bool(config.remember_session))

    def _set_status(self, message: str, *, state: str | None = None) -> None:
        self._status.setText(message)
        self._status.setVisible(bool(message))
        self._status.setProperty("immoState", state or "")
        style = self._status.style()
        if style is not None:
            style.unpolish(self._status)
            style.polish(self._status)

    @staticmethod
    def _is_second_factor_required(exc: ApiError) -> bool:
        text = str(exc.message or "").lower()
        second_factor_markers = ("mfa", "totp", "second factor", "security code", "phone app")
        if not any(marker in text for marker in second_factor_markers):
            return False
        return "invalid username or password" not in text and "invalid credentials" not in text

    @staticmethod
    def _normalize_code(raw: str) -> str:
        return "".join(ch for ch in raw if ch.isdigit())

    @staticmethod
    def _iter_exception_chain(exc: BaseException) -> list[BaseException]:
        chain: list[BaseException] = []
        seen: set[int] = set()
        current: BaseException | None = exc
        while current is not None and id(current) not in seen:
            chain.append(current)
            seen.add(id(current))
            next_exc = current.__cause__ or current.__context__
            current = next_exc if isinstance(next_exc, BaseException) else None
        return chain

    @classmethod
    def _is_connection_refused_error(cls, exc: BaseException) -> bool:
        for candidate in cls._iter_exception_chain(exc):
            text = str(candidate).lower()
            if isinstance(candidate, ConnectionRefusedError):
                return True
            if (
                "connection refused" in text
                or "failed to establish a new connection" in text
                or "winerror 10061" in text
            ):
                return True
        return False

    @classmethod
    def _friendly_connection_error_message(cls, *, base_url: str, exc: BaseException) -> str:
        parsed = urlparse(base_url)
        hostname = (parsed.hostname or "").strip().lower()
        is_local_host = hostname in {"localhost", "127.0.0.1"}
        is_https = parsed.scheme.strip().lower() == "https"

        if is_local_host and cls._is_connection_refused_error(exc):
            if is_https:
                return _TR(
                    "The local secure server is not running. Start the Docker server, then try again."
                )
            return _TR("The local server is not running. Start the server, then try again.")

        return _TR("Could not reach the server. Check the server address and try again.")

    @staticmethod
    def _is_temporary_lockout(exc: ApiError) -> bool:
        return "too many failed attempts" in str(exc.message or "").strip().lower()

    def _set_step_two_mode(self, enabled: bool) -> None:
        self._step_two_active = enabled
        self._step_one_panel.setVisible(not enabled)
        self._step_two_panel.setVisible(enabled)
        self._btn_back.setVisible(enabled)
        if enabled:
            self._btn_primary.setText(_TR("Verify code"))
            self._set_status(
                _TR("Great, one more step. Enter the 6-digit code from your phone app."),
                state="loading",
            )
            self._security_code.setFocus()
            self._security_code.selectAll()
            return
        self._btn_primary.setText(_TR("Sign in"))
        self._security_code.clear()
        self._set_status("")

    def _back_to_password_step(self) -> None:
        self._set_step_two_mode(False)

    def _attempt_login(self) -> None:
        if self._step_two_active:
            self._attempt_step_two()
            return
        self._attempt_step_one()

    def _attempt_step_one(self) -> None:
        base_url = normalize_api_base_url(self._base_url.text())
        username = (self._username.text() or "").strip()
        password = self._password.text()

        if not base_url:
            self._server_settings_panel.setVisible(True)
            self._base_url.setFocus()
            self._set_status(
                _TR("Open server settings and enter a valid server address."),
                state="error",
            )
            return
        if not username or not password:
            self._set_status(_TR("Email and password are required."), state="error")
            return

        self._pending_username = username
        self._pending_password = password
        self._set_step_two_mode(False)
        record_onboarding_event("sign_in_step_1_submitted", step="sign_in", outcome="submitted")
        self._run_login(
            base_url=base_url,
            username=username,
            password=password,
            mfa_code=None,
            allow_step_two_transition=True,
        )

    def _attempt_step_two(self) -> None:
        if not self._pending_username or not self._pending_password:
            self._set_step_two_mode(False)
            self._set_status(_TR("Please sign in again."), state="error")
            return
        code = self._normalize_code((self._security_code.text() or "").strip())
        if not code:
            self._set_status(_TR("Enter the 6-digit code from your phone app."), state="error")
            return
        if len(code) != 6 or not code.isdigit():
            self._set_status(_TR("Wrong code, try again."), state="error")
            record_onboarding_event("sign_in_step_2_failed", step="sign_in", outcome="invalid_code")
            return
        self._security_code.setText(code)
        base_url = normalize_api_base_url(self._base_url.text())
        if not base_url:
            self._set_step_two_mode(False)
            self._set_status(
                _TR("Open server settings and enter a valid server address."),
                state="error",
            )
            return
        self._run_login(
            base_url=base_url,
            username=self._pending_username,
            password=self._pending_password,
            mfa_code=code,
            allow_step_two_transition=False,
        )

    def _run_login(
        self,
        *,
        base_url: str,
        username: str,
        password: str,
        mfa_code: str | None,
        allow_step_two_transition: bool,
    ) -> None:
        remember = self._remember.isChecked()
        remember_session = self._remember_session.isChecked()
        set_api_config(
            base_url=base_url,
            username=username if remember else "",
            password="",
            token=None,
            remember_session=remember_session,
        )
        clear_api_token()
        if not remember_session:
            clear_persisted_session(username)
        set_session_credentials(username, password)
        reset_api_session()

        def _login_flow() -> None:
            token = get_access_token(mfa_code=mfa_code)
            if not token:
                raise RuntimeError(_TR("Sign in failed."))

        self._set_status(_TR("Signing you in..."), state="loading")
        try:
            run_blocking(_login_flow, timeout_ms=15000)
        except TimeoutError:
            self._set_status(
                _TR("Server is taking too long to respond. Please try again."), state="error"
            )
            record_onboarding_event("sign_in_failed", step="sign_in", outcome="timeout")
            return
        except ApiError as exc:
            logger.error("API login failed", exc_info=True)
            if allow_step_two_transition and self._is_second_factor_required(exc):
                self._set_step_two_mode(True)
                record_onboarding_event(
                    "sign_in_step_2_required",
                    step="sign_in",
                    outcome="second_factor_required",
                )
                return
            if self._step_two_active and exc.status_code in (400, 401, 403):
                self._set_status(_TR("Wrong code, try again."), state="error")
                record_onboarding_event(
                    "sign_in_step_2_failed",
                    step="sign_in",
                    outcome=f"http_{int(exc.status_code)}",
                )
                return
            if self._is_temporary_lockout(exc):
                status_msg = _TR("Too many failed attempts. Try again later.")
                outcome = "locked_out"
            elif exc.status_code in (400, 401):
                status_msg = _TR("Login failed: invalid email or password.")
                outcome = f"http_{int(exc.status_code)}"
            elif exc.status_code >= 500:
                status_msg = _TR("Login failed: server error. Please try again.")
                outcome = f"http_{int(exc.status_code)}"
            else:
                status_msg = _TR("Login failed. Check your credentials and server address.")
                outcome = f"http_{int(exc.status_code)}"
            self._set_status(status_msg, state="error")
            record_onboarding_event(
                "sign_in_failed",
                step="sign_in",
                outcome=outcome,
            )
            if exc.status_code in (400, 401) and not self._is_temporary_lockout(exc):
                return
            show_error_with_diagnostics(
                self,
                title=_TR("Login failed"),
                message=(
                    status_msg if self._is_temporary_lockout(exc) else (exc.message or status_msg)
                ),
                route_name="desktop.login",
                normalized_route="/desktop/login",
                policy_id="desktop.auth.login",
                error_code=f"LOGIN_HTTP_{exc.status_code}",
            )
            return
        except Exception as exc:
            logger.error("API connection failed", exc_info=True)
            status_msg = self._friendly_connection_error_message(base_url=base_url, exc=exc)
            self._set_status(status_msg, state="error")
            record_onboarding_event("sign_in_failed", step="sign_in", outcome="network_error")
            show_error_with_diagnostics(
                self,
                title=_TR("Connection error"),
                message=status_msg,
                route_name="desktop.login",
                normalized_route="/desktop/login",
                policy_id="desktop.auth.login",
                error_code="LOGIN_CONNECTION_ERROR",
            )
            return

        self._set_status(_TR("You're all set!"), state="success")
        record_onboarding_event("sign_in_succeeded", step="sign_in", outcome="completed")
        try:
            flush_pending_network_work()
        except Exception:
            logger.debug("Failed to flush pending network work", exc_info=True)
        self.accept()

    def _toggle_server_settings(self) -> None:
        now_visible = not self._server_settings_panel.isVisible()
        self._server_settings_panel.setVisible(now_visible)
        if now_visible:
            self._base_url.setFocus()

    def _refresh_resume_setup_action(self) -> None:
        self._resume_target = resolve_resume_target()
        if self._resume_target == REGISTER_DRAFT_KEY:
            text = _TR("Continue agency setup")
            hint = _TR("You started agency setup earlier. Continue where you left off.")
            outcome = "register"
        elif self._resume_target == ACTIVATE_DRAFT_KEY:
            text = _TR("Continue activation")
            hint = _TR("You started activation earlier. Continue where you left off.")
            outcome = "activate"
        elif self._resume_target == JOIN_TEAM_DRAFT_KEY:
            text = _TR("Continue team join")
            hint = _TR("You started team join earlier. Continue where you left off.")
            outcome = "join"
        else:
            self._btn_resume_setup.setVisible(False)
            self._resume_badge.setVisible(False)
            self._resume_hint.setVisible(False)
            self._resume_announced_target = None
            return
        self._btn_resume_setup.setText(text)
        self._btn_resume_setup.setVisible(True)
        self._resume_badge.setVisible(True)
        self._resume_hint.setText(hint)
        self._resume_hint.setVisible(True)
        if self._resume_announced_target != self._resume_target:
            record_onboarding_event("resume_setup_available", step="sign_in", outcome=outcome)
            self._resume_announced_target = self._resume_target

    def _open_resume_setup(self) -> None:
        target = self._resume_target
        if target == REGISTER_DRAFT_KEY:
            record_onboarding_event("resume_setup_opened", step="sign_in", outcome="register")
            self._open_register_dialog()
            return
        if target == ACTIVATE_DRAFT_KEY:
            record_onboarding_event("resume_setup_opened", step="sign_in", outcome="activate")
            self._open_activate_dialog()
            return
        if target == JOIN_TEAM_DRAFT_KEY:
            record_onboarding_event("resume_setup_opened", step="sign_in", outcome="join")
            self._open_join_team_dialog()
            return
        self._refresh_resume_setup_action()

    def _open_register_dialog(self) -> None:
        from app.widgets.register_dialog import RegisterDialog

        dialog = RegisterDialog(self)
        dialog.exec()
        self._refresh_resume_setup_action()

    def _open_join_team_dialog(self) -> None:
        from app.widgets.join_team_dialog import JoinTeamDialog

        dialog = JoinTeamDialog(self)
        if dialog.exec() == int(QDialog.DialogCode.Accepted):
            self.accept()
            return
        self._refresh_resume_setup_action()

    def _open_activate_dialog(self) -> None:
        from app.widgets.activate_dialog import ActivateDialog

        dialog = ActivateDialog(self)
        if dialog.exec() == int(QDialog.DialogCode.Accepted):
            self.accept()
            return
        self._refresh_resume_setup_action()


def ensure_login(app: QApplication) -> bool:
    """Ensure we can reach the API; show login dialog if needed."""
    set_api_config(password="")
    try:
        if get_access_token():
            record_onboarding_event("sign_in_succeeded", step="sign_in", outcome="token_reused")
            return True
    except Exception:
        logger.debug("Pre-login token reuse check failed", exc_info=True)
    dialog = LoginDialog()
    result = int(dialog.exec())
    return result == int(QDialog.DialogCode.Accepted)


__all__ = ["LoginDialog", "ensure_login", "QMessageBox"]
