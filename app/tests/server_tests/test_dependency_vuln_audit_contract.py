from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import verify_dependency_vulns  # noqa: E402


def _disable_real_ignore_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(verify_dependency_vulns, "_IGNORE_FILE", tmp_path / "missing.json")


def _clear_docker_audit_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("IMMOAPP_DEP_AUDIT_INCLUDE_DOCKER_BACKEND", raising=False)
    monkeypatch.delenv("IMMOAPP_DEP_AUDIT_REQUIRE_DOCKER_BACKEND", raising=False)
    monkeypatch.delenv("IMMOAPP_DEP_AUDIT_DOCKER_IMAGE", raising=False)
    monkeypatch.delenv("IMMOAPP_APP_IMAGE", raising=False)


def _python_marker(tmp_path: Path, name: str) -> Path:
    path = tmp_path / name
    path.write_text("# fake python executable for contract tests\n", encoding="utf-8")
    return path


def test_twisted_pin_uses_stable_release_without_prerelease_audit_policy() -> None:
    requirements = REPO_ROOT / "requirements" / "server.txt"
    text = requirements.read_text(encoding="utf-8")
    assert "Twisted==26.4.0" in text
    assert "Twisted==26.4.0rc2" not in text
    assert "GHSA-grgv-6hw6-v9g4" not in text
    assert "latest public stable remains 25.5.0" not in text


def test_server_requirements_pin_security_fixed_msgpack_and_ujson() -> None:
    text = (REPO_ROOT / "requirements" / "server.txt").read_text(encoding="utf-8")

    assert "msgpack==1.2.1" in text
    assert "ujson==5.13.0" in text
    assert "msgpack==1.1.2" not in text
    assert "ujson==5.12.1" not in text


