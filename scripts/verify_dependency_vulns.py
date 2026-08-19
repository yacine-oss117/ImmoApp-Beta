from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import NoReturn

from repo_layout import PIP_AUDIT_IGNORE

_IGNORE_FILE = PIP_AUDIT_IGNORE
_DEFAULT_PROCESS_TIMEOUT_SECONDS = 300
_DEFAULT_SOCKET_TIMEOUT_SECONDS = 15
_DEFAULT_CLIENT_PYTHON = (
    Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData"))
    / "ImmoApp"
    / "venvs"
    / "immoapp-client-py314"
    / "Scripts"
    / "python.exe"
)


class AuditSkipped(RuntimeError):
    pass


def _is_truthy(value: str | None) -> bool:
    if not value:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _positive_int_from_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise SystemExit(f"verify_dependency_vulns: {name} must be an integer.") from exc
    if value <= 0:
        raise SystemExit(f"verify_dependency_vulns: {name} must be positive.")
    return value


@dataclass(frozen=True)
class IgnoreRule:
    vuln_id: str
    expires_on: date | None


@dataclass(frozen=True)
class PythonInventoryTarget:
    label: str
    executable: Path


@dataclass(frozen=True)
class DockerInventoryTarget:
    label: str
    image: str


@dataclass(frozen=True)
class ResolvedInventory:
    label: str
    path: Path
    package_names: frozenset[str]


def _skip_or_fail(enforce: bool, message: str, cause: BaseException | None = None) -> NoReturn:
    if enforce:
        raise SystemExit(message) from cause
    raise AuditSkipped(message)


def _load_ignore_rules(path: Path) -> list[IgnoreRule]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise SystemExit("verify_dependency_vulns: ignore file must be a JSON array.")
    rules: list[IgnoreRule] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        vuln_id = str(item.get("id") or "").strip()
        if not vuln_id:
            continue
        expires_raw = str(item.get("expires_on") or "").strip()
        expires_on = None
        if expires_raw:
            try:
                expires_on = date.fromisoformat(expires_raw)
            except ValueError as exc:
                raise SystemExit(
                    f"verify_dependency_vulns: invalid expires_on for {vuln_id}: {expires_raw}"
                ) from exc
        rules.append(IgnoreRule(vuln_id=vuln_id, expires_on=expires_on))
    return rules


def _assert_not_expired(rules: list[IgnoreRule]) -> None:
    today = date.today()
    expired = [
        rule.vuln_id for rule in rules if rule.expires_on is not None and rule.expires_on < today
    ]
    if expired:
        raise SystemExit(
            "verify_dependency_vulns: expired vulnerability allowlist entries: "
            + ", ".join(sorted(expired))
        )


def _client_python_from_env() -> Path:
    for name in ("IMMOAPP_DEP_AUDIT_CLIENT_PYTHON", "IMMOAPP_E2E_CLIENT_PYTHON"):
        raw = str(os.environ.get(name) or "").strip()
        if raw:
            return Path(raw)
    return _DEFAULT_CLIENT_PYTHON


def _inventory_targets(enforce: bool) -> tuple[list[PythonInventoryTarget], list[str]]:
    warnings: list[str] = []
    server_python = Path(sys.executable).resolve()
    targets = [PythonInventoryTarget(label="server", executable=server_python)]
    client_python = _client_python_from_env().resolve()
    if not client_python.exists():
        message = (
            "verify_dependency_vulns: client Python for dependency audit was not found at "
            f"{client_python}."
        )
        if enforce:
            raise SystemExit(message)
        warnings.append(message)
        return targets, warnings
    if client_python != server_python:
        targets.append(PythonInventoryTarget(label="client", executable=client_python))
    return targets, warnings


def _docker_backend_image_from_env() -> str:
    for name in ("IMMOAPP_DEP_AUDIT_DOCKER_IMAGE", "IMMOAPP_APP_IMAGE"):
        raw = str(os.environ.get(name) or "").strip()
        if raw:
            return raw
    return "immoapp-server:local"


def _include_docker_backend_audit() -> bool:
    return _is_truthy(os.environ.get("IMMOAPP_DEP_AUDIT_INCLUDE_DOCKER_BACKEND")) or _is_truthy(
        os.environ.get("IMMOAPP_DEP_AUDIT_REQUIRE_DOCKER_BACKEND")
    )


def _require_docker_backend_audit() -> bool:
    return _is_truthy(os.environ.get("IMMOAPP_DEP_AUDIT_REQUIRE_DOCKER_BACKEND"))


