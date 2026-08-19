from __future__ import annotations

import json

from app.services import onboarding_analytics as module


def test_quick_start_seen_state_roundtrip(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("IMMOAPP_APPDATA_ROOT", str(tmp_path))

    assert module.should_show_quick_start() is True
    module.mark_quick_start_seen(seen=True)
    assert module.has_seen_quick_start() is True
    assert module.should_show_quick_start() is False


def test_record_onboarding_event_writes_sanitized_payload(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("IMMOAPP_APPDATA_ROOT", str(tmp_path))
    module.record_onboarding_event(
        "Sign In Submitted",
        step="Login Step 1",
        outcome="HTTP 401",
        metadata={"email": "owner@example.com", "reason": "Bad Password"},
    )

    path = tmp_path / "logs" / "onboarding_events.jsonl"
    assert path.exists()
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["event"] == "sign_in_submitted"
    assert payload["step"] == "login_step_1"
    assert payload["outcome"] == "http_401"
    # Unapproved metadata keys are dropped to avoid PII leakage.
    assert payload.get("meta") == {"reason": "bad_password"}


def test_next_steps_visibility_tracks_launches_and_dismissal(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("IMMOAPP_APPDATA_ROOT", str(tmp_path))

    assert module.get_app_launch_count() == 0
    assert module.increment_app_launch_count() == 1
    assert module.should_show_next_steps_card(max_launches=3) is True

    module.increment_app_launch_count()
    module.increment_app_launch_count()
    module.increment_app_launch_count()
    assert module.should_show_next_steps_card(max_launches=3) is False

    module.dismiss_next_steps_card(dismissed=True)
    assert module.should_show_next_steps_card(max_launches=5) is False

    module.reset_next_steps_card()
    assert module.should_show_next_steps_card(max_launches=5) is True


def test_funnel_snapshot_counts_started_completed_and_abandoned(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("IMMOAPP_APPDATA_ROOT", str(tmp_path))

    module.record_onboarding_event("register_dialog_opened", step="register", outcome="viewed")
    module.record_onboarding_event("register_abandoned", step="register", outcome="step_1")
    module.record_onboarding_event("activate_dialog_opened", step="activate", outcome="viewed")
    module.record_onboarding_event("activate_succeeded", step="activate", outcome="completed")

    snapshot = module.get_onboarding_funnel_snapshot(lookback_days=7)

    assert snapshot["register_started"] == 1
    assert snapshot["register_abandoned"] == 1
    assert snapshot["activate_started"] == 1
    assert snapshot["activate_completed"] == 1
