from __future__ import annotations

from app.services import offline_state


def test_offline_state_roundtrip(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("IMMOAPP_APPDATA_ROOT", str(tmp_path))
    monkeypatch.delenv("IMMOAPP_OFFLINE", raising=False)

    offline_state.set_offline_mode(True)
    assert offline_state.get_offline_mode() is True

    offline_state.set_offline_mode(False)
    assert offline_state.get_offline_mode() is False


def test_offline_state_env_override(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("IMMOAPP_APPDATA_ROOT", str(tmp_path))
    monkeypatch.setenv("IMMOAPP_OFFLINE", "1")
    assert offline_state.get_offline_mode() is True

    monkeypatch.setenv("IMMOAPP_OFFLINE", "0")
    assert offline_state.get_offline_mode() is False
