from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

import psutil
from pywinauto import Application, Desktop
from pywinauto.base_wrapper import BaseWrapper
from pywinauto.controls.uiawrapper import UIAWrapper

from app.tests.e2e_desktop.ui import (
    automation_id_matches,
    control_tree_as_text,
    matching_descendants,
    wait_for,
    write_text_file,
)

MIN_API_TIMEOUT_SECONDS = 3.0
MAX_API_TIMEOUT_SECONDS = 60.0
DEFAULT_API_TIMEOUT_SECONDS = 12.0

_KNOWN_APP_DIALOG_IDS = frozenset(
    {
        "immoMainWindow",
        "immoLoginDialog",
        "immoImportDialog",
        "agencySettingsDialog",
        "securityControlsDialog",
        "immoSetupWizardDialog",
        "NotificationsDialog",
    }
)


@dataclass(frozen=True)
class DesktopLaunchOptions:
    client_python: Path
    repo_root: Path
    appdata_root: Path
    artifact_dir: Path
    qsettings_org: str
    qsettings_app: str
    base_url: str
    username: str | None = None
    preseed_api: bool = True
    preseed_quick_start: bool = True
    server_log_path: Path | None = None
    api_timeout_seconds: float = DEFAULT_API_TIMEOUT_SECONDS


