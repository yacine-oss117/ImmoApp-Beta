from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
OWNER = Path("core/runtime/hub_runtime_profile.py")


def _read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def _python_files() -> list[Path]:
    roots = [REPO_ROOT / "core", REPO_ROOT / "server"]
    return [
        path
        for root in roots
        for path in root.rglob("*.py")
        if "__pycache__" not in path.parts
        and path.relative_to(REPO_ROOT) != OWNER
        and "test" not in path.name
    ] + [REPO_ROOT / "scripts" / "hub_runtime_profile.py"]


def test_no_backend_direct_cpu_or_ram_detection_outside_owner() -> None:
    offenders: list[str] = []
    for path in _python_files():
        text = path.read_text(encoding="utf-8")
        if "os.cpu_count(" in text or "psutil.virtual_memory(" in text:
            offenders.append(str(path.relative_to(REPO_ROOT)))
    assert offenders == []


def test_no_raw_free_memory_gating_outside_runtime_owner() -> None:
    offenders: list[str] = []
    forbidden = ("available_ram_bytes", "available_ram_gb", "free_memory", "free_ram")
    for path in _python_files():
        text = path.read_text(encoding="utf-8").lower()
        if any(token in text for token in forbidden):
            offenders.append(str(path.relative_to(REPO_ROOT)))
    assert offenders == []


def test_compose_celery_commands_use_profile_derived_concurrency() -> None:
    compose = _read("deployment/compose/compose.yml")
    prod = _read("deployment/compose/compose.prod.yml")
    assert "hub_runtime_profile_required" in compose
    assert "hub_runtime_profile_required" in prod
    for required in (
        "GUNICORN_WORKERS_DOCKER:?hub_runtime_profile_required",
        "ASGI_THREADS_DOCKER:?hub_runtime_profile_required",
        "PG_POOL_MAX_WEB_DOCKER:?hub_runtime_profile_required",
        "IMMOAPP_WEB_BIND_HOST:-127.0.0.1",
    ):
        assert required in compose
    for forbidden in ("-c 3", "-c 4", "concurrency = 12", "workers = 12", "max_workers=12"):
        assert forbidden not in compose
        assert forbidden not in prod


def test_startup_scripts_delegate_profile_calculation_to_python_owner() -> None:
    common = _read("scripts/common.ps1")
    stack = _read("scripts/stack.ps1")
    run_web = _read("deployment/docker/run_web.sh")
    assert "scripts\\hub_runtime_profile.py" in common
    assert "Set-ImmoAppHubRuntimeProfileEnv" in stack
    assert '"up-infra"' in stack
    assert '"logs-infra"' in stack
    assert "from core.runtime.hub_runtime_profile import ensure_hub_runtime_profile" in run_web

    threshold_tokens = (
        "<=2",
        "<= 2",
        "<=4",
        "<= 4",
        "<=8",
        "<= 8",
        "<=16",
        "<= 16",
        "16 GB",
        "tiny:",
        "small:",
        "medium:",
        "large:",
    )
    for text in (common, stack, run_web):
        lowered = text.lower()
        assert not any(token.lower() in lowered for token in threshold_tokens)
    assert "cpu_count" not in run_web
    assert "virtual_memory" not in run_web


def test_managed_wsl2_policy_has_single_owner_and_config_writer() -> None:
    policy = _read("scripts/managed_wsl2_runtime_policy.ps1")
    configure = _read("scripts/configure_managed_wsl2_runtime.ps1")
    assert "MachineTotalMemoryGb" in policy
    assert "MachineLogicalProcessors" in policy
    assert "available_ram" not in policy.lower()
    assert "free_ram" not in policy.lower()
    assert "ConfirmGlobalWslConfigChange" in configure
    assert "AllowMergeExistingWslConfig" in configure
    assert "wsl --shutdown" in configure
    for script in (REPO_ROOT / "scripts").glob("*.ps1"):
        if script.name == "configure_managed_wsl2_runtime.ps1":
            continue
        text = script.read_text(encoding="utf-8")
        assert ".wslconfig" not in text or "wslconfig_path" in text or "wslconfig_present" in text


def test_import_match_and_support_evidence_read_hub_profile() -> None:
    assert "resolve_hub_runtime_profile" in _read("server/services/import_execution_governor.py")
    assert "resolve_hub_runtime_profile" in _read("server/services/match_runtime_profile.py")
    assert "hub_runtime_profile.json" in _read("app/services/support_bundle.py")
    beta = _read("scripts/run_beta_release_validation.ps1")
    for token in (
        "hub_runtime_profile",
        "hub_runtime_worker_concurrency",
        "hub_runtime_import_concurrency",
        "hub_runtime_match_concurrency",
        "hub_runtime_db_pool_size",
        "hub_runtime_source",
        "hub_runtime_effective_cpu_budget",
        "hub_runtime_effective_memory_gb",
        "hub_runtime_pressure_state",
        "hub_runtime_profile_source",
        "hub_runtime_reason",
        "hub_runtime_capacity_fingerprint",
        "hub_runtime_stale_config_regenerated",
    ):
        assert token in beta


def test_match_runtime_profile_remains_pressure_controller_bounded_by_hub() -> None:
    text = _read("server/services/match_runtime_profile.py")
    assert "evaluate_profile_transition" in text
    assert "_bound_settings_by_hub_profile" in text
    assert "hub_limits.match_batch_size" in text
