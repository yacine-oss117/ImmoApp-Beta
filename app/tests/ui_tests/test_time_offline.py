"""Tests for offline time handling."""

import pytest
from PySide6.QtCore import QSettings

from app.utils import time_service

pytestmark = pytest.mark.ui


def test_offline_mode_skips_network(monkeypatch):
    s = QSettings(time_service.ORG, time_service.APP)
    s.clear()
    s.setValue("time/offline_mode", True)
    s.setValue("time/use_ntp", True)
    s.setValue("time/auto_detect_tz", True)

    called = {"ntp": False, "tz": False}

    def fake_ntp(*a, **k):
        called["ntp"] = True
        return None

    def fake_tz(*a, **k):
        called["tz"] = True
        return None

    monkeypatch.setattr(time_service, "_get_ntp_epoch", fake_ntp)
    monkeypatch.setattr(time_service, "_get_system_tz", fake_tz)

    dt, note = time_service.authoritative_now()
    status = time_service.maybe_resync_if_due()

    assert "tz=" in note and "time=" in note
    assert status == "offline"
    assert called["ntp"] is False
    assert called["tz"] is False
