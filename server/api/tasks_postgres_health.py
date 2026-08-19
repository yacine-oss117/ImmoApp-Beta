"""Periodic Postgres match-artifact health sampling tasks."""

from __future__ import annotations

from server.services import match_runtime_profile, postgres_match_health, work_admission

from .tasks_core import logger, task_decorator


@task_decorator(name="snapshot_postgres_match_health")
def snapshot_postgres_match_health(_task: object) -> dict[str, object]:
    """Collect a Postgres health snapshot and update the runtime profile state."""
    current_payload = match_runtime_profile.raw_profile_state_payload()
    captured_at = (
        str(current_payload.get("snapshot_captured_at") or "")
        if isinstance(current_payload, dict)
        else ""
    )
    sample_age = match_runtime_profile.sample_age_seconds_from_captured_at(captured_at)
    interval_seconds = work_admission.runtime_sample_interval_seconds()
    if current_payload and sample_age < interval_seconds:
        state = match_runtime_profile.effective_profile_state()
        return {
            "collector_ok": True,
            "profile": state.profile,
            "reason": state.reason,
            "captured_at": captured_at,
            "skipped": True,
            "interval_seconds": interval_seconds,
        }
    snapshot = postgres_match_health.collect_match_artifact_health_snapshot()
    captured_at = snapshot.db_snapshot.captured_at
    if not snapshot.collector_ok:
        state = match_runtime_profile.effective_profile_state()
        return {
            "collector_ok": False,
            "collector_error": snapshot.collector_error,
            "profile": state.profile,
            "reason": state.reason,
            "captured_at": captured_at,
        }
    try:
        next_state = match_runtime_profile.evaluate_profile_transition(snapshot, current_payload)
        stored_state = match_runtime_profile.store_profile_state(
            next_state,
            snapshot_captured_at=captured_at,
            current_payload=current_payload,
            snapshot=snapshot,
        )
        return {
            "collector_ok": bool(snapshot.collector_ok),
            "collector_error": None,
            "profile": stored_state.profile,
            "reason": stored_state.reason,
            "captured_at": captured_at,
        }
    except Exception:
        logger.warning("Failed to update match runtime profile state", exc_info=True)
        return {
            "collector_ok": bool(snapshot.collector_ok),
            "collector_error": snapshot.collector_error,
            "profile": match_runtime_profile.effective_profile_state().profile,
            "reason": match_runtime_profile.effective_profile_state().reason,
            "captured_at": captured_at,
        }


__all__ = ["snapshot_postgres_match_health"]