def test_dependency_audit_uses_resolved_transitive_inventories_without_pip_resolution(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _disable_real_ignore_file(monkeypatch, tmp_path)
    _clear_docker_audit_env(monkeypatch)
    server_python = _python_marker(tmp_path, "server-python.exe")
    client_python = _python_marker(tmp_path, "client-python.exe")
    monkeypatch.setattr(verify_dependency_vulns.sys, "executable", str(server_python))
    monkeypatch.setenv("IMMOAPP_DEP_AUDIT_CLIENT_PYTHON", str(client_python))
    monkeypatch.setenv("IMMOAPP_ENFORCE_DEP_AUDIT", "1")
    monkeypatch.setenv("IMMOAPP_DEP_AUDIT_PROCESS_TIMEOUT_SECONDS", "17")
    monkeypatch.setenv("IMMOAPP_DEP_AUDIT_SOCKET_TIMEOUT_SECONDS", "5")
    audit_calls: list[tuple[list[str], dict[str, object], str]] = []

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if args[1:5] == ["-m", "pip", "freeze", "--all"]:
            stdout = (
                "requests==2.32.5\nurllib3==2.5.0\n"
                if Path(args[0]) == server_python
                else "httpx==0.28.1\nanyio==4.11.0\n"
            )
            return subprocess.CompletedProcess(args, 0, stdout=stdout, stderr="")
        if args[1:3] == ["-m", "pip_audit"]:
            inventory_path = Path(args[args.index("-r") + 1])
            inventory_text = inventory_path.read_text(encoding="utf-8")
            audit_calls.append((args, kwargs, inventory_text))
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
        raise AssertionError(f"unexpected command: {args}")

    monkeypatch.setattr(verify_dependency_vulns.subprocess, "run", fake_run)

    verify_dependency_vulns.main()

    assert len(audit_calls) == 2
    audited_text = "\n".join(call[2] for call in audit_calls)
    assert "urllib3==2.5.0" in audited_text
    assert "anyio==4.11.0" in audited_text
    for args, kwargs, _inventory_text in audit_calls:
        assert "--no-deps" in args
        assert "--disable-pip" in args
        assert "requirements/server.txt" not in args
        assert "requirements/client.txt" not in args
        assert args[args.index("--progress-spinner") + 1] == "off"
        assert args[args.index("--cache-dir") + 1].endswith("pip-audit-cache")
        assert args[args.index("--timeout") + 1] == "5"
        assert kwargs["timeout"] == 17


def test_dependency_audit_timeout_is_gating_when_enforced(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _disable_real_ignore_file(monkeypatch, tmp_path)
    _clear_docker_audit_env(monkeypatch)
    server_python = _python_marker(tmp_path, "server-python.exe")
    monkeypatch.setattr(verify_dependency_vulns.sys, "executable", str(server_python))
    monkeypatch.setenv("IMMOAPP_DEP_AUDIT_CLIENT_PYTHON", str(server_python))
    monkeypatch.setenv("IMMOAPP_ENFORCE_DEP_AUDIT", "1")
    monkeypatch.setenv("IMMOAPP_DEP_AUDIT_PROCESS_TIMEOUT_SECONDS", "3")

    def fake_run(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        if args[1:5] == ["-m", "pip", "freeze", "--all"]:
            return subprocess.CompletedProcess(args, 0, stdout="requests==2.32.5\n", stderr="")
        raise subprocess.TimeoutExpired(cmd=["pip-audit"], timeout=3)

    monkeypatch.setattr(verify_dependency_vulns.subprocess, "run", fake_run)

    with pytest.raises(SystemExit) as exc_info:
        verify_dependency_vulns.main()

    assert "pip-audit for server timed out after 3 seconds" in str(exc_info.value)


def test_dependency_audit_missing_tool_is_gating_when_enforced(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _disable_real_ignore_file(monkeypatch, tmp_path)
    _clear_docker_audit_env(monkeypatch)
    server_python = _python_marker(tmp_path, "server-python.exe")
    monkeypatch.setattr(verify_dependency_vulns.sys, "executable", str(server_python))
    monkeypatch.setenv("IMMOAPP_DEP_AUDIT_CLIENT_PYTHON", str(server_python))
    monkeypatch.setenv("IMMOAPP_ENFORCE_DEP_AUDIT", "1")

    def fake_run(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        if args[1:5] == ["-m", "pip", "freeze", "--all"]:
            return subprocess.CompletedProcess(args, 0, stdout="requests==2.32.5\n", stderr="")
        return subprocess.CompletedProcess(
            args,
            1,
            stdout="",
            stderr="No module named pip_audit",
        )

    monkeypatch.setattr(verify_dependency_vulns.subprocess, "run", fake_run)

    with pytest.raises(SystemExit) as exc_info:
        verify_dependency_vulns.main()

    assert "pip-audit is required when enforce mode is enabled" in str(exc_info.value)


def test_dependency_audit_enforce_requires_client_inventory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _disable_real_ignore_file(monkeypatch, tmp_path)
    _clear_docker_audit_env(monkeypatch)
    server_python = _python_marker(tmp_path, "server-python.exe")
    monkeypatch.setattr(verify_dependency_vulns.sys, "executable", str(server_python))
    monkeypatch.setenv("IMMOAPP_DEP_AUDIT_CLIENT_PYTHON", str(tmp_path / "missing-client.exe"))
    monkeypatch.setenv("IMMOAPP_ENFORCE_DEP_AUDIT", "1")

    with pytest.raises(SystemExit) as exc_info:
        verify_dependency_vulns.main()

    assert "client Python for dependency audit was not found" in str(exc_info.value)


def test_dependency_audit_can_audit_docker_backend_inventory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _disable_real_ignore_file(monkeypatch, tmp_path)
    server_python = _python_marker(tmp_path, "server-python.exe")
    client_python = _python_marker(tmp_path, "client-python.exe")
    monkeypatch.setattr(verify_dependency_vulns.sys, "executable", str(server_python))
    monkeypatch.setenv("IMMOAPP_DEP_AUDIT_CLIENT_PYTHON", str(client_python))
    monkeypatch.setenv("IMMOAPP_ENFORCE_DEP_AUDIT", "1")
    monkeypatch.setenv("IMMOAPP_DEP_AUDIT_REQUIRE_DOCKER_BACKEND", "1")
    audit_calls: list[tuple[list[str], str]] = []
    docker_freeze_calls: list[list[str]] = []

    def fake_run(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        if args[1:5] == ["-m", "pip", "freeze", "--all"]:
            stdout = (
                "requests==2.33.0\nurllib3==2.6.0\n"
                if Path(args[0]) == server_python
                else "httpx==0.29.0\nanyio==4.12.0\n"
            )
            return subprocess.CompletedProcess(args, 0, stdout=stdout, stderr="")
        if args[:5] == ["docker", "run", "--rm", "--entrypoint", "python"]:
            docker_freeze_calls.append(args)
            return subprocess.CompletedProcess(
                args,
                0,
                stdout=(
                    "Django @ file:///wheels/django-5.2.8-py3-none-any.whl#sha256=abc\n"
                    "uvloop @ file:///wheels/uvloop-0.22.1-cp314-cp314-manylinux.whl"
                    "#sha256=def\n"
                    "httptools @ file:///wheels/httptools-0.7.1-cp314-cp314-manylinux.whl"
                    "#sha256=ghi\n"
                ),
                stderr="",
            )
        if args[1:3] == ["-m", "pip_audit"]:
            inventory_path = Path(args[args.index("-r") + 1])
            audit_calls.append((args, inventory_path.read_text(encoding="utf-8")))
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
        raise AssertionError(f"unexpected command: {args}")

    monkeypatch.setattr(verify_dependency_vulns.subprocess, "run", fake_run)

    verify_dependency_vulns.main()

    assert len(docker_freeze_calls) == 1
    docker_args = docker_freeze_calls[0]
    assert docker_args[:5] == ["docker", "run", "--rm", "--entrypoint", "python"]
    assert docker_args[-4:] == ["-m", "pip", "freeze", "--all"]
    assert len(audit_calls) == 3
    docker_audits = [text for _args, text in audit_calls if "uvloop==0.22.1" in text]
    assert docker_audits
    assert "httptools==0.7.1" in docker_audits[0]
    assert "file:///wheels" not in docker_audits[0]
    for args, _inventory_text in audit_calls:
        assert "--no-deps" in args
        assert "--disable-pip" in args
    assert "audited=server,client,docker-backend" in capsys.readouterr().out


def test_dependency_audit_enforced_docker_inventory_failure_is_gating(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _disable_real_ignore_file(monkeypatch, tmp_path)
    server_python = _python_marker(tmp_path, "server-python.exe")
    monkeypatch.setattr(verify_dependency_vulns.sys, "executable", str(server_python))
    monkeypatch.setenv("IMMOAPP_DEP_AUDIT_CLIENT_PYTHON", str(server_python))
    monkeypatch.setenv("IMMOAPP_ENFORCE_DEP_AUDIT", "1")
    monkeypatch.setenv("IMMOAPP_DEP_AUDIT_REQUIRE_DOCKER_BACKEND", "1")

    def fake_run(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        if args[1:5] == ["-m", "pip", "freeze", "--all"]:
            return subprocess.CompletedProcess(args, 0, stdout="requests==2.33.0\n", stderr="")
        if args[:5] == ["docker", "run", "--rm", "--entrypoint", "python"]:
            return subprocess.CompletedProcess(args, 125, stdout="", stderr="missing image")
        raise AssertionError(f"unexpected command: {args}")

    monkeypatch.setattr(verify_dependency_vulns.subprocess, "run", fake_run)

    with pytest.raises(SystemExit) as exc_info:
        verify_dependency_vulns.main()

    assert "Docker backend dependency inventory failed" in str(exc_info.value)
    assert "missing image" in str(exc_info.value)


def test_dependency_audit_optional_docker_inventory_skip_is_clear(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _disable_real_ignore_file(monkeypatch, tmp_path)
    server_python = _python_marker(tmp_path, "server-python.exe")
    monkeypatch.setattr(verify_dependency_vulns.sys, "executable", str(server_python))
    monkeypatch.setenv("IMMOAPP_DEP_AUDIT_CLIENT_PYTHON", str(server_python))
    monkeypatch.setenv("IMMOAPP_DEP_AUDIT_INCLUDE_DOCKER_BACKEND", "1")
    monkeypatch.delenv("IMMOAPP_ENFORCE_DEP_AUDIT", raising=False)
    monkeypatch.delenv("CI", raising=False)

    def fake_run(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        if args[1:5] == ["-m", "pip", "freeze", "--all"]:
            return subprocess.CompletedProcess(args, 0, stdout="requests==2.33.0\n", stderr="")
        if args[:5] == ["docker", "run", "--rm", "--entrypoint", "python"]:
            raise FileNotFoundError("docker")
        if args[1:3] == ["-m", "pip_audit"]:
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
        raise AssertionError(f"unexpected command: {args}")

    monkeypatch.setattr(verify_dependency_vulns.subprocess, "run", fake_run)

    verify_dependency_vulns.main()

    output = capsys.readouterr().out
    assert "failed to collect Docker backend inventory" in output
    assert "audited=server" in output
    assert "docker-backend" not in output.split("audited=", 1)[1].split(";", 1)[0]


def test_full_and_release_lanes_require_docker_backend_dependency_audit() -> None:
    full = (REPO_ROOT / "scripts" / "checks_full.ps1").read_text(encoding="utf-8")
    release = (REPO_ROOT / "scripts" / "run_e2e_release_validation.ps1").read_text(encoding="utf-8")
    docs = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (
            REPO_ROOT / "scripts" / "README.md",
            REPO_ROOT / "app" / "tests" / "e2e_desktop" / "README.md",
        )
    )

    assert "build backend image for Docker dependency audit" in full
    assert 'IMMOAPP_DEP_AUDIT_REQUIRE_DOCKER_BACKEND = "1"' in full
    assert "verify_dependency_vulns.py" in full
    assert 'IMMOAPP_DEP_AUDIT_REQUIRE_DOCKER_BACKEND = "1"' in release
    assert "verify_dependency_vulns.py" in release
    assert "Docker backend" in docs
    assert "docker-backend" in docs
