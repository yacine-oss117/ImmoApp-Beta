from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

import pytest

from core.runtime.hub_runtime_profile import (
    HubRuntimeProfileError,
    MachineCapacity,
    ensure_hub_runtime_profile,
    load_hub_runtime_profile,
    resolve_hub_runtime_profile,
    snapshot_hub_memory_pressure,
    summarize_hub_runtime_profile,
    write_hub_runtime_profile,
)

REPO_ROOT = Path(__file__).resolve().parents[3]


def _capacity(
    cpu: int,
    ram_gb: float,
    *,
    available_gb: float | None = None,
    db_class: str = "large",
    container_cpu_quota: float | None = None,
    container_memory_gb: float | None = None,
) -> MachineCapacity:
    ram_bytes = int(ram_gb * 1024**3)
    available_bytes = int((ram_gb / 2 if available_gb is None else available_gb) * 1024**3)
    return MachineCapacity(
        cpu_count=cpu,
        total_ram_bytes=ram_bytes,
        available_ram_bytes=available_bytes,
        total_ram_gb=ram_gb,
        available_ram_gb=round(available_bytes / 1024**3, 2),
        db_capacity_class=db_class,
        container_cpu_quota=container_cpu_quota,
        container_memory_limit_bytes=(
            int(container_memory_gb * 1024**3) if container_memory_gb is not None else None
        ),
    )


@pytest.fixture(autouse=True)
def _clear_hub_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in tuple(os.environ):
        if name.startswith("IMMOAPP_HUB_") or name in {"IMMOAPP_ENV", "DJANGO_ENV"}:
            monkeypatch.delenv(name, raising=False)
    snapshot_hub_memory_pressure(memory_load_percent=10, reset_streak=True)


@pytest.mark.parametrize(
    ("capacity", "expected"),
    [
        (_capacity(2, 4), "tiny"),
        (_capacity(4, 8), "small"),
        (_capacity(8, 16), "medium"),
        (_capacity(9, 17), "large"),
    ],
)
def test_machine_capacity_resolves_expected_profile(
    capacity: MachineCapacity, expected: str
) -> None:
    assert resolve_hub_runtime_profile(capacity=capacity).profile_name == expected


def test_many_cores_low_total_ram_does_not_resolve_above_small() -> None:
    assert resolve_hub_runtime_profile(capacity=_capacity(24, 4)).profile_name == "tiny"
    assert resolve_hub_runtime_profile(capacity=_capacity(24, 8)).profile_name == "small"


def test_mixed_cpu_ram_uses_weakest_stable_capacity_dimension() -> None:
    medium = resolve_hub_runtime_profile(capacity=_capacity(12, 16))
    assert medium.profile_name == "medium"
    assert medium.effective_cpu_budget == 12
    assert medium.limits.worker_concurrency == 4
    assert medium.limits.import_concurrency == 2
    assert medium.limits.match_concurrency == 2
    assert medium.limits.db_pool_size == 8

    assert resolve_hub_runtime_profile(capacity=_capacity(12, 32)).profile_name == "large"
    assert resolve_hub_runtime_profile(capacity=_capacity(4, 32)).profile_name == "small"
    assert resolve_hub_runtime_profile(capacity=_capacity(2, 64)).profile_name == "tiny"


def test_selected_profile_limits_are_distinct_from_effective_cpu_budget() -> None:
    profile = resolve_hub_runtime_profile(capacity=_capacity(12, 16))
    summary = summarize_hub_runtime_profile(profile)
    assert summary["selected_profile"] == "medium"
    assert summary["profile_source"] == "auto"
    assert summary["effective_cpu_budget"] == 12
    selected_limits = cast(dict[str, Any], summary["selected_profile_limits"])
    assert selected_limits["worker_concurrency"] == 4
    assert summary["reason"] == profile.explanation
    assert summary["raw_free_ram_diagnostics_only"] is True


def test_summary_distinguishes_auto_from_persisted_config(tmp_path: Path) -> None:
    path = tmp_path / "hub_runtime_profile.json"
    profile = resolve_hub_runtime_profile(capacity=_capacity(12, 16))
    assert summarize_hub_runtime_profile(profile)["profile_source"] == "auto"

    write_hub_runtime_profile(profile, path)
    loaded = load_hub_runtime_profile(path)
    assert loaded is not None
    persisted_summary = summarize_hub_runtime_profile(loaded)
    assert persisted_summary["source"] == "persisted_config"
    assert persisted_summary["profile_source"] == "persisted_config"
    assert persisted_summary["reason"]


