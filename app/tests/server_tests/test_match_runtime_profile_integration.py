from __future__ import annotations

from server.services import match_runtime_profile, postgres_match_health


class _StoreCapture(list[tuple[str, str]]):
    def __call__(self, state, *, snapshot_captured_at, current_payload, snapshot):
        self.append((state.profile, state.reason))
        return state


def _snapshot() -> postgres_match_health.MatchArtifactHealthSnapshot:
    table = postgres_match_health.MatchArtifactTableHealth(
        table_name="match_pairs",
        live_tuples=100,
        dead_tuples=0,
        dead_ratio=0.0,
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


def test_snapshot_task_collects_and_stores_profile_state(monkeypatch) -> None:
    from server.api import tasks_postgres_health

    stored = _StoreCapture()
    snapshot = _snapshot()

    monkeypatch.setattr(
        tasks_postgres_health.postgres_match_health,
        "collect_match_artifact_health_snapshot",
        lambda: snapshot,
    )
    monkeypatch.setattr(
        tasks_postgres_health.match_runtime_profile, "raw_profile_state_payload", lambda: {}
    )
    monkeypatch.setattr(
        tasks_postgres_health.match_runtime_profile,
        "evaluate_profile_transition",
        lambda _snapshot, _current: match_runtime_profile.MatchRuntimeProfileState(
            profile="green",
            reason="green_recovered",
            updated_at="2026-03-09T00:00:00+00:00",
            sample_age_seconds=0,
            stale=False,
        ),
    )
    monkeypatch.setattr(tasks_postgres_health.match_runtime_profile, "store_profile_state", stored)

    result = tasks_postgres_health.snapshot_postgres_match_health.run()

    assert result == {
        "collector_ok": True,
        "collector_error": None,
        "profile": "green",
        "reason": "green_recovered",
        "captured_at": "2026-03-09T00:00:00+00:00",
    }
    assert stored == [("green", "green_recovered")]


def test_snapshot_task_falls_back_to_effective_state_on_store_failure(monkeypatch) -> None:
    from server.api import tasks_postgres_health

    snapshot = _snapshot()

    monkeypatch.setattr(
        tasks_postgres_health.postgres_match_health,
        "collect_match_artifact_health_snapshot",
        lambda: snapshot,
    )
    monkeypatch.setattr(
        tasks_postgres_health.match_runtime_profile, "raw_profile_state_payload", lambda: {}
    )
    monkeypatch.setattr(
        tasks_postgres_health.match_runtime_profile,
        "evaluate_profile_transition",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    monkeypatch.setattr(
        tasks_postgres_health.match_runtime_profile,
        "effective_profile_state",
        lambda: match_runtime_profile.MatchRuntimeProfileState(
            profile="yellow",
            reason="cache_unavailable",
            updated_at="2026-03-09T00:00:00+00:00",
            sample_age_seconds=901,
            stale=True,
        ),
    )

    result = tasks_postgres_health.snapshot_postgres_match_health.run()

    assert result["profile"] == "yellow"
    assert result["reason"] == "cache_unavailable"


def test_snapshot_task_does_not_store_profile_on_durable_snapshot_failure(monkeypatch) -> None:
    from server.api import tasks_postgres_health

    snapshot = postgres_match_health.MatchArtifactHealthSnapshot(
        db_snapshot=_snapshot().db_snapshot,
        collector_ok=False,
        collector_error="persist failed",
    )
    stored = _StoreCapture()

    monkeypatch.setattr(
        tasks_postgres_health.postgres_match_health,
        "collect_match_artifact_health_snapshot",
        lambda: snapshot,
    )
    monkeypatch.setattr(
        tasks_postgres_health.match_runtime_profile, "raw_profile_state_payload", lambda: {}
    )
    monkeypatch.setattr(tasks_postgres_health.match_runtime_profile, "store_profile_state", stored)
    monkeypatch.setattr(
        tasks_postgres_health.match_runtime_profile,
        "effective_profile_state",
        lambda: match_runtime_profile.MatchRuntimeProfileState(
            profile="yellow",
            reason="cache_unavailable",
            updated_at="2026-03-09T00:00:00+00:00",
            sample_age_seconds=901,
            stale=True,
        ),
    )

    result = tasks_postgres_health.snapshot_postgres_match_health.run()

    assert result["collector_ok"] is False
    assert result["collector_error"] == "persist failed"
    assert stored == []


def test_tasks_match_pairs_profile_helpers_use_effective_profile(monkeypatch) -> None:
    from server.api import tasks_match_pairs

    monkeypatch.setattr(
        tasks_match_pairs.match_runtime_profile,
        "resolve_effective_profile",
        lambda: match_runtime_profile.MatchRuntimeProfileSettings(
            name="yellow",
            demande_batch_size=200,
            task_chunk_size=750,
            full_sql_threshold=200,
        ),
    )

    assert tasks_match_pairs._demande_batch_size() == 200
    assert tasks_match_pairs._demande_task_chunk_size() == 750
    assert tasks_match_pairs._demande_full_sql_threshold() == 200
