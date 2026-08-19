from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, cast

import psutil
from pywinauto import Application, Desktop

SUPPORT_OUTPUT_DIR = Path(r"C:\ProgramData\ImmoApp\logs\hub-manager-app")


class HubManagerAppDriver:
    def __init__(self, process: subprocess.Popen[str]) -> None:
        self.process = process

    def __enter__(self) -> HubManagerAppDriver:
        return self

    def __exit__(self, _exc_type: object, _exc: object, _traceback: object) -> None:
        self.close()

    @classmethod
    def launch(
        cls,
        repo_root: Path,
        e2e_client_python: Path,
        *,
        env_overrides: dict[str, str] | None = None,
    ) -> HubManagerAppDriver:
        env = os.environ.copy()
        env["QT_ENABLE_HIGHDPI_SCALING"] = "0"
        env["IMMOAPP_SERVER_PYTHON"] = sys.executable
        if env_overrides:
            env.update(env_overrides)
        process = subprocess.Popen(
            [str(e2e_client_python), "-m", "app.hub_manager_app"],
            cwd=repo_root,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        return cls(process)

    @classmethod
    def launch_installed(cls, installed_exe: Path) -> HubManagerAppDriver:
        env = os.environ.copy()
        env["QT_ENABLE_HIGHDPI_SCALING"] = "0"
        env["IMMOAPP_SERVER_PYTHON"] = sys.executable
        process = subprocess.Popen(
            [str(installed_exe)],
            cwd=installed_exe.parent,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        return cls(process)

    def close(self) -> None:
        if self.process.poll() is None:
            _kill_process_id(self.process.pid)
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=10)

    def wait_for_login(self, timeout: float = 30.0) -> Any:
        return self.wait_for_window(automation_id="hubManagerLoginDialog", timeout=timeout)

    def wait_for_main_window(self, timeout: float = 45.0) -> Any:
        return self.wait_for_window(automation_id="hub-manager-window", timeout=timeout)

    def find_main_window(self) -> Any | None:
        return self.find_window(automation_id="hub-manager-window")

    def wait_for_window(
        self,
        *,
        title: str = "ImmoApp Hub Manager",
        automation_id: str = "",
        timeout: float = 30.0,
    ) -> Any:
        deadline = time.monotonic() + timeout
        last_seen = ""
        while time.monotonic() < deadline:
            candidate_pids = _process_tree_ids(self.process.pid)
            try:
                roots = [
                    root
                    for root in Desktop(backend="uia").windows()
                    if int(root.process_id()) in candidate_pids
                ]
                for descend in (False, True):
                    for root in roots:
                        candidates = root.descendants() if descend else [root]
                        for candidate in candidates:
                            candidate_pid = int(candidate.process_id())
                            candidate_title = candidate.window_text()
                            candidate_auto_id = str(candidate.element_info.automation_id or "")
                            last_seen += (
                                f"\n{candidate_title}|{candidate_auto_id}|pid={candidate_pid}"
                            )
                            if title and candidate_title != title:
                                continue
                            if automation_id and not candidate_auto_id.endswith(automation_id):
                                continue
                            if not candidate.is_visible():
                                continue
                            Application(backend="uia").connect(process=candidate_pid)
                            return root
            except Exception:
                time.sleep(0.2)
            time.sleep(0.2)
        raise AssertionError(
            f"Hub Manager window did not appear: title={title!r} auto_id={automation_id!r}"
            f"\nSeen:{last_seen}"
        )

    def find_window(self, *, title: str = "", automation_id: str = "") -> Any | None:
        candidate_pids = _process_tree_ids(self.process.pid)
        try:
            roots = [
                root
                for root in Desktop(backend="uia").windows()
                if int(root.process_id()) in candidate_pids
            ]
            for descend in (False, True):
                for root in roots:
                    candidates = root.descendants() if descend else [root]
                    for candidate in candidates:
                        if title and candidate.window_text() != title:
                            continue
                        candidate_auto_id = str(candidate.element_info.automation_id or "")
                        if automation_id and not candidate_auto_id.endswith(automation_id):
                            continue
                        if not candidate.is_visible():
                            continue
                        return root
        except Exception:
            return None
        return None

    def window_text(self, window: object) -> str:
        texts: list[str] = []
        for control in window.descendants():  # type: ignore[attr-defined]
            try:
                value = control.window_text()
            except Exception:
                continue
            if value:
                texts.append(str(value))
        return "\n".join(texts)

    def wait_for_text(self, window: object, expected: str, timeout: float = 60.0) -> None:
        deadline = time.monotonic() + timeout
        last_text = ""
        while time.monotonic() < deadline:
            last_text = self.window_text(window)
            if expected in last_text:
                return
            time.sleep(0.25)
        raise AssertionError(f"Expected Hub Manager text not found: {expected!r}\n{last_text}")

    def wait_for_text_absent(self, window: object, unexpected: str, timeout: float = 20.0) -> None:
        deadline = time.monotonic() + timeout
        last_text = ""
        while time.monotonic() < deadline:
            last_text = self.window_text(window)
            if unexpected not in last_text:
                return
            time.sleep(0.25)
        raise AssertionError(
            f"Unexpected Hub Manager text still present: {unexpected!r}\n{last_text}"
        )

    def wait_for_action_text(
        self,
        window: object,
        expected: str,
        *,
        timeout: float = 90.0,
    ) -> None:
        deadline = time.monotonic() + timeout
        last_text = ""
        while time.monotonic() < deadline:
            last_text = self.window_text(window)
            if expected in last_text:
                self.dismiss_message_box_if_present(title="Hub action did not complete")
                return
            self.dismiss_message_box_if_present(title="Hub action did not complete")
            time.sleep(0.25)
        raise AssertionError(
            f"Expected Hub Manager action text not found: {expected!r}\n{last_text}"
        )

    def wait_for_control_enabled(
        self,
        window: object,
        *,
        automation_id: str,
        timeout: float = 240.0,
    ) -> None:
        dynamic_window = cast(Any, window)
        root = Desktop(backend="uia").window(handle=dynamic_window.handle)
        control = root.child_window(
            predicate_func=lambda element: str(element.automation_id or "").endswith(automation_id),
        )
        try:
            control.wait("exists visible enabled", timeout=timeout, retry_interval=0.25)
        except Exception as exc:
            raise AssertionError(
                f"Hub Manager control did not become enabled: {automation_id}"
            ) from exc

    def dismiss_message_box_if_present(self, *, title: str) -> None:
        dialog = self.find_window(title=title)
        if dialog is None:
            return
        try:
            self.click_button(dialog, "OK")
        except AssertionError:
            try:
                dialog.close()
            except Exception:
                pass

    def set_text(self, window: object, *, automation_id: str, text: str) -> None:
        control = self.descendant(window, automation_id=automation_id, control_type="Edit")
        self._replace_edit_text(control, text)

    def set_first_edit_text(self, window: object, text: str) -> None:
        controls = window.descendants(control_type="Edit")  # type: ignore[attr-defined]
        if not controls:
            raise AssertionError("Dialog did not contain an editable text field.")
        self._replace_edit_text(controls[0], text)

    @staticmethod
    def _replace_edit_text(control: object, text: str) -> None:
        try:
            control.set_focus()  # type: ignore[attr-defined]
        except Exception:
            pass
        try:
            control.set_edit_text(text)  # type: ignore[attr-defined]
        except Exception:
            control.click_input()  # type: ignore[attr-defined]
            control.type_keys("^a{BACKSPACE}")  # type: ignore[attr-defined]
            control.type_keys(text, with_spaces=True)  # type: ignore[attr-defined]

    def click_button(
        self,
        window: object,
        label: str = "",
        *,
        automation_id: str = "",
        physical: bool = False,
    ) -> None:
        button = self._button(window, label=label, automation_id=automation_id)
        self._prepare_button(button)
        if physical:
            try:
                button.click_input()
            except Exception:
                button.invoke()
        else:
            try:
                button.invoke()
            except Exception:
                button.click_input()
        time.sleep(0.3)

    def press_button(
        self,
        window: object,
        label: str = "",
        *,
        automation_id: str = "",
    ) -> None:
        button = self._button(window, label=label, automation_id=automation_id)
        self._prepare_button(button)
        if not button.has_keyboard_focus():
            raise AssertionError(f"Button did not receive keyboard focus: {label or automation_id}")
        button.type_keys("{SPACE}")
        time.sleep(0.3)

    def scroll_main(self, window: object, *, direction: str) -> None:
        if direction not in {"up", "down"}:
            raise ValueError(f"Unsupported Hub Manager scroll direction: {direction}")
        scroll_area = self.descendant(window, automation_id="hub-main-scroll")
        try:
            scroll_area.scroll(direction, "page", count=12)
        except AttributeError:
            wheel_distance = -30 if direction == "down" else 30
            scroll_area.wheel_mouse_input(wheel_dist=wheel_distance)
        time.sleep(0.3)

    @staticmethod
    def _prepare_button(button: object) -> None:
        try:
            button.scroll_into_view()  # type: ignore[attr-defined]
        except Exception:
            pass
        try:
            button.set_focus()  # type: ignore[attr-defined]
        except Exception:
            pass

    @staticmethod
    def _button(window: object, *, label: str, automation_id: str) -> Any:
        buttons = window.descendants(control_type="Button")  # type: ignore[attr-defined]
        button = None
        if automation_id:
            for candidate in buttons:
                if str(candidate.element_info.automation_id or "").endswith(automation_id):
                    button = candidate
                    break
        else:
            for candidate in buttons:
                candidate_label = candidate.window_text().replace("&", "")
                if candidate_label == label:
                    button = candidate
                    break
        if button is None:
            available = "\n".join(
                f"{candidate.window_text()}|{candidate.element_info.automation_id}"
                for candidate in buttons
            )
            raise AssertionError(f"Button not found: {label or automation_id}\n{available}")
        return button

    def descendant(self, window: object, *, automation_id: str, control_type: str = "") -> Any:
        dynamic_window = cast(Any, window)
        controls = (
            dynamic_window.descendants(control_type=control_type)
            if control_type
            else dynamic_window.descendants()
        )
        for candidate in controls:
            candidate_auto_id = str(candidate.element_info.automation_id or "")
            if candidate_auto_id.endswith(automation_id):
                return candidate
        available = "\n".join(
            f"{candidate.window_text()}|{candidate.element_info.automation_id}"
            for candidate in controls
        )
        raise AssertionError(f"Control automation id not found: {automation_id}\n{available}")

    def sign_in_owner(self, login_window: object) -> None:
        self.sign_in(login_window, username="owner", password="admin")

    def sign_in(self, login_window: object, *, username: str, password: str) -> None:
        try:
            login_window.set_focus()  # type: ignore[attr-defined]
        except Exception:
            pass
        self.wait_for_text(login_window, "Owner/admin sign in", timeout=10.0)
        self.set_text(login_window, automation_id="hubManagerLoginUsername", text=username)
        self.set_text(login_window, automation_id="hubManagerLoginPassword", text=password)
        login_button = self.descendant(
            login_window, automation_id="hubManagerLoginButton", control_type="Button"
        )
        try:
            login_button.set_focus()
        except Exception:
            pass
        try:
            login_button.click_input()
        except Exception:
            login_button.invoke()
        time.sleep(0.5)


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as handle:
        data = json.load(handle)
    assert isinstance(data, dict)
    return data


def newest_support_bundle(*, output_dir: Path = SUPPORT_OUTPUT_DIR, after_timestamp: float) -> Path:
    candidates = [
        path
        for path in output_dir.glob("immoapp_support_*.zip")
        if path.stat().st_mtime >= after_timestamp
    ]
    if not candidates:
        raise AssertionError(f"No new support bundle zip was created in {output_dir}")
    return max(candidates, key=lambda path: path.stat().st_mtime)


def _process_tree_ids(root_process_id: int) -> set[int]:
    process_ids = {int(root_process_id)}
    try:
        parent = psutil.Process(int(root_process_id))
        process_ids.update(int(child.pid) for child in parent.children(recursive=True))
    except psutil.Error:
        pass
    return process_ids


def _kill_process_id(process_id: int) -> None:
    subprocess.run(
        ["taskkill", "/PID", str(process_id), "/T", "/F"],
        capture_output=True,
        text=True,
        check=False,
    )