def test_low_free_ram_does_not_drive_baseline_classification() -> None:
    profile = resolve_hub_runtime_profile(capacity=_capacity(12, 32, available_gb=0.2))
    assert profile.profile_name == "large"
    assert profile.detected_available_ram_gb == 0.2


def test_active_runtime_envelope_uses_effective_cpu_and_memory_minimums() -> None:
    capacity = MachineCapacity(
        cpu_count=12,
        total_ram_bytes=32 * 1024**3,
        available_ram_bytes=16 * 1024**3,
        total_ram_gb=32,
        available_ram_gb=16,
        db_capacity_class="large",
        effective_cpu_budget=2,
        effective_memory_bytes=4 * 1024**3,
    )
    profile = resolve_hub_runtime_profile(capacity=capacity)
    assert profile.effective_cpu_budget == 2
    assert profile.effective_memory_gb == 4
    assert profile.profile_name == "tiny"


def test_runtime_profile_records_wsl_policy_as_planned_metadata_only() -> None:
    profile = resolve_hub_runtime_profile(capacity=_capacity(12, 32))
    summary = profile.to_json_dict()
    assert summary["selected_profile"] == "large"
    assert summary["planned_wsl_memory_gb"] is None
    assert summary["planned_wsl_processors"] is None
    assert summary["cap_is_ceiling_not_reservation"] is True
    assert summary["sustained_pressure_backoff_required"] is True


def test_container_limits_reduce_effective_budgets() -> None:
    profile = resolve_hub_runtime_profile(
        capacity=_capacity(12, 32, container_cpu_quota=2.0, container_memory_gb=4)
    )
    assert profile.profile_name == "tiny"
    assert profile.effective_cpu_budget == 2
    assert profile.effective_memory_gb == 4


def test_invalid_profile_override_fails_clearly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IMMOAPP_HUB_PROFILE", "giant")
    with pytest.raises(HubRuntimeProfileError, match="IMMOAPP_HUB_PROFILE"):
        resolve_hub_runtime_profile(capacity=_capacity(8, 16))


def test_invalid_numeric_override_fails_clearly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IMMOAPP_HUB_WORKER_CONCURRENCY", "many")
    with pytest.raises(HubRuntimeProfileError, match="worker_concurrency"):
        resolve_hub_runtime_profile(capacity=_capacity(8, 16))


def test_invalid_boolean_override_fails_clearly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IMMOAPP_HUB_ALLOW_UNSAFE_OVERRIDES", "maybe")
    with pytest.raises(HubRuntimeProfileError, match="IMMOAPP_HUB_ALLOW_UNSAFE_OVERRIDES"):
        resolve_hub_runtime_profile(capacity=_capacity(8, 16))


def test_production_rejects_unsafe_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IMMOAPP_ENV", "production")
    monkeypatch.setenv("IMMOAPP_HUB_WORKER_CONCURRENCY", "8")
    with pytest.raises(HubRuntimeProfileError, match="production/staging"):
        resolve_hub_runtime_profile(capacity=_capacity(2, 4))


def test_developer_profile_is_explicit_local_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IMMOAPP_HUB_RUNTIME_MODE", "local_dev")
    monkeypatch.setenv("IMMOAPP_HUB_PROFILE", "developer")
    profile = resolve_hub_runtime_profile(capacity=_capacity(4, 8))
    assert profile.profile_name == "developer"
    assert profile.limits.worker_concurrency == 6

    monkeypatch.setenv("IMMOAPP_ENV", "production")
    with pytest.raises(HubRuntimeProfileError, match="developer"):
        resolve_hub_runtime_profile(capacity=_capacity(12, 32))

    monkeypatch.delenv("IMMOAPP_ENV", raising=False)
    monkeypatch.delenv("IMMOAPP_HUB_RUNTIME_MODE", raising=False)
    with pytest.raises(HubRuntimeProfileError, match="local_dev/ci"):
        resolve_hub_runtime_profile(capacity=_capacity(12, 32))


