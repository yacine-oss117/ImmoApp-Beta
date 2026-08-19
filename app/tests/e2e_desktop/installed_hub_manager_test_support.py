from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest

HUB_MANAGER_OUTPUT_DIR = Path(r"C:\ProgramData\ImmoApp\logs\hub-manager-app")


def required_env_path(name: str) -> Path:
    raw = str(os.environ.get(name, "") or "").strip()
    if not raw:
        pytest.skip(f"{name} is required for installed Hub Manager E2E.")
    path = Path(raw).resolve()
    if not path.exists():
        pytest.fail(f"{name} does not exist: {path}")
    return path


def required_env_text(name: str) -> str:
    value = str(os.environ.get(name, "") or "").strip()
    if not value:
        pytest.skip(f"{name} is required for installed Hub Manager E2E.")
    return value


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    assert isinstance(payload, dict)
    return cast(dict[str, Any], payload)


def installed_hub_manager_path() -> Path:
    return required_env_path("IMMOAPP_E2E_INSTALLED_HUB_MANAGER_PATH")


def installed_desktop_path() -> Path:
    manager = installed_hub_manager_path()
    desktop = manager.with_name("ImmoApp.exe")
    assert desktop.is_file()
    return desktop


def assert_installed_build_identity(installed_exe: Path) -> dict[str, Any]:
    expected_source_commit = required_env_text("IMMOAPP_E2E_INSTALLED_SOURCE_COMMIT_SHA")
    identity = read_json(installed_exe.parent / "_internal" / "app" / "build_identity.json")
    assert identity["git_sha"] == expected_source_commit
    return identity


def wait_for_evidence(
    path: Path,
    *,
    predicate: Callable[[dict[str, Any]], bool],
    after_mtime_ns: int = 0,
    timeout: float = 600.0,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last_payload: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        try:
            if path.is_file() and path.stat().st_mtime_ns > after_mtime_ns:
                last_payload = read_json(path)
                if predicate(last_payload):
                    return last_payload
        except (OSError, json.JSONDecodeError):
            pass
        time.sleep(0.25)
    raise AssertionError(f"Installed Hub Manager evidence did not complete: {path} {last_payload}")


def prior_mtime_ns(path: Path) -> int:
    return path.stat().st_mtime_ns if path.exists() else 0


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
