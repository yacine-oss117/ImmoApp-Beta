from __future__ import annotations

import os
import re
import uuid
from typing import Any

import pytest
import requests

from app.tests.e2e_desktop import backend, owner_onboarding_backend
from app.tests.e2e_desktop.owner_onboarding_driver import (
    ActivateDialogDriver,
    LoginOnboardingDriver,
    QuickStartOnboardingDriver,
    RegisterDialogDriver,
)
from app.tests.e2e_desktop.pages import MainWindowPage, SetupWizardPage
from app.tests.e2e_desktop.ui import wait_for

pytestmark = [pytest.mark.e2e, pytest.mark.e2e_smoke, pytest.mark.owner_onboarding]

_APPROVAL_URL_RE = re.compile(r"Approve:\s*(?P<url>https?://\S+/api/v1/auth/register/approve/\S+/)")
_ACTIVATION_CODE_RE = re.compile(r"Activation code:\s*(?P<code>[A-Z0-9]{8})")


def _extract_approval_url(body_text: str) -> str:
    match = _APPROVAL_URL_RE.search(body_text)
    assert match is not None, f"Approval URL missing from email body:\n{body_text}"
    return match.group("url")


def _extract_activation_code(body_text: str) -> str:
    match = _ACTIVATION_CODE_RE.search(body_text)
    assert match is not None, f"Activation code missing from email body:\n{body_text}"
    return match.group("code")


def test_first_owner_registration_approval_activation_reaches_dashboard(
    e2e_front_door_url: str,
    launch_native_desktop: Any,
) -> None:
    platform_admin_email = os.environ.get("IMMOAPP_PLATFORM_ADMIN_EMAIL", "").strip()
    assert platform_admin_email, (
        "Owner onboarding E2E requires IMMOAPP_PLATFORM_ADMIN_EMAIL. "
        "Use scripts/test_e2e_desktop.ps1 so the isolated E2E runtime env is prepared."
    )

    suffix = uuid.uuid4().hex[:8]
    agency_name = f"E2E Owner Agency {suffix}"
    owner_email = f"e2e-owner-{suffix}@example.test"
    owner_password = "OwnerStrongPass_123!"

    owner_onboarding_backend.cleanup_owner_registration_email(
        owner_email,
        platform_admin_email=platform_admin_email,
    )
    try:
        session = launch_native_desktop(
            preseed_api=False,
            preseed_quick_start=False,
        )
        SetupWizardPage.wait(session).connect_manual(e2e_front_door_url)
        QuickStartOnboardingDriver.wait(session).choose_register()

        register = RegisterDialogDriver.wait(session)
        register.submit_registration(
            agency_name=agency_name,
            owner_first_name="E2E",
            owner_last_name="Owner",
            owner_email=owner_email,
            owner_phone=f"+213555{backend.numeric_suffix(6)}",
        )
        register.wait_for_request_sent()

        request_row = owner_onboarding_backend.wait_for_registration_request(
            owner_email,
            status="pending",
        )
        assert request_row["owner_email"] == owner_email

        review_email = owner_onboarding_backend.wait_for_email_outbox(
            to_email=platform_admin_email,
            subject_contains="registration review",
            body_contains=owner_email,
        )
        approval_url = _extract_approval_url(review_email.body_text)
        review_response = requests.get(approval_url, timeout=10.0)
        assert review_response.status_code == 200
        assert agency_name in review_response.text

        approval_response = requests.post(approval_url, timeout=10.0)
        assert approval_response.status_code == 200
        assert "Agency approved" in approval_response.text
        owner_onboarding_backend.wait_for_registration_request(owner_email, status="approved")

        owner_user = wait_for(
            "approved inactive owner user",
            lambda: owner_onboarding_backend.user_by_email(owner_email),
            timeout=20.0,
        )
        assert owner_user["is_owner"] is True
        assert owner_user["is_active"] is False

        welcome_email = owner_onboarding_backend.wait_for_email_outbox(
            to_email=owner_email,
            subject_contains="Welcome to ImmoApp",
            body_contains="Activation code:",
        )
        activation_code = _extract_activation_code(welcome_email.body_text)

        register.close_after_success()
        login = LoginOnboardingDriver.wait(session)
        login.open_activation()
        activation = ActivateDialogDriver.wait(session)
        activation.activate_owner(
            email=owner_email,
            activation_code=activation_code,
            password=owner_password,
        )
        activation.wait_for_success()
        activation.continue_to_app()

        main = MainWindowPage.wait(session)
        wait_for("owner dashboard after activation", lambda: main.tabs, timeout=30.0)

        active_owner = owner_onboarding_backend.user_by_email(owner_email)
        assert active_owner is not None
        assert active_owner["is_owner"] is True
        assert active_owner["is_active"] is True
    finally:
        owner_onboarding_backend.cleanup_owner_registration_email(
            owner_email,
            platform_admin_email=platform_admin_email,
        )
