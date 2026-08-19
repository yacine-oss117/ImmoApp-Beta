from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from app.tests.server_tests._integration_auth_helpers import ensure_django

ensure_django()

from server.services import health as health_service  # noqa: E402
from server.services import match_runtime_profile, postgres_match_health  # noqa: E402


def _base_snapshot() -> health_service.HealthSnapshot:
    return health_service.HealthSnapshot(
        db_path="postgres://localhost:5432/immoapp",
        active_connections=1,
        audit_actor="system",
        schema_version="1",
        settings_schema_version="1",
        last_repair=None,
        last_backup_ts=None,
        last_backup_reason=None,
        last_backup_path=None,
    )


def _match_snapshot() -> postgres_match_health.MatchArtifactHealthSnapshot:
    table = postgres_match_health.MatchArtifactTableHealth(
        table_name="match_pairs",
        live_tuples=100,
        dead_tuples=10,
        dead_ratio=0.09,
        table_bytes=1024,
        index_bytes=2048,
        total_bytes=3072,
        index_bloat_estimate_bytes=0,
        last_autovacuum=None,
        autovacuum_count=0,
        last_autoanalyze=None,
        autoanalyze_count=0,
        vacuum_lag_seconds=None,
        analyze_lag_seconds=None,
    )
    db_snapshot = postgres_match_health.MatchArtifactDbSnapshot(
        captured_at="2026-03-09T00:00:00+00:00",
        active_connections=1,
        max_connections=10,
        active_connection_ratio=0.1,
        temp_bytes_total=0,
        temp_bytes_delta_5m=0,
        temp_files_total=0,
        temp_files_delta_5m=0,
        statement_timeout_count=0,
        lock_timeout_count=0,
        statement_timeout_delta_5m=0,
        lock_timeout_delta_5m=0,
        match_candidates=table,
        match_pairs=table,
    )
    return postgres_match_health.MatchArtifactHealthSnapshot(
        db_snapshot=db_snapshot,
        collector_ok=True,
        collector_error=None,
    )


def test_health_snapshot_includes_match_artifact_health_for_admin(monkeypatch) -> None:
    monkeypatch.setattr(health_service, "fetch_health_snapshot", _base_snapshot)
    monkeypatch.setattr(health_service, "get_pool_stats", lambda: {})
    monkeypatch.setattr(health_service, "get_cache_stats", lambda: {})
    monkeypatch.setattr(
        health_service,
        "import_security_limits_snapshot",
        lambda: {"max_rows": 20000, "cache_policy": "process_cached_until_reload_or_restart"},
    )
    monkeypatch.setattr(health_service, "_check_database", lambda: {"ok": True})
    monkeypatch.setattr(health_service, "_check_cache", lambda: {"ok": True})
    monkeypatch.setattr(health_service, "_check_broker", lambda: {"ok": True})
    monkeypatch.setattr(health_service.tenant_usage_gauge, "compute_all_tenant_usage", lambda: [])
    monkeypatch.setattr(
        health_service.postgres_match_health, "load_match_artifact_health_snapshot", _match_snapshot
    )
    monkeypatch.setattr(
        health_service.match_runtime_profile,
        "effective_profile_state",
        lambda: match_runtime_profile.MatchRuntimeProfileState(
            profile="green",
            reason="green_stable",
            updated_at="2026-03-09T00:00:00+00:00",
            sample_age_seconds=5,
            stale=False,
        ),
    )
    monkeypatch.setattr(
        health_service.import_execution_governor,
        "import_runtime_health_payload",
        lambda: {
            "profile": "green",
            "queue_depth": 1,
            "budget_pressure": "stable",
        },
    )
    monkeypatch.setattr(
        health_service,
        "import_runtime_maintenance",
        SimpleNamespace(
            runtime_health_snapshot=lambda: {
                "stale_temp_dirs": 0,
                "stale_artifact_jobs": 0,
                "cancelled_import_phases": 1,
                "requeued_expired_phases": 2,
            }
        ),
    )
    monkeypatch.setattr(
        health_service.tenant_resource_governor,
        "budget_state_snapshot",
        lambda **_kwargs: {
            "import_execute": {"1": {"remaining": 3}},
            "match_pairs_rebuild": {"1": {"remaining": 2}},
        },
    )

    payload = health_service.health_snapshot(include_tenant_usage=True)

    assert payload["match_runtime_profile"] == "green"
    assert payload["match_runtime_profile_reason"] == "green_stable"
    assert payload["match_runtime_profile_sample_age_seconds"] == 5
    assert dict(payload["import_security_limits"])["cache_policy"] == (
        "process_cached_until_reload_or_restart"
    )
    assert payload["match_artifact_health"]["collector_ok"] is True
    assert dict(payload["import_runtime_health"])["profile"] == "green"
    assert dict(payload["import_runtime_cleanup"])["cancelled_import_phases"] == 1
    assert isinstance(payload["tenant_surface_classification_version"], str)
    assert dict(payload["tenant_budget_state"])["import_execute"]["1"]["remaining"] == 3
    assert dict(payload["offline_sync_health"])["available"] is False
    assert "match_rebuild_health" in payload


def test_health_snapshot_omits_match_artifact_health_for_non_admin(monkeypatch) -> None:
    monkeypatch.setattr(health_service, "fetch_health_snapshot", _base_snapshot)
    monkeypatch.setattr(health_service, "get_pool_stats", lambda: {})
    monkeypatch.setattr(health_service, "get_cache_stats", lambda: {})
    monkeypatch.setattr(
        health_service,
        "import_security_limits_snapshot",
        lambda: {"max_rows": 20000, "cache_policy": "process_cached_until_reload_or_restart"},
    )
    monkeypatch.setattr(health_service, "_check_database", lambda: {"ok": True})
    monkeypatch.setattr(health_service, "_check_cache", lambda: {"ok": True})
    monkeypatch.setattr(health_service, "_check_broker", lambda: {"ok": True})

    payload = health_service.health_snapshot(include_tenant_usage=False)

    assert "match_artifact_health" not in payload
    assert "match_runtime_profile" not in payload
    assert dict(payload["import_security_limits"])["max_rows"] == 20000


def test_match_artifact_health_payload_no_longer_exposes_split_timeout_sample() -> None:
    source = Path("server/services/postgres_match_health.py").read_text(encoding="utf-8")

    assert "external_timeout_sample" not in source
    assert "MatchArtifactExternalTimeoutSample" not in source
