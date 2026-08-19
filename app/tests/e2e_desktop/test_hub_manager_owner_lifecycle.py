from __future__ import annotations

import os
import re
import time
import uuid
from pathlib import Path

import pytest
import requests

from app.tests.e2e_desktop import backend, owner_onboarding_backend
from app.tests.e2e_desktop.hub_manager_driver import HubManagerAppDriver
from app.tests.e2e_desktop.owner_onboarding_driver import (
    ActivateDialogDriver,
    RegisterDialogDriver,
)
from app.tests.e2e_desktop.ui import wait_for

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.e2e_nightly,
    pytest.mark.hub_manager_owner_lifecycle,
]

_APPROVAL_URL_RE = re.compile(r"Approve:\s*(?P<url>https?://\S+/api/v1/auth/register/approve/\S+/)")
_ACTIVATION_CODE_RE = re.compile(r"Activation code:\s*(?P<code>[A-Z0-9]{8})")
_PROTECTED_OUTPUT = Path(r"C:\ProgramData\ImmoApp\logs\hub-manager-app\cleanup-runtime-logs.json")


def _extract(pattern: re.Pattern[str], body: str, group: str) -> str:
    match = pattern.search(body)
    assert match is not None, f"Expected {group} in queued email body:\n{body}"
    return match.group(group)


def _desktop_config_path(name: str) -> Path:
    root = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    assert root
    local_appdata = Path(root)
    return local_appdata / "ImmoApp" / "config" / name


def _config_files_to_preserve() -> tuple[Path, ...]:
    programdata = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "ImmoApp" / "config"
    return (
        _desktop_config_path("client_api.json"),
        _desktop_config_path("onboarding_drafts_v1.json"),
        programdata / "client_api.json",
        programdata / "onboarding_drafts_v1.json",
    )


