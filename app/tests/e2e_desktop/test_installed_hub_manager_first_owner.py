from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
import requests

from app.tests.e2e_desktop.hub_manager_driver import HubManagerAppDriver
from app.tests.e2e_desktop.installed_hub_manager_backend import (
    cleanup_managed_e2e_owner_records,
    cleanup_owner_registration,
    extract_activation_code,
    extract_approval_url,
    managed_user_by_email,
    platform_admin_email,
    restore_hub_owner_admin_activity,
    suspend_active_hub_owners_and_admins,
    wait_for_email,
    wait_for_front_door,
)
from app.tests.e2e_desktop.installed_hub_manager_test_support import (
    assert_installed_build_identity,
    installed_hub_manager_path,
)
from app.tests.e2e_desktop.owner_onboarding_driver import (
    ActivateDialogDriver,
    RegisterDialogDriver,
)

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.e2e_nightly,
    pytest.mark.installed_hub_manager,
    pytest.mark.hub_manager_owner_lifecycle,
]


def _desktop_config_path(name: str) -> Path:
    root = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    assert root
    return Path(root) / "ImmoApp" / "config" / name


def _config_files_to_preserve() -> tuple[Path, ...]:
    programdata = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "ImmoApp" / "config"
    return (
        _desktop_config_path("client_api.json"),
        _desktop_config_path("onboarding_drafts_v1.json"),
        programdata / "client_api.json",
        programdata / "onboarding_drafts_v1.json",
    )


def test_installed_hub_manager_first_owner_lifecycle() -> None:
    installed_exe = installed_hub_manager_path()
    assert_installed_build_identity(installed_exe)
    wait_for_front_door(ready=True)
    admin_email = platform_admin_email()
    suffix = uuid.uuid4().hex[:8]
    agency_name = f"Installed First Owner Agency {suffix}"
    owner_email = f"installed-first-owner-{suffix}@example.test"
    owner_password = "InstalledFirstOwnerStrongPass_123!"
    preserved_config = {
        path: path.read_bytes() if path.is_file() else None for path in _config_files_to_preserve()
    }
    for path in preserved_config:
        if path.name == "onboarding_drafts_v1.json":
            path.unlink(missing_ok=True)
    cleanup_managed_e2e_owner_records()
    snapshot = suspend_active_hub_owners_and_admins()
    cleanup_owner_registration(owner_email, admin_email=admin_email)

    try:
        with HubManagerAppDriver.launch_installed(installed_exe) as hub_manager:
            window = hub_manager.wait_for_main_window(timeout=60.0)
            hub_manager.wait_for_control_enabled(
                window,
                automation_id="hubManagerCreateOwnerButton",
                timeout=300.0,
            )
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
                owner_first_name="Installed",
                owner_last_name="First Owner",
                owner_email=owner_email,
                owner_phone=f"+213555{uuid.uuid4().int % 1_000_000:06d}",
            )
            register.wait_for_request_sent()

            review_email = wait_for_email(
                to_email=admin_email,
                subject_contains="registration review",
                body_contains=owner_email,
            )
            approval_url = extract_approval_url(review_email["body_text"])
            review = requests.get(approval_url, timeout=15.0)
            assert review.status_code == 200
            approval = requests.post(approval_url, timeout=15.0)
            assert approval.status_code == 200

            inactive_owner = managed_user_by_email(owner_email)
            assert inactive_owner is not None
            assert inactive_owner["is_owner"] is True
            assert inactive_owner["is_active"] is False
            activation_email = wait_for_email(
                to_email=owner_email,
                subject_contains="Welcome to ImmoApp",
                body_contains="Activation code:",
            )
            activation_code = extract_activation_code(activation_email["body_text"])

            register.close_after_success()
            hub_manager.wait_for_control_enabled(
                window,
                automation_id="hubManagerActivateOwnerButton",
                timeout=60.0,
            )
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
            activation = ActivateDialogDriver(activate_window)
            activation.activate_owner(
                email=owner_email,
                activation_code=activation_code,
                password=owner_password,
            )
            activation.wait_for_success()
            activation.continue_to_app()
            hub_manager.wait_for_text(window, "Owner account is active.", timeout=60.0)

            active_owner = managed_user_by_email(owner_email)
            assert active_owner is not None
            assert active_owner["is_owner"] is True
            assert active_owner["is_active"] is True
    finally:
        cleanup_owner_registration(owner_email, admin_email=admin_email)
        restore_hub_owner_admin_activity(snapshot)
        for path, previous in preserved_config.items():
            if previous is None:
                path.unlink(missing_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(previous)