def _package_name_from_freeze_line(line: str) -> str | None:
    normalized = line.strip()
    if not normalized or normalized.startswith(("#", "-")):
        return None
    for separator in ("==", " @ "):
        if separator in normalized:
            return normalized.split(separator, 1)[0].split("[", 1)[0].strip().lower()
    return normalized.split(";", 1)[0].split("[", 1)[0].strip().lower() or None


def _normalize_freeze_line_for_audit(line: str) -> str:
    normalized = line.strip()
    if " @ " not in normalized:
        return normalized
    name, url = normalized.split(" @ ", 1)
    wheel_name = url.split("#", 1)[0].replace("\\", "/").rsplit("/", 1)[-1]
    if not wheel_name.endswith(".whl"):
        raise ValueError(f"non-wheel direct URL requirement cannot be audited: {line}")
    wheel_parts = wheel_name[:-4].split("-")
    if len(wheel_parts) < 2 or not wheel_parts[1]:
        raise ValueError(f"wheel direct URL requirement has no exact version: {line}")
    return f"{name.strip()}=={wheel_parts[1]}"


def _normalize_freeze_lines_for_audit(lines: list[str]) -> list[str]:
    try:
        return [_normalize_freeze_line_for_audit(line) for line in lines]
    except ValueError as exc:
        raise SystemExit(f"verify_dependency_vulns: {exc}") from exc


def _freeze_inventory(
    target: PythonInventoryTarget,
    *,
    enforce: bool,
    process_timeout: int,
    output_dir: Path,
) -> ResolvedInventory:
    args = [str(target.executable), "-m", "pip", "freeze", "--all"]
    try:
        result = subprocess.run(
            args,
            check=False,
            capture_output=True,
            text=True,
            timeout=process_timeout,
        )
    except subprocess.TimeoutExpired as exc:
        _skip_or_fail(
            enforce,
            "verify_dependency_vulns: pip freeze for "
            f"{target.label} timed out after {process_timeout} seconds",
            exc,
        )
    except Exception as exc:
        _skip_or_fail(
            enforce,
            "verify_dependency_vulns: failed to collect "
            f"{target.label} dependency inventory: {exc}",
            exc,
        )

    if result.returncode != 0:
        details = ((result.stdout or "") + "\n" + (result.stderr or "")).strip()
        _skip_or_fail(
            enforce,
            f"verify_dependency_vulns: pip freeze for {target.label} failed.\n{details}",
        )
    raw_lines = [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]
    lines = _normalize_freeze_lines_for_audit(raw_lines)
    package_names = {
        name for line in lines if (name := _package_name_from_freeze_line(line)) is not None
    }
    if not lines or not package_names:
        _skip_or_fail(
            enforce,
            f"verify_dependency_vulns: {target.label} dependency inventory is empty.",
        )
    inventory_path = output_dir / f"{target.label}-resolved-requirements.txt"
    inventory_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return ResolvedInventory(
        label=target.label,
        path=inventory_path,
        package_names=frozenset(package_names),
    )


def _freeze_docker_backend_inventory(
    target: DockerInventoryTarget,
    *,
    enforce: bool,
    process_timeout: int,
    output_dir: Path,
) -> ResolvedInventory:
    args = [
        "docker",
        "run",
        "--rm",
        "--entrypoint",
        "python",
        target.image,
        "-m",
        "pip",
        "freeze",
        "--all",
    ]
    try:
        result = subprocess.run(
            args,
            check=False,
            capture_output=True,
            text=True,
            timeout=process_timeout,
        )
    except subprocess.TimeoutExpired as exc:
        _skip_or_fail(
            enforce,
            "verify_dependency_vulns: Docker backend pip freeze timed out after "
            f"{process_timeout} seconds",
            exc,
        )
    except Exception as exc:
        _skip_or_fail(
            enforce,
            f"verify_dependency_vulns: failed to collect Docker backend inventory: {exc}",
            exc,
        )

    if result.returncode != 0:
        details = ((result.stdout or "") + "\n" + (result.stderr or "")).strip()
        _skip_or_fail(
            enforce,
            "verify_dependency_vulns: Docker backend dependency inventory failed "
            f"for image {target.image}.\n{details}",
        )
    raw_lines = [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]
    lines = _normalize_freeze_lines_for_audit(raw_lines)
    package_names = {
        name for line in lines if (name := _package_name_from_freeze_line(line)) is not None
    }
    if not lines or not package_names:
        _skip_or_fail(
            enforce,
            "verify_dependency_vulns: Docker backend dependency inventory is empty.",
        )
    inventory_path = output_dir / f"{target.label}-resolved-requirements.txt"
    inventory_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return ResolvedInventory(
        label=target.label,
        path=inventory_path,
        package_names=frozenset(package_names),
    )


