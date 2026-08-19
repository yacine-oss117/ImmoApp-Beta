from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from app.services import onboarding_drafts as module

pytestmark = pytest.mark.ui


def test_onboarding_draft_roundtrip_and_clear(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(module, "config_dir", lambda: tmp_path)

    module.save_onboarding_draft(module.REGISTER_DRAFT_KEY, {"agency_name": "Demo", "step": 1})
    loaded = module.load_onboarding_draft(module.REGISTER_DRAFT_KEY)
    assert loaded.get("agency_name") == "Demo"
    assert loaded.get("step") == 1
    assert module.has_onboarding_draft(module.REGISTER_DRAFT_KEY) is True

    module.clear_onboarding_draft(module.REGISTER_DRAFT_KEY)
    assert module.load_onboarding_draft(module.REGISTER_DRAFT_KEY) == {}
    assert module.has_onboarding_draft(module.REGISTER_DRAFT_KEY) is False


def test_resolve_resume_target_uses_priority(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(module, "config_dir", lambda: tmp_path)
    module.save_onboarding_draft(module.REGISTER_DRAFT_KEY, {"step": 0})
    module.save_onboarding_draft(module.JOIN_TEAM_DRAFT_KEY, {"step": 0})
    assert module.resolve_resume_target() == module.JOIN_TEAM_DRAFT_KEY

    module.save_onboarding_draft(module.ACTIVATE_DRAFT_KEY, {"step": 0})
    assert module.resolve_resume_target() == module.ACTIVATE_DRAFT_KEY


def test_expired_draft_is_purged(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(module, "config_dir", lambda: tmp_path)
    monkeypatch.setattr(module, "_TTL_DAYS", 1)
    module.save_onboarding_draft(module.REGISTER_DRAFT_KEY, {"agency_name": "Old", "step": 1})

    path = tmp_path / "onboarding_drafts_v1.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw[module.REGISTER_DRAFT_KEY]["updated_at"] = (
        datetime.now(timezone.utc) - timedelta(days=3)
    ).isoformat()
    path.write_text(json.dumps(raw, ensure_ascii=True, indent=2), encoding="utf-8")

    assert module.load_onboarding_draft(module.REGISTER_DRAFT_KEY) == {}
    assert module.resolve_resume_target() is None
