from __future__ import annotations

import time

import psutil
import pytest

from app.tests.e2e_desktop.hub_manager_driver import HubManagerAppDriver
from app.tests.e2e_desktop.installed_hub_manager_test_support import (
    assert_installed_build_identity,
    installed_desktop_path,
    installed_hub_manager_path,
)

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.e2e_nightly,
    pytest.mark.installed_hub_manager,
]


def _matching_processes(executable: str) -> list[psutil.Process]:
    expected = executable.lower()
    matches: list[psutil.Process] = []
    for process in psutil.process_iter(("exe",)):
        try:
            if str(process.info.get("exe") or "").lower() == expected:
                matches.append(process)
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            continue
    return matches


def _stop_matching_processes(executable: str) -> None:
    processes = _matching_processes(executable)
    for process in processes:
        try:
            process.terminate()
        except psutil.Error:
            pass
    _, alive = psutil.wait_procs(processes, timeout=10.0)
    for process in alive:
        try:
            process.kill()
        except psutil.Error:
            pass


def test_installed_windows_utilities() -> None:
    installed_exe = installed_hub_manager_path()
    desktop_exe = installed_desktop_path()
    assert_installed_build_identity(installed_exe)
    assert_installed_build_identity(desktop_exe)
    _stop_matching_processes(str(desktop_exe))

    try:
        with HubManagerAppDriver.launch_installed(installed_exe) as hub_manager:
            window = hub_manager.wait_for_main_window(timeout=60.0)
            hub_manager.wait_for_text(window, "Refresh status: GO", timeout=300.0)
            hub_manager.click_button(
                window,
                "Open desktop app",
                automation_id="hubManagerAction_open-desktop",
            )
            hub_manager.wait_for_action_text(window, "Open desktop app: GO", timeout=60.0)

            deadline = time.monotonic() + 45.0
            launched: list[psutil.Process] = []
            while time.monotonic() < deadline:
                launched = _matching_processes(str(desktop_exe))
                if launched:
                    break
                time.sleep(0.25)
            assert launched
            assert all(process.is_running() for process in launched)
    finally:
        _stop_matching_processes(str(desktop_exe))