def test_custom_override_is_allowed_with_local_unsafe_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("IMMOAPP_HUB_RUNTIME_MODE", "local_dev")
    monkeypatch.setenv("IMMOAPP_HUB_ALLOW_UNSAFE_OVERRIDES", "1")
    profile = resolve_hub_runtime_profile(
        overrides={"worker_concurrency": 6}, capacity=_capacity(4, 8)
    )
    assert profile.profile_name == "small"
    assert profile.profile_source == "env_override"
    assert profile.limits.worker_concurrency == 6
    assert profile.warnings


def test_runtime_overrides_reject_values_above_safe_bounds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("IMMOAPP_HUB_WORKER_CONCURRENCY", "100")
    with pytest.raises(HubRuntimeProfileError, match="hard safe maximum"):
        resolve_hub_runtime_profile(capacity=_capacity(2, 4))

    monkeypatch.delenv("IMMOAPP_HUB_WORKER_CONCURRENCY", raising=False)
    monkeypatch.setenv("IMMOAPP_HUB_DB_POOL_MAX", "100")
    with pytest.raises(HubRuntimeProfileError, match="hard safe maximum"):
        resolve_hub_runtime_profile(capacity=_capacity(4, 8))


def test_runtime_overrides_reject_profile_dependent_oversubscription() -> None:
    with pytest.raises(HubRuntimeProfileError, match="selected capacity safe limit"):
        resolve_hub_runtime_profile(overrides={"worker_concurrency": 6}, capacity=_capacity(4, 8))


def test_conflicting_env_aliases_fail_clearly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IMMOAPP_HUB_DB_POOL_MAX", "4")
    monkeypatch.setenv("IMMOAPP_HUB_DB_POOL_SIZE", "5")
    with pytest.raises(HubRuntimeProfileError, match="Conflicting Hub runtime overrides"):
        resolve_hub_runtime_profile(capacity=_capacity(4, 8))


def test_custom_profile_requires_complete_safe_fields() -> None:
    with pytest.raises(HubRuntimeProfileError, match="requires overrides"):
        resolve_hub_runtime_profile(
            overrides={"profile_name": "custom", "worker_concurrency": 1},
            capacity=_capacity(4, 8),
        )

    profile = resolve_hub_runtime_profile(
        overrides={
            "profile_name": "custom",
            "cpu_budget": 4,
            "memory_gb": 8,
            "worker_concurrency": 2,
            "import_concurrency": 1,
            "match_concurrency": 1,
            "db_pool_size": 4,
        },
        capacity=_capacity(4, 8),
    )
    assert profile.profile_name == "custom"
    assert profile.profile_source == "custom"

    with pytest.raises(HubRuntimeProfileError, match="custom profile"):
        resolve_hub_runtime_profile(
            overrides={
                "profile_name": "custom",
                "cpu_budget": 2,
                "memory_gb": 4,
                "worker_concurrency": 6,
                "import_concurrency": 1,
                "match_concurrency": 1,
                "db_pool_size": 2,
            },
            capacity=_capacity(12, 32),
        )


def test_custom_profile_cannot_bypass_safety_in_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("IMMOAPP_ENV", "production")
    with pytest.raises(HubRuntimeProfileError, match="production/staging"):
        resolve_hub_runtime_profile(
            overrides={
                "profile_name": "custom",
                "cpu_budget": 2,
                "memory_gb": 4,
                "worker_concurrency": 6,
                "import_concurrency": 1,
                "match_concurrency": 1,
                "db_pool_size": 2,
            },
            capacity=_capacity(12, 32),
        )