def test_hub_manager_drives_real_first_owner_lifecycle_and_protected_action(
    repo_root: Path,
    e2e_client_python: Path,
) -> None:
    platform_admin_email = os.environ.get("IMMOAPP_PLATFORM_ADMIN_EMAIL", "").strip()
    assert platform_admin_email
    suffix = uuid.uuid4().hex[:8]
    agency_name = f"E2E Hub Manager Agency {suffix}"
    owner_email = f"e2e-hub-manager-owner-{suffix}@example.test"
    owner_password = "OwnerStrongPass_123!"
    preserved_config_files = {
        path: path.read_bytes() if path.is_file() else None for path in _config_files_to_preserve()
    }
    for path in preserved_config_files:
        if path.name == "onboarding_drafts_v1.json":
            path.unlink(missing_ok=True)
    snapshot = owner_onboarding_backend.suspend_active_hub_owners_and_admins()
    owner_onboarding_backend.cleanup_owner_registration_email(
        owner_email,
        platform_admin_email=platform_admin_email,
    )
    protected_mtime = _PROTECTED_OUTPUT.stat().st_mtime_ns if _PROTECTED_OUTPUT.exists() else None
    try:
        with HubManagerAppDriver.launch(repo_root, e2e_client_python) as hub_manager:
            window = hub_manager.wait_for_main_window(timeout=60.0)
            hub_manager.wait_for_text(window, "Create owner account", timeout=240.0)
            hub_manager.click_button(
                window,
                "Create owner account",
                automation_id="hubManagerCreateOwnerButton",
            )
            register_window = hub_manager.wait_for_window(
                title="",
                automation_id="immoRegisterDialog",
                timeout=30.0,
            )
            register = RegisterDialogDriver(register_window)
            register.submit_registration(
                agency_name=agency_name,
                owner_first_name="E2E",
                owner_last_name="Hub Owner",
                owner_email=owner_email,
                owner_phone=f"+213555{backend.numeric_suffix(6)}",
            )
            register.wait_for_request_sent()
            owner_onboarding_backend.wait_for_registration_request(owner_email, status="pending")
            register.close_after_success()
            hub_manager.wait_for_text(window, "waiting for approval", timeout=30.0)

            hub_manager.click_button(
                window,
                "Clean Hub logs",
                automation_id="hubManagerAction_cleanup-runtime-logs",
            )
            blocked = hub_manager.wait_for_window(title="Owner account required", timeout=20.0)
            assert "Create and activate the Hub owner account" in hub_manager.window_text(blocked)
            hub_manager.click_button(blocked, "OK")
            if protected_mtime is None:
                assert not _PROTECTED_OUTPUT.exists()
            else:
                assert _PROTECTED_OUTPUT.stat().st_mtime_ns == protected_mtime

            review_email = owner_onboarding_backend.wait_for_email_outbox(
                to_email=platform_admin_email,
                subject_contains="registration review",
                body_contains=owner_email,
            )
            approval_url = _extract(_APPROVAL_URL_RE, review_email.body_text, "url")
            review_response = requests.get(approval_url, timeout=10.0)
            assert review_response.status_code == 200
            approval_response = requests.post(approval_url, timeout=10.0)
            assert approval_response.status_code == 200
            assert "Agency approved" in approval_response.text
            owner_onboarding_backend.wait_for_registration_request(owner_email, status="approved")

            inactive_owner = wait_for(
                "approved inactive Hub Manager owner",
                lambda: owner_onboarding_backend.user_by_email(owner_email),
                timeout=20.0,
            )
            assert inactive_owner["is_owner"] is True
            assert inactive_owner["is_active"] is False
            welcome_email = owner_onboarding_backend.wait_for_email_outbox(
                to_email=owner_email,
                subject_contains="Welcome to ImmoApp",
                body_contains="Activation code:",
            )
            activation_code = _extract(_ACTIVATION_CODE_RE, welcome_email.body_text, "code")

            hub_manager.click_button(
                window,
                "Refresh status",
                automation_id="hubManagerAction_status",
            )
            hub_manager.wait_for_action_text(window, "Refresh status: GO", timeout=220.0)
            hub_manager.wait_for_text(window, "Activate owner account", timeout=30.0)

            hub_manager.click_button(
                window,
                "Clean Hub logs",
                automation_id="hubManagerAction_cleanup-runtime-logs",
            )
            blocked = hub_manager.wait_for_window(title="Owner account required", timeout=20.0)
            assert "Create and activate the Hub owner account" in hub_manager.window_text(blocked)
            hub_manager.click_button(blocked, "OK")
            if protected_mtime is None:
                assert not _PROTECTED_OUTPUT.exists()
            else:
                assert _PROTECTED_OUTPUT.stat().st_mtime_ns == protected_mtime

            hub_manager.click_button(
                window,
                "Activate owner account",
                automation_id="hubManagerActivateOwnerButton",
            )
            activate_window = hub_manager.wait_for_window(
                title="",
                automation_id="immoActivateDialog",
                timeout=30.0,
            )
            activate_text = hub_manager.window_text(activate_window)
            assert "Step 1 of 2 - Verify your email" in activate_text, activate_text
            activation = ActivateDialogDriver(activate_window)
            activation.activate_owner(
                email=owner_email,
                activation_code=activation_code,
                password=owner_password,
            )
            activation.wait_for_success()
            activation.continue_to_app()
            hub_manager.wait_for_text(window, "Owner account is active.", timeout=30.0)

            active_owner = owner_onboarding_backend.user_by_email(owner_email)
            assert active_owner is not None
            assert active_owner["is_owner"] is True
            assert active_owner["is_active"] is True

            hub_manager.click_button(
                window,
                "Clean Hub logs",
                automation_id="hubManagerAction_cleanup-runtime-logs",
            )
            login = hub_manager.wait_for_login(timeout=30.0)
            hub_manager.sign_in(login, username=owner_email, password=owner_password)
            hub_manager.wait_for_action_text(window, "Clean Hub logs: GO", timeout=120.0)
            assert _PROTECTED_OUTPUT.is_file()
            if protected_mtime is not None:
                assert _PROTECTED_OUTPUT.stat().st_mtime_ns > protected_mtime
            deadline = time.monotonic() + 5.0
            evidence_path = Path(
                r"C:\ProgramData\ImmoApp\logs\hub-manager-app\hub_owner_authorization.json"
            )
            while evidence_path.exists() and time.monotonic() < deadline:
                time.sleep(0.1)
            assert not evidence_path.exists()
    finally:
        owner_onboarding_backend.cleanup_owner_registration_email(
            owner_email,
            platform_admin_email=platform_admin_email,
        )
        owner_onboarding_backend.restore_hub_owner_admin_activity(snapshot)
        for path, previous_content in preserved_config_files.items():
            if previous_content is None:
                path.unlink(missing_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(previous_content)
