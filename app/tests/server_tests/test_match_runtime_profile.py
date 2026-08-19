from __future__ import annotations

from datetime import UTC, datetime, timedelta

from core.runtime.hub_runtime_profile import HubRuntimeLimits
from server.services import match_runtime_profile, postgres_match_health


def _table(
    *, dead_ratio: float = 0.0, dead_tuples: int = 0, index_bloat: int = 0
) -> postgres_match_health.MatchArtifactTableHealth:
    return postgres_match_health.MatchArtifactTableHealth(
        table_name="match_pairs",
        live_tuples=max(1, 100 - dead_tuples),
        dead_tuples=dead_tuples,
        dead_ratio=dead_ratio,
        table_bytes=1024,
        index_bytes=2048,
        total_bytes=3072,
        index_bloat_estimate_bytes=index_bloat,
        last_autovacuum=None,
        autovacuum_count=0,
        last_autoanalyze=None,
        autoanalyze_count=0,
        vacuum_lag_seconds=None,
        analyze_lag_seconds=None,
    )


def _snapshot(
    *,
    dead_ratio: float = 0.0,
    temp_bytes_delta_5m: int = 0,
    active_connection_ratio: float = 0.0,
    statement_timeout_delta_5m: int = 0,
    lock_timeout_delta_5m: int = 0,
    index_bloat: int = 0,
) -> postgres_match_health.MatchArtifactHealthSnapshot:
    return postgres_match_health.MatchArtifactHealthSnapshot(
        db_snapshot=postgres_match_health.MatchArtifactDbSnapshot(
            captured_at=datetime.now(tz=UTC).isoformat(),
            active_connections=1,
            max_connections=10,
            active_connection_ratio=active_connection_ratio,
            temp_bytes_total=0,
            temp_bytes_delta_5m=temp_bytes_delta_5m,
            temp_files_total=0,
            temp_files_delta_5m=0,
            statement_timeout_count=0,
            lock_timeout_count=0,
            statement_timeout_delta_5m=statement_timeout_delta_5m,
            lock_timeout_delta_5m=lock_timeout_delta_5m,
            match_candidates=_table(
                dead_ratio=dead_ratio,
                dead_tuples=60000 if dead_ratio else 0,
                index_bloat=index_bloat,
            ),
            match_pairs=_table(
                dead_ratio=dead_ratio,
                dead_tuples=60000 if dead_ratio else 0,
                index_bloat=index_bloat,
            ),
        ),
        collector_ok=True,
        collector_error=None,
    )


class _StateRecorder(list[tuple[str, str, int, bool]]):
    def __call__(self, *, profile: str, reason: str, sample_age_seconds: int, stale: bool) -> None:
        self.append((profile, reason, sample_age_seconds, stale))


class _HubProfile:
    def __init__(self, limits: HubRuntimeLimits) -> None:
        self._limits = limits

    def effective_limits(self) -> HubRuntimeLimits:
        return self._limits


def _hub_limits(*, match_batch_size: int) -> HubRuntimeLimits:
    return HubRuntimeLimits(
        worker_concurrency=6,
        import_concurrency=3,
        match_concurrency=3,
        rebuild_concurrency=2,
        max_background_jobs=6,
        db_pool_size=12,
        db_max_overflow=4,
        default_batch_size=500,
        match_batch_size=match_batch_size,
        import_batch_size=500,
        polling_interval_seconds=0.25,
        max_media_thumbnail_concurrency=4,
        startup_warmup_enabled=True,
        web_concurrency=4,
        asgi_threads=48,
    )


def test_evaluate_profile_transition_cold_start_requires_three_healthy_samples() -> None:
    healthy = _snapshot()

    first = match_runtime_profile.evaluate_profile_transition(healthy, None)
    second = match_runtime_profile.evaluate_profile_transition(
        healthy,
        {
            "profile": "yellow",
            "reason": "cold_start_no_baseline",
            "healthy_green_streak": 1,
        },
    )
    third = match_runtime_profile.evaluate_profile_transition(
        healthy,
        {
            "profile": "yellow",
            "reason": "yellow_stable",
            "healthy_green_streak": 2,
        },
    )

    assert first.profile == "yellow"
    assert first.reason == "cold_start_no_baseline"
    assert second.profile == "yellow"
    assert second.reason == "yellow_stable"
    assert third.profile == "green"
    assert third.reason == "green_recovered"


