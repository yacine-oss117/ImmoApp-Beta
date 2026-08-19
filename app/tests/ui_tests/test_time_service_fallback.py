"""Fallback tests for time_service when network is disabled."""

from __future__ import annotations

from datetime import datetime

import pytest
from PySide6.QtCore import QSettings

from app.utils import time_service, time_service_helpers

pytestmark = pytest.mark.ui


def test_authoritative_now_no_network(monkeypatch) -> None:
    s = QSettings(time_service.ORG, time_service.APP)
    s.clear()
    s.setValue("time/offline_mode", False)
    s.setValue("time/use_ntp", True)
    s.setValue("time/auto_detect_tz", True)
    s.setValue("cache/ntp_seed_epoch", 0)
    s.setValue("cache/ntp_seed_mono", 0.0)
    s.setValue("cache/tz_name", "")

    called = {"ntp": False, "tz": False}

    def fake_ntp(timeout: float = 1.5) -> float | None:
        called["ntp"] = True
        return None

    def fake_tz() -> str | None:
        called["tz"] = True
        return None

    monkeypatch.setattr(time_service, "_get_ntp_epoch", fake_ntp)
    monkeypatch.setattr(time_service, "_get_system_tz", fake_tz)

    dt, note = time_service.authoritative_now(allow_network=False)

    assert isinstance(dt, datetime)
    assert "tz=" in note and "time=" in note
    assert called["ntp"] is False
    assert called["tz"] is False


def test_resync_skips_when_network_disabled() -> None:
    s = QSettings(time_service.ORG, time_service.APP)
    s.clear()
    s.setValue("time/offline_mode", False)
    s.setValue("time/use_ntp", True)
    s.setValue("time/ntp_resync_enabled", True)

    status = time_service.maybe_resync_if_due(allow_network=False)

    assert status == "skipped_network"


def test_ntp_failure_logs_info_not_warning(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    class _Client:
        def request(self, *_args, **_kwargs) -> float | None:
            raise time_service_helpers.ntplib.NTPException("no response")

    monkeypatch.setattr(time_service_helpers.ntplib, "NTPClient", lambda: _Client())

    with caplog.at_level("INFO"):
        result = time_service_helpers._get_ntp_epoch(timeout=0.01)

    assert result is None
    assert any(
        record.levelname == "INFO" and "NTP request unavailable" in record.message
        for record in caplog.records
    )
    assert not any(record.levelname == "WARNING" for record in caplog.records)