def test_profile_json_round_trips_as_persisted_config(tmp_path: Path) -> None:
    path = tmp_path / "hub_runtime_profile.json"
    profile = resolve_hub_runtime_profile(capacity=_capacity(4, 8))
    write_hub_runtime_profile(profile, path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["schema_version"] == 2
    assert data["selected_profile"] == "small"
    assert data["profile_limits"]["worker_concurrency"] == 2
    assert data["raw_free_ram_diagnostics_only"] is True
    assert data["capacity_fingerprint"]
    loaded = load_hub_runtime_profile(path)
    assert loaded is not None
    assert loaded.profile_name == "small"
    assert loaded.source == "persisted_config"
    assert loaded.profile_source == "persisted_config"
    assert loaded.limits.worker_concurrency == 2


def test_ensure_generates_missing_profile(tmp_path: Path) -> None:
    path = tmp_path / "hub_runtime_profile.json"
    profile = ensure_hub_runtime_profile(path, capacity=_capacity(4, 8))
    assert profile.profile_name == "small"
    assert path.exists()


def test_stale_auto_profile_regenerates_after_material_capacity_change(tmp_path: Path) -> None:
    path = tmp_path / "hub_runtime_profile.json"
    original = ensure_hub_runtime_profile(path, capacity=_capacity(4, 8))
    assert original.profile_name == "small"

    regenerated = ensure_hub_runtime_profile(path, capacity=_capacity(12, 32))
    assert regenerated.profile_name == "large"
    assert regenerated.stale_config_regenerated is True
    assert "stale auto-generated" in ";".join(regenerated.warnings)

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["selected_profile"] == "large"
    assert data["stale_config_regenerated"] is True


def test_stale_auto_profile_not_regenerated_for_free_ram_change(tmp_path: Path) -> None:
    path = tmp_path / "hub_runtime_profile.json"
    original = ensure_hub_runtime_profile(path, capacity=_capacity(12, 32, available_gb=1))
    loaded = ensure_hub_runtime_profile(path, capacity=_capacity(12, 32, available_gb=28))
    assert loaded.profile_name == original.profile_name
    assert loaded.stale_config_regenerated is False


def test_pinned_profile_remains_pinned_when_current_capacity_can_safely_run_it(
    tmp_path: Path,
) -> None:
    path = tmp_path / "hub_runtime_profile.json"
    pinned = resolve_hub_runtime_profile(
        overrides={"profile_name": "tiny"}, capacity=_capacity(12, 32)
    )
    write_hub_runtime_profile(pinned, path)

    loaded = ensure_hub_runtime_profile(path, capacity=_capacity(12, 32))
    assert loaded.profile_name == "tiny"
    assert loaded.profile_source == "pinned"
    assert loaded.stale_config_regenerated is False


def test_pinned_profile_fails_when_current_capacity_cannot_safely_run_it(
    tmp_path: Path,
) -> None:
    path = tmp_path / "hub_runtime_profile.json"
    pinned = resolve_hub_runtime_profile(
        overrides={"profile_name": "large"}, capacity=_capacity(12, 32)
    )
    write_hub_runtime_profile(pinned, path)

    with pytest.raises(HubRuntimeProfileError, match="above current stable-capacity limit"):
        ensure_hub_runtime_profile(path, capacity=_capacity(4, 8))


def test_invalid_persisted_profile_fails_unless_local_fallback_allowed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "hub_runtime_profile.json"
    path.write_text("{bad-json", encoding="utf-8")
    with pytest.raises(HubRuntimeProfileError, match="invalid"):
        ensure_hub_runtime_profile(path, capacity=_capacity(4, 8))

    monkeypatch.setenv("IMMOAPP_HUB_RUNTIME_MODE", "local_dev")
    monkeypatch.setenv("IMMOAPP_HUB_ALLOW_INVALID_PROFILE_FALLBACK", "1")
    profile = ensure_hub_runtime_profile(path, capacity=_capacity(4, 8))
    assert profile.profile_name == "small"
    assert "invalid persisted profile" in ";".join(profile.warnings)


def test_schema_v2_malformed_persisted_profile_fails_clearly(tmp_path: Path) -> None:
    path = tmp_path / "hub_runtime_profile.json"
    path.write_text(
        json.dumps({"schema_version": 2, "selected_profile": "small"}),
        encoding="utf-8",
    )
    with pytest.raises(HubRuntimeProfileError, match="missing required schema v2 fields"):
        ensure_hub_runtime_profile(path, capacity=_capacity(4, 8))


def test_persisted_profile_with_unsafe_limits_fails(tmp_path: Path) -> None:
    path = tmp_path / "hub_runtime_profile.json"
    profile = resolve_hub_runtime_profile(capacity=_capacity(2, 4))
    payload = profile.to_json_dict()
    payload["final_resolved_limits"]["worker_concurrency"] = 6
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(HubRuntimeProfileError, match="above tiny baseline"):
        load_hub_runtime_profile(path)


def test_pressure_snapshot_clamps_effective_limits_without_rewriting_baseline() -> None:
    profile = resolve_hub_runtime_profile(capacity=_capacity(12, 32))
    yellow = snapshot_hub_memory_pressure(
        memory_load_percent=96,
        commit_headroom_gb=4,
        capacity=_capacity(12, 32),
        reset_streak=True,
    )
    yellow_limits = profile.effective_limits(yellow)
    assert yellow.state == "yellow"
    assert profile.limits.import_concurrency == 3
    assert yellow_limits.import_concurrency == 2
    assert profile.profile_name == "large"

    snapshot_hub_memory_pressure(memory_load_percent=96, commit_headroom_gb=4)
    red = snapshot_hub_memory_pressure(memory_load_percent=96, commit_headroom_gb=4)
    red_limits = profile.effective_limits(red)
    assert red.state == "red"
    assert red_limits.import_concurrency == 1
    assert red_limits.defer_non_urgent_background_jobs is True


def test_profile_generation_script_writes_valid_json(tmp_path: Path) -> None:
    output = tmp_path / "hub_runtime_profile.json"
    env = {
        **os.environ,
        "PYTHONPATH": str(REPO_ROOT),
        "IMMOAPP_HUB_PROFILE": "tiny",
        "IMMOAPP_APPDATA_ROOT": str(tmp_path / "appdata"),
    }
    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "hub_runtime_profile.py"),
            "generate",
            "--output",
            str(output),
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["selected_profile_name"] == "tiny"
    assert data["selected_profile"] == "tiny"
    assert data["source"] == "env_override"
    assert data["schema_version"] == 2
    assert data["profile_source"] == "env_override"
    assert data["final_resolved_limits"]["worker_concurrency"] == 1


