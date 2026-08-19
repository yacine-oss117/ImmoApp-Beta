from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def _read(relative: str) -> str:
    return (REPO_ROOT / relative).read_text(encoding="utf-8")


def test_managed_runtime_pr_guard_keeps_offline_runtime_contract() -> None:
    compose = _read("deployment/managed-runtime/compose/compose.yaml")
    start = _read("deployment/managed-runtime/bin/start-managed-hub")
    common = _read("deployment/managed-runtime/bin/managed-hub-common")
    bundle = _read("scripts/build_managed_wsl2_runtime_image_bundle.ps1")

    assert "pull_policy: never" in compose
    assert "docker pull" not in start
    assert "docker pull" not in common
    assert "apt-get install" not in start
    assert "apt-get install" not in common
    assert "stack.ps1" not in start
    assert "stack.ps1" not in common
    assert "Docker Desktop" not in start
    assert "Docker Desktop" not in common
    assert "latest" not in compose
    assert "org.opencontainers.image.revision" in bundle
    assert "docker_pull_invoked = $false" in bundle
    assert "package_manager_install_invoked = $false" in bundle


def test_check_lanes_keep_slow_runtime_proofs_out_of_pr_but_in_full() -> None:
    pr = _read("scripts/checks_pr.ps1")
    full = _read("scripts/checks_full.ps1")
    hub_contract = _read("app/tests/server_tests/test_hub_beta_m1_contract.py")

    assert "not integration and not slow and not perf and not e2e and not nightly" in pr
    assert 'PytestMarker "integration or e2e or slow"' in full
    assert "pytestmark = pytest.mark.slow" in hub_contract


def test_pr_type_checks_run_mypy_targets_individually() -> None:
    checks_common = _read("scripts/checks_common.ps1")

    assert "foreach ($target in $script:ImmoAppMypyTargets)" in checks_common
    assert "-m mypy @script:ImmoAppMypyTargets" not in checks_common