def test_evaluate_profile_transition_enters_yellow_on_timeout_delta() -> None:
    snapshot = _snapshot(statement_timeout_delta_5m=1)

    state = match_runtime_profile.evaluate_profile_transition(
        snapshot,
        {
            "profile": "green",
            "reason": "green_stable",
            "yellow_violation_streak": 1,
        },
    )

    assert state.profile == "yellow"
    assert state.reason == "yellow_statement_timeout"


def test_evaluate_profile_transition_enters_red_on_index_bloat() -> None:
    snapshot = _snapshot(index_bloat=match_runtime_profile._red_index_bloat_bytes() + 1)

    state = match_runtime_profile.evaluate_profile_transition(
        snapshot,
        {
            "profile": "yellow",
            "reason": "yellow_stable",
            "red_violation_streak": 1,
        },
    )

    assert state.profile == "red"
    assert state.reason == "red_index_bloat"


def test_resolve_effective_profile_falls_back_to_yellow_when_cache_unavailable(monkeypatch) -> None:
    recorder = _StateRecorder()

    monkeypatch.delenv("IMMOAPP_MATCH_RUNTIME_PROFILE", raising=False)
    monkeypatch.setattr(match_runtime_profile, "record_match_runtime_profile_state", recorder)
    monkeypatch.setattr(match_runtime_profile, "_safe_cache_get_dict", lambda _key: None)

    profile = match_runtime_profile.resolve_effective_profile()

    assert profile.name == "yellow"
    assert recorder[-1][1] == "cache_unavailable"
    assert recorder[-1][3] is True


def test_resolve_effective_profile_uses_stale_fail_safe(monkeypatch) -> None:
    recorder = _StateRecorder()
    stale_at = (datetime.now(tz=UTC) - timedelta(seconds=3600)).isoformat()

    monkeypatch.delenv("IMMOAPP_MATCH_RUNTIME_PROFILE", raising=False)
    monkeypatch.setattr(match_runtime_profile, "record_match_runtime_profile_state", recorder)
    monkeypatch.setattr(
        match_runtime_profile,
        "_safe_cache_get_dict",
        lambda _key: {
            "profile": "green",
            "reason": "green_stable",
            "updated_at": stale_at,
            "snapshot_captured_at": stale_at,
        },
    )

    profile = match_runtime_profile.resolve_effective_profile()

    assert profile.name == "yellow"
    assert recorder[-1][1] == "stale_health_snapshot_fail_safe"
    assert recorder[-1][3] is True


def test_manual_override_pins_profile(monkeypatch) -> None:
    recorder = _StateRecorder()

    monkeypatch.setenv("IMMOAPP_MATCH_RUNTIME_PROFILE", "red")
    monkeypatch.setattr(match_runtime_profile, "record_match_runtime_profile_state", recorder)

    profile = match_runtime_profile.resolve_effective_profile()

    assert profile.name == "red"
    assert recorder[-1][1] == "manual_red"


def test_settings_for_profile_are_bounded_by_hub_profile(monkeypatch) -> None:
    monkeypatch.setenv("IMMOAPP_MATCH_PAIRS_DEMANDE_BATCH_SIZE", "2000")
    monkeypatch.setenv("IMMOAPP_MATCH_PAIRS_TASK_CHUNK_SIZE", "5000")
    monkeypatch.setenv("IMMOAPP_MATCH_PAIRS_FULL_SQL_THRESHOLD", "5000")
    monkeypatch.setattr(
        match_runtime_profile,
        "resolve_hub_runtime_profile",
        lambda: _HubProfile(_hub_limits(match_batch_size=50)),
    )

    profile = match_runtime_profile.settings_for_profile("green")

    assert profile.name == "green"
    assert profile.demande_batch_size == 50
    assert profile.task_chunk_size == 50
    assert profile.full_sql_threshold == 50


def test_match_pressure_only_reduces_from_hub_baseline(monkeypatch) -> None:
    monkeypatch.setattr(
        match_runtime_profile,
        "resolve_hub_runtime_profile",
        lambda: _HubProfile(_hub_limits(match_batch_size=250)),
    )

    green = match_runtime_profile.settings_for_profile("green")
    red = match_runtime_profile.settings_for_profile("red")

    assert green.demande_batch_size == 250
    assert red.demande_batch_size == 125
    assert red.demande_batch_size <= green.demande_batch_size