def _pip_audit_args(
    *,
    inventory: ResolvedInventory,
    socket_timeout: int,
    rules: list[IgnoreRule],
) -> list[str]:
    args = [
        sys.executable,
        "-m",
        "pip_audit",
        "--strict",
        "--no-deps",
        "--disable-pip",
        "--progress-spinner",
        "off",
        "--cache-dir",
        str(inventory.path.parent / "pip-audit-cache"),
        "--timeout",
        str(socket_timeout),
        "-r",
        str(inventory.path),
    ]
    for rule in rules:
        args.extend(["--ignore-vuln", rule.vuln_id])
    return args


def _run_pip_audit(
    *,
    inventory: ResolvedInventory,
    rules: list[IgnoreRule],
    enforce: bool,
    process_timeout: int,
    socket_timeout: int,
) -> None:
    args = _pip_audit_args(inventory=inventory, socket_timeout=socket_timeout, rules=rules)
    try:
        result = subprocess.run(
            args,
            check=False,
            capture_output=True,
            text=True,
            timeout=process_timeout,
        )
    except subprocess.TimeoutExpired as exc:
        _skip_or_fail(
            enforce,
            "verify_dependency_vulns: pip-audit for "
            f"{inventory.label} timed out after {process_timeout} seconds",
            exc,
        )
        return
    except Exception as exc:
        _skip_or_fail(
            enforce,
            f"verify_dependency_vulns: failed to execute pip-audit for {inventory.label}: {exc}",
            exc,
        )
        return

    missing = "No module named pip_audit" in (result.stderr or "")
    if missing:
        message = (
            "verify_dependency_vulns: pip-audit is required when enforce mode is enabled."
            if enforce
            else "verify_dependency_vulns: pip-audit not installed."
        )
        _skip_or_fail(
            enforce,
            message,
        )
        return

    if result.returncode != 0:
        details = ((result.stdout or "") + "\n" + (result.stderr or "")).strip()
        raise SystemExit(
            "verify_dependency_vulns: "
            f"{inventory.label} audit failed (exit code {result.returncode})\n{details}"
        )


def main() -> None:
    enforce = _is_truthy(os.environ.get("IMMOAPP_ENFORCE_DEP_AUDIT")) or _is_truthy(
        os.environ.get("CI")
    )
    process_timeout = _positive_int_from_env(
        "IMMOAPP_DEP_AUDIT_PROCESS_TIMEOUT_SECONDS",
        _DEFAULT_PROCESS_TIMEOUT_SECONDS,
    )
    socket_timeout = _positive_int_from_env(
        "IMMOAPP_DEP_AUDIT_SOCKET_TIMEOUT_SECONDS",
        _DEFAULT_SOCKET_TIMEOUT_SECONDS,
    )
    rules = _load_ignore_rules(_IGNORE_FILE)
    _assert_not_expired(rules)
    require_docker_backend = _require_docker_backend_audit()

    try:
        targets, warnings = _inventory_targets(enforce)
        with tempfile.TemporaryDirectory(prefix="immoapp-dep-audit-") as temp_root:
            temp_dir = Path(temp_root)
            inventories = [
                _freeze_inventory(
                    target,
                    enforce=enforce,
                    process_timeout=process_timeout,
                    output_dir=temp_dir,
                )
                for target in targets
            ]
            if _include_docker_backend_audit():
                docker_target = DockerInventoryTarget(
                    label="docker-backend",
                    image=_docker_backend_image_from_env(),
                )
                try:
                    inventories.append(
                        _freeze_docker_backend_inventory(
                            docker_target,
                            enforce=enforce or require_docker_backend,
                            process_timeout=process_timeout,
                            output_dir=temp_dir,
                        )
                    )
                except AuditSkipped as exc:
                    warnings.append(str(exc))
            for inventory in inventories:
                _run_pip_audit(
                    inventory=inventory,
                    rules=rules,
                    enforce=enforce,
                    process_timeout=process_timeout,
                    socket_timeout=socket_timeout,
                )
            audited_labels = ",".join(inventory.label for inventory in inventories)
            audited_packages = sum(len(inventory.package_names) for inventory in inventories)
    except AuditSkipped as exc:
        print(f"{exc}; skipped")
        return

    for warning in warnings:
        print(warning)

    ignored = [rule.vuln_id for rule in rules]
    suffix = f" (ignored={','.join(sorted(ignored))})" if ignored else ""
    print(
        "verify_dependency_vulns: OK "
        f"(audited={audited_labels}; packages={audited_packages}){suffix}"
    )


if __name__ == "__main__":
    main()
