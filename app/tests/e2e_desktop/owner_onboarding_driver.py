from __future__ import annotations

from pywinauto.controls.uiawrapper import UIAWrapper

from app.tests.e2e_desktop.runtime import DesktopSession
from app.tests.e2e_desktop.ui import child, clear_and_type, click, wait_for_text


def _ensure_checked(checkbox: UIAWrapper) -> None:
    for getter in (
        lambda: checkbox.get_toggle_state(),
        lambda: checkbox.iface_toggle.CurrentToggleState,
    ):
        try:
            if int(getter()) != 0:
                return
        except Exception:
            pass
    click(checkbox)


class QuickStartOnboardingDriver:
    def __init__(self, dialog: UIAWrapper) -> None:
        self.dialog = dialog

    @classmethod
    def wait(cls, session: DesktopSession) -> QuickStartOnboardingDriver:
        return cls(session.window(title_re=".*Get started.*"))

    def choose_register(self) -> None:
        click(child(self.dialog, auto_id="quickStartRegisterButton"))


class RegisterDialogDriver:
    def __init__(self, dialog: UIAWrapper) -> None:
        self.dialog = dialog

    @classmethod
    def wait(cls, session: DesktopSession) -> RegisterDialogDriver:
        return cls(session.window(auto_id="immoRegisterDialog"))

    def submit_registration(
        self,
        *,
        agency_name: str,
        owner_first_name: str,
        owner_last_name: str,
        owner_email: str,
        owner_phone: str,
    ) -> None:
        clear_and_type(child(self.dialog, auto_id="registerAgencyNameInput"), agency_name)
        clear_and_type(child(self.dialog, auto_id="registerLegalNameInput"), f"{agency_name} SARL")
        clear_and_type(
            child(self.dialog, auto_id="registerRegistryNumberInput"),
            f"RC-{agency_name[-8:]}",
        )
        clear_and_type(
            child(self.dialog, auto_id="registerAgencyAddressInput"),
            "12 Rue Didouche Mourad",
        )
        clear_and_type(child(self.dialog, auto_id="registerAgencyCityInput"), "Algiers")
        clear_and_type(child(self.dialog, auto_id="registerAgencyPostalCodeInput"), "16000")
        click(child(self.dialog, auto_id="registerNextButton"))

        clear_and_type(child(self.dialog, auto_id="registerOwnerFirstNameInput"), owner_first_name)
        clear_and_type(child(self.dialog, auto_id="registerOwnerLastNameInput"), owner_last_name)
        clear_and_type(child(self.dialog, auto_id="registerOwnerEmailInput"), owner_email)
        clear_and_type(child(self.dialog, auto_id="registerOwnerPhoneInput"), owner_phone)
        _ensure_checked(child(self.dialog, auto_id="registerTermsAcceptedCheckbox"))
        click(child(self.dialog, auto_id="registerNextButton"))

    def wait_for_request_sent(self) -> None:
        wait_for_text(self.dialog, "Request sent.", timeout=45.0)

    def close_after_success(self) -> None:
        click(child(self.dialog, auto_id="registerNextButton"))


class LoginOnboardingDriver:
    def __init__(self, dialog: UIAWrapper) -> None:
        self.dialog = dialog

    @classmethod
    def wait(cls, session: DesktopSession) -> LoginOnboardingDriver:
        return cls(session.window(auto_id="immoLoginDialog"))

    def open_activation(self) -> None:
        click(child(self.dialog, auto_id="immoLoginActivateButton"))


class ActivateDialogDriver:
    def __init__(self, dialog: UIAWrapper) -> None:
        self.dialog = dialog

    @classmethod
    def wait(cls, session: DesktopSession) -> ActivateDialogDriver:
        return cls(session.window(auto_id="immoActivateDialog"))

    def activate_owner(self, *, email: str, activation_code: str, password: str) -> None:
        clear_and_type(child(self.dialog, auto_id="activateEmailInput"), email)
        clear_and_type(child(self.dialog, auto_id="activateCodeInput"), activation_code)
        click(child(self.dialog, auto_id="activateNextButton"))

        clear_and_type(child(self.dialog, auto_id="activatePasswordInput"), password)
        clear_and_type(child(self.dialog, auto_id="activatePasswordConfirmInput"), password)
        click(child(self.dialog, auto_id="activateNextButton"))

    def wait_for_success(self) -> None:
        wait_for_text(self.dialog, "You're all set!", timeout=45.0)

    def continue_to_app(self) -> None:
        click(child(self.dialog, auto_id="activateNextButton"))