def test_startup_export_changes_between_tiny_and_small(tmp_path: Path) -> None:
    def export(profile: str) -> str:
        env = {
            **os.environ,
            "PYTHONPATH": str(REPO_ROOT),
            "IMMOAPP_HUB_PROFILE": profile,
            "IMMOAPP_APPDATA_ROOT": str(tmp_path / profile),
        }
        result = subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "scripts" / "hub_runtime_profile.py"),
                "export-env",
                "--format",
                "dotenv",
            ],
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )
        assert result.returncode == 0, result.stderr
        return result.stdout

    tiny = export("tiny")
    small = export("small")
    assert "CELERY_WORKER_CONCURRENCY_DOCKER=1" in tiny
    assert "GUNICORN_WORKERS_DOCKER=1" in tiny
    assert "IMMOAPP_HUB_DB_POOL_MAX=2" in tiny
    assert "CELERY_WORKER_CONCURRENCY_DOCKER=2" in small
    assert "GUNICORN_WORKERS_DOCKER=2" in small


def test_script_export_env_matches_python_owner_for_tiny_and_medium(tmp_path: Path) -> None:
    def parse_dotenv(text: str) -> dict[str, str]:
        result: dict[str, str] = {}
        for line in text.splitlines():
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            result[key] = value
        return result

    for profile_name in ("tiny", "medium"):
        profile_path = tmp_path / profile_name / "hub_runtime_profile.json"
        env = {
            **os.environ,
            "PYTHONPATH": str(REPO_ROOT),
            "IMMOAPP_HUB_PROFILE": profile_name,
            "IMMOAPP_APPDATA_ROOT": str(tmp_path / f"appdata-{profile_name}"),
        }
        result = subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "scripts" / "hub_runtime_profile.py"),
                "export-env",
                "--output",
                str(profile_path),
                "--format",
                "dotenv",
            ],
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )
        assert result.returncode == 0, result.stderr
        loaded = load_hub_runtime_profile(profile_path)
        assert loaded is not None
        exported = parse_dotenv(result.stdout)
        for key, expected_value in loaded.to_env().items():
            if key in {
                "IMMOAPP_HUB_PROFILE_SOURCE",
                "IMMOAPP_HUB_PROFILE_SOURCE_DOCKER",
                "IMMOAPP_HUB_PROFILE_SOURCE_DETAIL",
            }:
                continue
            assert exported[key] == expected_value


def test_simulated_small_hub_proof_passes() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "verify_small_hub_runtime_profile.py"),
            "--profile",
            "tiny",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert '"profile": "tiny"' in result.stdout
