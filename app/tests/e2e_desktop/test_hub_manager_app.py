from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.tests.e2e_desktop.hub_manager_driver import HubManagerAppDriver

pytestmark = [pytest.mark.e2e, pytest.mark.e2e_smoke]


@pytest.mark.hub_manager_auth
def test_hub_manager_rejects_wrong_password_and_employee_login(
    repo_root: Path,
    e2e_client_python: Path,
    make_backend_user: Any,
) -> None:
    employee = make_backend_user(prefix="hub_mgr_employee")
    with HubManagerAppDriver.launch(repo_root, e2e_client_python) as hub_manager:
        window = hub_manager.wait_for_main_window()
        hub_manager.wait_for_text(window, "Refresh status: GO", timeout=220.0)

        hub_manager.click_button(
            window, "Clean Hub logs", automation_id="hubManagerAction_cleanup-runtime-logs"
        )
        login = hub_manager.wait_for_login()

        hub_manager.sign_in(login, username="owner", password="wrong-password")
        hub_manager.wait_for_text(login, "Owner/admin sign-in failed", timeout=45.0)
        assert "Clean Hub logs: GO" not in hub_manager.window_text(window)

        hub_manager.sign_in(login, username=employee.username, password=employee.password)
        hub_manager.wait_for_text(login, "not allowed to manage the Hub", timeout=45.0)
        assert "Clean Hub logs: GO" not in hub_manager.window_text(window)
