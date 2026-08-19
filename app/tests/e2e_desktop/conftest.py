from __future__ import annotations

import os
import platform
import shutil
import time
import uuid
import warnings
from collections.abc import Callable, Generator, Iterator
from pathlib import Path
from typing import Any, cast

import pytest

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "server.immoapp_server.settings")
os.environ.setdefault("IMMOAPP_SKIP_CELERY_APP", "1")
os.environ.setdefault("IMMOAPP_REQUIRE_ALE_KEY", "1")
os.environ.setdefault("IMMOAPP_ALE_MASTER_KEY", "test-master-key")
os.environ.setdefault("IMMOAPP_ALE_HMAC_KEY", "test-hmac-key")
os.environ.setdefault("POSTGRES_HOST", "127.0.0.1")
os.environ.setdefault("POSTGRES_PORT", "5432")

from app.tests.e2e_desktop import backend
from app.tests.e2e_desktop.installed_hub_manager_backend import (
    ManagedOwner,
    cleanup_owner_registration,
    ensure_managed_hub_running,
    platform_admin_email,
    provision_active_owner,
    wait_for_front_door,
)
from app.tests.e2e_desktop.runtime import (
    DEFAULT_API_TIMEOUT_SECONDS,
    DesktopLaunchOptions,
    DesktopSession,
    launch_desktop,
    validate_api_timeout_seconds,
)