def validate_api_timeout_seconds(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError("Desktop E2E API timeout must be a numeric value.")
    try:
        timeout = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Desktop E2E API timeout must be a numeric value.") from exc
    if not math.isfinite(timeout):
        raise ValueError("Desktop E2E API timeout must be finite.")
    if timeout < MIN_API_TIMEOUT_SECONDS or timeout > MAX_API_TIMEOUT_SECONDS:
        raise ValueError(
            "Desktop E2E API timeout must be between "
            f"{MIN_API_TIMEOUT_SECONDS:g} and {MAX_API_TIMEOUT_SECONDS:g} seconds."
        )
    return timeout


def format_api_timeout_seconds(value: object) -> str:
    timeout = validate_api_timeout_seconds(value)
    return f"{timeout:g}"


class DesktopSession:
    def __init__(
        self,
        *,
        options: DesktopLaunchOptions,
        process: subprocess.Popen[str],
        gui_pid: int,
        stdio_handle: TextIO | None,
    ) -> None:
        self.options = options
        self.process = process
        self.gui_pid = int(gui_pid)
        self._stdio_handle = stdio_handle
        self.app = Application(backend="uia").connect(process=self.gui_pid)

    @property
    def _candidate_pids(self) -> set[int]:
        return {int(self.process.pid), int(self.gui_pid)}

    def _top_windows(self) -> list[UIAWrapper]:
        return [
            wrapper
            for wrapper in Desktop(backend="uia").windows()
            if isinstance(wrapper, UIAWrapper)
            and int(getattr(wrapper.element_info, "process_id", 0) or 0) in self._candidate_pids
        ]

    def _candidate_windows(self) -> list[UIAWrapper]:
        candidates: list[UIAWrapper] = []
        seen_handles: set[int] = set()
        for root in self._top_windows():
            descendants: list[UIAWrapper] = []
            try:
                descendants = [
                    wrapper for wrapper in root.descendants() if isinstance(wrapper, UIAWrapper)
                ]
            except Exception:
                try:
                    descendants = [
                        wrapper for wrapper in root.children() if isinstance(wrapper, UIAWrapper)
                    ]
                except Exception:
                    descendants = []
            for wrapper in [root, *descendants]:
                if not isinstance(wrapper, UIAWrapper):
                    continue
                handle = int(getattr(wrapper, "handle", 0) or 0)
                if handle and handle in seen_handles:
                    continue
                if handle:
                    seen_handles.add(handle)
                candidates.append(wrapper)
        return candidates

    def _match_window(
        self,
        wrapper: UIAWrapper,
        *,
        auto_id: str | None,
        title_re: str | None,
        class_name: str | None,
    ) -> bool:
        if not wrapper.is_visible():
            return False
        info = wrapper.element_info
        wrapper_auto_id = str(getattr(info, "automation_id", "") or "")
        wrapper_title = str(getattr(info, "name", "") or "")
        wrapper_class = str(getattr(info, "class_name", "") or "")
        if auto_id and not automation_id_matches(wrapper_auto_id, auto_id):
            return False
        if title_re and re.search(title_re, wrapper_title) is None:
            return False
        if class_name and wrapper_class != class_name:
            return False
        return True

    def window(
        self,
        *,
        auto_id: str | None = None,
        title_re: str | None = None,
        class_name: str | None = None,
        timeout: float = 20.0,
    ) -> UIAWrapper:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise AssertionError(
                    f"Desktop app exited early with code {self.process.returncode}. "
                    f"Artifacts: {self.options.artifact_dir}"
                )
            for wrapper in self._candidate_windows():
                if self._match_window(
                    wrapper,
                    auto_id=auto_id,
                    title_re=title_re,
                    class_name=class_name,
                ):
                    return wrapper
            time.sleep(0.2)
        raise AssertionError(
            f"Timed out waiting for desktop window auto_id={auto_id!r} "
            f"title_re={title_re!r} class_name={class_name!r}"
        )

    def try_window(
        self,
        *,
        auto_id: str | None = None,
        title_re: str | None = None,
        class_name: str | None = None,
        timeout: float = 2.0,
    ) -> UIAWrapper | None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                return None
            for wrapper in self._candidate_windows():
                if self._match_window(
                    wrapper,
                    auto_id=auto_id,
                    title_re=title_re,
                    class_name=class_name,
                ):
                    return wrapper
            time.sleep(0.2)
        return None

    def message_box(self, *, timeout: float = 6.0) -> UIAWrapper:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for root in self._top_windows():
                try:
                    descendants = [
                        wrapper for wrapper in root.descendants() if isinstance(wrapper, UIAWrapper)
                    ]
                except Exception:
                    try:
                        descendants = [
                            wrapper
                            for wrapper in root.children()
                            if isinstance(wrapper, UIAWrapper)
                        ]
                    except Exception:
                        descendants = []
                candidates = [root, *descendants]
                for wrapper in candidates:
                    if not isinstance(wrapper, UIAWrapper) or not wrapper.is_visible():
                        continue
                    automation_id = str(getattr(wrapper.element_info, "automation_id", "") or "")
                    title = str(getattr(wrapper.element_info, "name", "") or "")
                    control_type = str(getattr(wrapper.element_info, "control_type", "") or "")
                    if any(
                        automation_id_matches(automation_id, known)
                        for known in _KNOWN_APP_DIALOG_IDS
                    ):
                        continue
                    if automation_id_matches(automation_id, "QMessageBox") or automation_id_matches(
                        automation_id, "QApplication.QMessageBox"
                    ):
                        return wrapper
                    if control_type == "Window" and title and title != "Yacine Real Estate Matcher":
                        return wrapper
            time.sleep(0.2)
        raise AssertionError("Timed out waiting for a desktop message box")

    def element(
        self,
        *,
        auto_id: str | None = None,
        title: str | None = None,
        title_re: str | None = None,
        control_type: str | None = None,
        timeout: float = 10.0,
        visible_only: bool = True,
        found_index: int = 0,
    ) -> UIAWrapper:
        def _resolve() -> UIAWrapper | None:
            for root in self._candidate_windows():
                root_auto_id = str(getattr(root.element_info, "automation_id", "") or "")
                root_title = str(getattr(root.element_info, "name", "") or "")
                root_control_type = str(getattr(root.element_info, "control_type", "") or "")
                if (
                    (auto_id is None or automation_id_matches(root_auto_id, auto_id))
                    and (title is None or root_title == title)
                    and (title_re is None or re.search(title_re, root_title) is not None)
                    and (control_type is None or root_control_type == control_type)
                    and ((not visible_only) or root.is_visible())
                ):
                    if found_index == 0:
                        return root
                    found_index_matches = matching_descendants(
                        root,
                        auto_id=auto_id,
                        title=title,
                        title_re=title_re,
                        control_type=control_type,
                        visible_only=visible_only,
                    )
                    if found_index < len(found_index_matches):
                        return found_index_matches[found_index]
                matches = matching_descendants(
                    root,
                    auto_id=auto_id,
                    title=title,
                    title_re=title_re,
                    control_type=control_type,
                    visible_only=visible_only,
                )
                if found_index < len(matches):
                    return matches[found_index]
            return None

        return wait_for(
            f"desktop element auto_id={auto_id!r} title={title!r} title_re={title_re!r}",
            _resolve,
            timeout=timeout,
        )

    def capture_diagnostics(self, label: str) -> None:
        artifact_dir = self.options.artifact_dir
        artifact_dir.mkdir(parents=True, exist_ok=True)

        screenshot_path = artifact_dir / f"{label}.png"
        try:
            from PIL import ImageGrab

            image = ImageGrab.grab(all_screens=True)
            image.save(screenshot_path)
        except Exception as exc:  # pragma: no cover - best-effort diagnostics
            write_text_file(
                artifact_dir / f"{label}_screenshot_error.txt",
                f"{type(exc).__name__}: {exc}",
            )

        windows_path = artifact_dir / f"{label}_windows.txt"
        window_chunks: list[str] = []
        for wrapper in self._top_windows():
            try:
                process_id = int(getattr(wrapper.element_info, "process_id", 0) or 0)
                title = str(getattr(wrapper.element_info, "name", "") or "")
                automation_id = str(getattr(wrapper.element_info, "automation_id", "") or "")
                class_name = str(getattr(wrapper.element_info, "class_name", "") or "")
                window_chunks.append(
                    f"PID: {process_id}\nTITLE: {title}\nAUTO_ID: {automation_id}\n"
                    f"CLASS: {class_name}\nPROCESS: {_process_name(process_id)}\n"
                    f"{control_tree_as_text(wrapper)}"
                )
            except Exception as exc:  # pragma: no cover - best-effort diagnostics
                window_chunks.append(f"CONTROL TREE ERROR: {type(exc).__name__}: {exc}")
        write_text_file(windows_path, "\n\n".join(window_chunks))

        write_text_file(
            artifact_dir / f"{label}_process_tree.txt",
            _process_tree_as_text(self.process.pid),
        )
        write_text_file(
            artifact_dir / f"{label}_visible_desktop_windows.txt",
            _visible_desktop_windows_as_text(),
        )
        write_text_file(
            artifact_dir / f"{label}_launch_environment.txt",
            _launch_environment_as_text(
                self.options,
                process=self.process,
                gui_pid=self.gui_pid,
            ),
        )

        stdout_path = artifact_dir / f"{label}_client_stdio_tail.txt"
        if self._stdio_handle is not None:
            try:
                self._stdio_handle.flush()
            except Exception:
                pass
            stdio_log = Path(getattr(self._stdio_handle, "name", ""))
            if stdio_log.exists():
                write_text_file(stdout_path, _tail_text(stdio_log))

        config_dir = self.options.appdata_root / "config"
        for name in ("client_api.json", "onboarding_state.json"):
            source = config_dir / name
            if source.exists():
                shutil.copy2(source, artifact_dir / name)

        app_log = self.options.appdata_root / "logs" / "app.log"
        if app_log.exists():
            write_text_file(artifact_dir / f"{label}_app_log_tail.txt", _tail_text(app_log))

        if self.options.server_log_path and self.options.server_log_path.exists():
            write_text_file(
                artifact_dir / f"{label}_server_log_tail.txt",
                _tail_text(self.options.server_log_path),
            )

    def close(self) -> None:
        for candidate in (
            lambda: self.try_window(auto_id="immoMainWindow", timeout=1.0),
            lambda: self.try_window(auto_id="immoImportDialog", timeout=1.0),
            lambda: self.try_window(auto_id="immoLoginDialog", timeout=1.0),
            lambda: self.try_window(auto_id="immoSetupWizardDialog", timeout=1.0),
        ):
            wrapper = candidate()
            if wrapper is None:
                continue
            try:
                wrapper.close()
            except Exception:
                try:
                    wrapper.type_keys("%{F4}")
                except Exception:
                    pass
            if _wait_for_process_exit(self.process, timeout=6.0):
                break
        if self.process.poll() is None:
            self.process.terminate()
            if not _wait_for_process_exit(self.process, timeout=5.0):
                self.process.kill()
                _wait_for_process_exit(self.process, timeout=3.0)
        _kill_child_processes(self.process.pid)
        if self._stdio_handle is not None:
            try:
                self._stdio_handle.close()
            except Exception:
                pass


def launch_desktop(options: DesktopLaunchOptions) -> DesktopSession:
    appdata_root = options.appdata_root
    artifact_dir = options.artifact_dir
    appdata_root.mkdir(parents=True, exist_ok=True)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    _kill_stale_desktop_launches(options.client_python)
    for rel_path in (
        Path("cache"),
        Path("config"),
        Path("logs"),
        Path("media"),
        Path("tmp"),
        Path("tools"),
        Path("backups"),
    ):
        (appdata_root / rel_path).mkdir(parents=True, exist_ok=True)

    if options.preseed_api:
        config_payload = {"base_url": options.base_url}
        if options.username:
            config_payload["username"] = options.username
        config_payload["remember_session"] = "1"
        write_text_file(
            appdata_root / "config" / "client_api.json",
            json.dumps(config_payload, indent=2, ensure_ascii=True),
        )
    if options.preseed_quick_start:
        write_text_file(
            appdata_root / "config" / "onboarding_state.json",
            json.dumps({"quick_start_seen": True}, indent=2, ensure_ascii=True),
        )

    stdio_path = artifact_dir / "client-stdio.log"
    stdio_handle = stdio_path.open("w", encoding="utf-8")
    env = os.environ.copy()
    env["IMMOAPP_APPDATA_ROOT"] = str(appdata_root)
    env["IMMOAPP_QSETTINGS_ORG"] = options.qsettings_org
    env["IMMOAPP_QSETTINGS_APP"] = options.qsettings_app
    env["IMMOAPP_DISABLE_KEYRING"] = "1"
    env["IMMOAPP_E2E_TEST_MODE"] = "1"
    env["IMMOAPP_API_TIMEOUT"] = format_api_timeout_seconds(options.api_timeout_seconds)
    for inherited_auth_name in (
        "IMMOAPP_API_BASE_URL",
        "IMMOAPP_API_USERNAME",
        "IMMOAPP_API_PASSWORD",
        "IMMOAPP_API_TOKEN",
        "IMMOAPP_API_SCHEMA",
    ):
        env.pop(inherited_auth_name, None)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.pop("PYTHONPYCACHEPREFIX", None)
    env["PYTHONUNBUFFERED"] = "1"
    process = subprocess.Popen(
        [str(options.client_python), "-u", "app/main.py"],
        cwd=options.repo_root,
        env=env,
        stdout=stdio_handle,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        gui_pid = _resolve_gui_pid(process.pid)
        session = DesktopSession(
            options=options,
            process=process,
            gui_pid=gui_pid,
            stdio_handle=stdio_handle,
        )
        _wait_for_initial_surface(session)
        return session
    except Exception:
        _capture_launch_exception_diagnostics(
            options=options,
            process=process,
            stdio_handle=stdio_handle,
            gui_pid=locals().get("gui_pid"),
        )
        _terminate_process_tree(process)
        try:
            stdio_handle.close()
        except Exception:
            pass
        raise


def _wait_for_initial_surface(session: DesktopSession) -> BaseWrapper:
    deadline = time.monotonic() + 30.0
    while time.monotonic() < deadline:
        for candidate in (
            lambda: session.try_window(auto_id="immoSetupWizardDialog", timeout=0.3),
            lambda: session.try_window(title_re=".*Get started.*", timeout=0.3),
            lambda: session.try_window(auto_id="immoLoginDialog", timeout=0.3),
            lambda: session.try_window(auto_id="immoMainWindow", timeout=0.3),
        ):
            wrapper = candidate()
            if wrapper is not None:
                return wrapper
        if session.process.poll() is not None:
            session.capture_diagnostics("launch_failed")
            raise AssertionError(
                f"Desktop app exited during startup with code {session.process.returncode}. "
                f"Artifacts: {session.options.artifact_dir}"
            )
        time.sleep(0.2)
    session.capture_diagnostics("launch_timeout")
    raise AssertionError(
        f"Timed out waiting for desktop startup surface. Artifacts: {session.options.artifact_dir}"
    )


def _wait_for_process_exit(process: subprocess.Popen[str], *, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return True
        time.sleep(0.2)
    return process.poll() is not None


def _resolve_gui_pid(parent_pid: int, *, timeout: float = 10.0) -> int:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            parent = psutil.Process(parent_pid)
            children = parent.children(recursive=True)
        except psutil.Error:
            return int(parent_pid)
        python_children = [child for child in children if child.name().lower().startswith("python")]
        if python_children:
            newest = max(python_children, key=lambda child: child.create_time())
            return int(newest.pid)
        time.sleep(0.2)
    return int(parent_pid)


def _kill_child_processes(parent_pid: int) -> None:
    try:
        parent = psutil.Process(parent_pid)
        children = parent.children(recursive=True)
    except psutil.Error:
        return
    for child in reversed(children):
        try:
            child.terminate()
        except psutil.Error:
            continue
    _, alive = psutil.wait_procs(children, timeout=3.0)
    for child in alive:
        try:
            child.kill()
        except psutil.Error:
            continue


def _terminate_process_tree(process: subprocess.Popen[str]) -> None:
    processes: list[psutil.Process] = []
    try:
        parent = psutil.Process(process.pid)
        processes.extend(parent.children(recursive=True))
        processes.append(parent)
    except psutil.Error:
        processes = []

    for candidate in processes:
        try:
            candidate.terminate()
        except psutil.Error:
            continue
    _, alive = psutil.wait_procs(processes, timeout=5.0)
    for candidate in alive:
        try:
            candidate.kill()
        except psutil.Error:
            continue

    if process.poll() is None:
        process.terminate()
        if not _wait_for_process_exit(process, timeout=2.0):
            process.kill()
            _wait_for_process_exit(process, timeout=2.0)


def _kill_stale_desktop_launches(client_python: Path) -> None:
    expected_exe = str(client_python).strip().lower()
    stale_parents: list[psutil.Process] = []
    for process in psutil.process_iter(["pid", "exe", "cmdline"]):
        try:
            exe = str(process.info.get("exe") or "").strip().lower()
            cmdline = [str(part) for part in (process.info.get("cmdline") or [])]
        except (psutil.Error, OSError):
            continue
        normalized_cmdline = [part.replace("\\", "/").lower() for part in cmdline]
        expected_in_cmdline = any(part.strip().lower() == expected_exe for part in cmdline)
        if exe != expected_exe and not expected_in_cmdline:
            continue
        if not any("app/main.py" in part for part in normalized_cmdline):
            continue
        stale_parents.append(process)

    for process in stale_parents:
        try:
            for child in reversed(process.children(recursive=True)):
                try:
                    child.terminate()
                except psutil.Error:
                    continue
            process.terminate()
        except psutil.Error:
            continue

    if stale_parents:
        psutil.wait_procs(stale_parents, timeout=5.0)
        for process in stale_parents:
            try:
                if process.is_running():
                    for child in reversed(process.children(recursive=True)):
                        try:
                            child.kill()
                        except psutil.Error:
                            continue
                    process.kill()
            except psutil.Error:
                continue


def _process_name(process_id: int) -> str:
    if process_id <= 0:
        return ""
    try:
        return str(psutil.Process(process_id).name())
    except psutil.Error:
        return ""


def _process_tree_as_text(root_pid: int) -> str:
    lines: list[str] = []
    try:
        root = psutil.Process(root_pid)
        processes = [root, *root.children(recursive=True)]
    except psutil.Error as exc:
        return f"PROCESS TREE ERROR: {type(exc).__name__}: {exc}"
    for process in processes:
        try:
            lines.append(
                "PID={pid} PPID={ppid} NAME={name} STATUS={status} EXITED={exited} CMD={cmd}".format(
                    pid=process.pid,
                    ppid=process.ppid(),
                    name=process.name(),
                    status=process.status(),
                    exited=not process.is_running(),
                    cmd=_redact(" ".join(process.cmdline())),
                )
            )
        except psutil.Error as exc:
            lines.append(f"PID={process.pid} PROCESS ERROR: {type(exc).__name__}: {exc}")
    return "\n".join(lines)


def _visible_desktop_windows_as_text() -> str:
    lines: list[str] = []
    try:
        windows = Desktop(backend="uia").windows()
    except Exception as exc:  # pragma: no cover - best-effort diagnostics
        return f"DESKTOP WINDOWS ERROR: {type(exc).__name__}: {exc}"
    for wrapper in windows:
        if not isinstance(wrapper, UIAWrapper):
            continue
        try:
            if not wrapper.is_visible():
                continue
            info = wrapper.element_info
            process_id = int(getattr(info, "process_id", 0) or 0)
            lines.append(
                "PID={pid} PROCESS={process} TITLE={title} CLASS={class_name} AUTO_ID={auto_id}".format(
                    pid=process_id,
                    process=_process_name(process_id),
                    title=_redact(str(getattr(info, "name", "") or "")),
                    class_name=str(getattr(info, "class_name", "") or ""),
                    auto_id=str(getattr(info, "automation_id", "") or ""),
                )
            )
        except Exception as exc:  # pragma: no cover - best-effort diagnostics
            lines.append(f"WINDOW ERROR: {type(exc).__name__}: {exc}")
    return "\n".join(lines)


def _launch_environment_as_text(
    options: DesktopLaunchOptions,
    *,
    process: subprocess.Popen[str],
    gui_pid: int | None,
) -> str:
    config_dir = options.appdata_root / "config"
    lines = [
        f"process_pid={process.pid}",
        f"process_exit_code={process.poll()}",
        f"gui_pid={gui_pid if gui_pid is not None else ''}",
        f"IMMOAPP_E2E_TEST_MODE={os.environ.get('IMMOAPP_E2E_TEST_MODE', '')}",
        f"IMMOAPP_APPDATA_ROOT={options.appdata_root}",
        f"IMMOAPP_CONFIG_DIR={os.environ.get('IMMOAPP_CONFIG_DIR', '')}",
        f"base_url={options.base_url}",
        f"api_timeout_seconds={format_api_timeout_seconds(options.api_timeout_seconds)}",
        f"client_python={options.client_python}",
        f"cwd={options.repo_root}",
        f"client_api_json_exists={(config_dir / 'client_api.json').exists()}",
        f"onboarding_state_json_exists={(config_dir / 'onboarding_state.json').exists()}",
        f"artifact_dir={options.artifact_dir}",
    ]
    return _redact("\n".join(lines))


def _capture_launch_exception_diagnostics(
    *,
    options: DesktopLaunchOptions,
    process: subprocess.Popen[str],
    stdio_handle: TextIO | None,
    gui_pid: object,
) -> None:
    artifact_dir = options.artifact_dir
    artifact_dir.mkdir(parents=True, exist_ok=True)
    resolved_gui_pid = int(gui_pid) if isinstance(gui_pid, int) else None
    write_text_file(
        artifact_dir / "launch_exception_process_tree.txt",
        _process_tree_as_text(process.pid),
    )
    write_text_file(
        artifact_dir / "launch_exception_visible_desktop_windows.txt",
        _visible_desktop_windows_as_text(),
    )
    write_text_file(
        artifact_dir / "launch_exception_environment.txt",
        _launch_environment_as_text(options, process=process, gui_pid=resolved_gui_pid),
    )
    if stdio_handle is not None:
        try:
            stdio_handle.flush()
        except Exception:
            pass
        stdio_log = Path(getattr(stdio_handle, "name", ""))
        if stdio_log.exists():
            write_text_file(
                artifact_dir / "launch_exception_client_stdio_tail.txt", _tail_text(stdio_log)
            )
    app_log = options.appdata_root / "logs" / "app.log"
    if app_log.exists():
        write_text_file(artifact_dir / "launch_exception_app_log_tail.txt", _tail_text(app_log))
    try:
        from PIL import ImageGrab

        ImageGrab.grab(all_screens=True).save(artifact_dir / "launch_exception.png")
    except Exception as exc:  # pragma: no cover - best-effort diagnostics
        write_text_file(
            artifact_dir / "launch_exception_screenshot_error.txt",
            f"{type(exc).__name__}: {exc}",
        )


def _redact(value: str) -> str:
    redacted = str(value)
    patterns = (
        (r"(?i)(password=)[^\s&;]+", r"\1<redacted>"),
        (r"(?i)(token=)[^\s&;]+", r"\1<redacted>"),
        (r"(?i)(secret=)[^\s&;]+", r"\1<redacted>"),
        (r"(?i)(key=)[^\s&;]+", r"\1<redacted>"),
        (r"(?i)(Authorization:\s*Bearer\s+)[^\s]+", r"\1<redacted>"),
    )
    for pattern, replacement in patterns:
        redacted = re.sub(pattern, replacement, redacted)
    return redacted


def _tail_text(path: Path, *, bytes_limit: int = 20_000) -> str:
    data = path.read_bytes()
    if len(data) > bytes_limit:
        data = data[-bytes_limit:]
    return _redact(data.decode("utf-8", errors="replace"))