def _env_flag(name: str) -> bool:
    raw = str(os.environ.get(name, "") or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = str(os.environ.get(name, "") or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        warnings.warn(
            f"Ignoring invalid integer value for {name}: {raw!r}",
            RuntimeWarning,
            stacklevel=2,
        )
        return default


def _remove_tree(path: Path, *, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while True:
        shutil.rmtree(path, ignore_errors=True)
        if not path.exists():
            return
        if time.monotonic() >= deadline:
            raise RuntimeError(f"Failed to remove desktop E2E artifact directory {path}")
        time.sleep(0.2)


def _prune_stale_artifacts(root: Path, *, retention_days: int) -> None:
    if retention_days <= 0 or not root.exists():
        return
    cutoff = time.time() - (retention_days * 24 * 60 * 60)
    for candidate in root.iterdir():
        try:
            candidate_mtime = candidate.stat().st_mtime
        except OSError as exc:
            warnings.warn(
                f"Could not stat desktop E2E artifact {candidate}: {exc}",
                RuntimeWarning,
                stacklevel=2,
            )
            continue
        if candidate_mtime >= cutoff:
            continue
        try:
            if candidate.is_dir():
                _remove_tree(candidate)
            else:
                candidate.unlink(missing_ok=True)
        except OSError as exc:
            warnings.warn(
                f"Could not prune stale desktop E2E artifact {candidate}: {exc}",
                RuntimeWarning,
                stacklevel=2,
            )


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("desktop-e2e")
    group.addoption(
        "--e2e-base-url",
        action="store",
        default=os.environ.get("IMMOAPP_E2E_BASE_URL", "http://127.0.0.1:8000"),
        help="Base URL for the locally running backend used by desktop E2E tests.",
    )
    group.addoption(
        "--e2e-front-door-url",
        action="store",
        default=os.environ.get("IMMOAPP_E2E_FRONT_DOOR_URL", ""),
        help=(
            "Caddy Hub front-door URL used by setup-wizard E2E tests. "
            "This is intentionally separate from --e2e-base-url."
        ),
    )
    group.addoption(
        "--e2e-client-python",
        action="store",
        default=os.environ.get(
            "IMMOAPP_E2E_CLIENT_PYTHON",
            r"C:\ProgramData\ImmoApp\venvs\immoapp-client-py314\Scripts\python.exe",
        ),
        help="Python executable from the client virtual environment used to launch app/main.py.",
    )
    group.addoption(
        "--e2e-server-log-path",
        action="store",
        default=os.environ.get("IMMOAPP_E2E_SERVER_LOG_PATH", ""),
        help="Optional server log path to tail into desktop E2E failure artifacts.",
    )
    group.addoption(
        "--e2e-api-timeout-seconds",
        action="store",
        default=os.environ.get(
            "IMMOAPP_E2E_API_TIMEOUT_SECONDS",
            f"{DEFAULT_API_TIMEOUT_SECONDS:g}",
        ),
        help="Validated API timeout passed to the launched desktop client.",
    )
    group.addoption(
        "--e2e-keep-passing-artifacts",
        action="store_true",
        default=_env_flag("IMMOAPP_E2E_KEEP_PASSING_ARTIFACTS"),
        help="Keep passing desktop E2E artifacts instead of deleting them after each test.",
    )
    group.addoption(
        "--e2e-artifact-retention-days",
        action="store",
        type=int,
        default=_env_int("IMMOAPP_E2E_ARTIFACT_RETENTION_DAYS", 7),
        help=(
            "Prune desktop E2E artifacts older than this many days at session start. "
            "Use 0 to disable pruning."
        ),
    )


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if "app/tests/e2e_desktop" in str(item.fspath).replace("\\", "/"):
            item.add_marker(pytest.mark.e2e)


@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_runtest_makereport(
    item: pytest.Item,
    call: pytest.CallInfo[object],
) -> Generator[None]:
    outcome = yield
    report = cast(Any, outcome).get_result()
    setattr(item, f"rep_{report.when}", report)


@pytest.fixture(scope="session")
def ensure_windows_host() -> None:
    if platform.system() != "Windows":
        pytest.skip("Desktop E2E is Windows-only.")


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


@pytest.fixture(scope="session")
def e2e_base_url(ensure_windows_host: None, request: pytest.FixtureRequest) -> str:
    value = str(request.config.getoption("--e2e-base-url"))
    backend.ensure_backend_ready(value)
    return backend.normalize_base_url(value)


@pytest.fixture(scope="session")
def e2e_front_door_url(ensure_windows_host: None, request: pytest.FixtureRequest) -> str:
    value = str(request.config.getoption("--e2e-front-door-url") or "").strip()
    if not value:
        raise pytest.UsageError(
            "Setup-wizard front-door E2E requires --e2e-front-door-url or "
            "IMMOAPP_E2E_FRONT_DOOR_URL."
        )
    result = backend.ensure_front_door_ready(value)
    return result.base_url


@pytest.fixture(scope="session")
def e2e_client_python(ensure_windows_host: None, request: pytest.FixtureRequest) -> Path:
    path = Path(str(request.config.getoption("--e2e-client-python"))).resolve()
    if not path.exists():
        raise RuntimeError(
            f"Desktop E2E client Python was not found at {path}. "
            "Pass --e2e-client-python or set IMMOAPP_E2E_CLIENT_PYTHON."
        )
    return path


@pytest.fixture(scope="session")
def e2e_server_log_path(request: pytest.FixtureRequest) -> Path | None:
    raw = str(request.config.getoption("--e2e-server-log-path") or "").strip()
    return Path(raw).resolve() if raw else None


@pytest.fixture(scope="session")
def e2e_api_timeout_seconds(request: pytest.FixtureRequest) -> float:
    raw = request.config.getoption("--e2e-api-timeout-seconds")
    try:
        return validate_api_timeout_seconds(raw)
    except ValueError as exc:
        raise pytest.UsageError(str(exc)) from exc


@pytest.fixture(scope="session")
def e2e_keep_passing_artifacts(request: pytest.FixtureRequest) -> bool:
    return bool(request.config.getoption("--e2e-keep-passing-artifacts"))


@pytest.fixture(scope="session")
def e2e_artifact_root(repo_root: Path, request: pytest.FixtureRequest) -> Path:
    root = repo_root / ".tmp" / "desktop_e2e_artifacts"
    root.mkdir(parents=True, exist_ok=True)
    retention_days = int(request.config.getoption("--e2e-artifact-retention-days"))
    _prune_stale_artifacts(root, retention_days=retention_days)
    return root


@pytest.fixture
def artifact_dir(e2e_artifact_root: Path, request: pytest.FixtureRequest) -> Path:
    safe_name = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in request.node.name)
    artifact = e2e_artifact_root / f"{safe_name}_{uuid.uuid4().hex[:8]}"
    artifact.mkdir(parents=True, exist_ok=True)
    return artifact


@pytest.fixture
def make_backend_user() -> Iterator[Callable[..., backend.DesktopUser]]:
    users: list[backend.DesktopUser] = []

    def _create(*, prefix: str, can_import: bool = False) -> backend.DesktopUser:
        user = backend.create_desktop_user(prefix=prefix, can_import=can_import)
        users.append(user)
        return user

    try:
        yield _create
    finally:
        for user in reversed(users):
            backend.cleanup_desktop_user(user)


@pytest.fixture
def managed_hub_owner() -> Iterator[ManagedOwner]:
    required_env = (
        "IMMOAPP_E2E_INSTALLED_HUB_MANAGER_PATH",
        "IMMOAPP_E2E_INSTALLED_SOURCE_COMMIT_SHA",
        "IMMOAPP_E2E_MANAGED_FRONT_DOOR_URL",
        "IMMOAPP_E2E_MANAGED_PLATFORM_ADMIN_EMAIL",
    )
    missing = [name for name in required_env if not str(os.environ.get(name, "")).strip()]
    if missing:
        pytest.skip("Managed installed Hub E2E requires: " + ", ".join(missing))
    wait_for_front_door(ready=True)
    owner = provision_active_owner()
    try:
        yield owner
    finally:
        ensure_managed_hub_running()
        cleanup_owner_registration(owner.email, admin_email=platform_admin_email())


@pytest.fixture
def launch_native_desktop(
    repo_root: Path,
    e2e_base_url: str,
    e2e_client_python: Path,
    e2e_keep_passing_artifacts: bool,
    e2e_server_log_path: Path | None,
    e2e_api_timeout_seconds: float,
    artifact_dir: Path,
    request: pytest.FixtureRequest,
) -> Iterator[Callable[..., DesktopSession]]:
    sessions: list[DesktopSession] = []

    def _launch(
        *,
        username: str | None = None,
        preseed_api: bool = True,
        preseed_quick_start: bool = True,
    ) -> DesktopSession:
        token = uuid.uuid4().hex[:8]
        session = launch_desktop(
            DesktopLaunchOptions(
                client_python=e2e_client_python,
                repo_root=repo_root,
                appdata_root=artifact_dir / f"appdata_{token}",
                artifact_dir=artifact_dir / f"session_{token}",
                qsettings_org=f"ImmoAppE2E_{token}",
                qsettings_app=f"DesktopSuite_{token}",
                base_url=e2e_base_url,
                username=username,
                preseed_api=preseed_api,
                preseed_quick_start=preseed_quick_start,
                server_log_path=e2e_server_log_path,
                api_timeout_seconds=e2e_api_timeout_seconds,
            )
        )
        sessions.append(session)
        return session

    try:
        yield _launch
    finally:
        failed = any(
            bool(getattr(getattr(request.node, report_name, None), "failed", False))
            for report_name in ("rep_setup", "rep_call", "rep_teardown")
        )
        for index, session in enumerate(reversed(sessions), start=1):
            if failed:
                session.capture_diagnostics(f"failure_{index}")
            session.close()
        if not failed and not e2e_keep_passing_artifacts and artifact_dir.exists():
            _remove_tree(artifact_dir)
