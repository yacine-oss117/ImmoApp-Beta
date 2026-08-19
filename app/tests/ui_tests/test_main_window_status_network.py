from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QMainWindow

from app.main_window_status import MainWindowStatusMixin

pytestmark = pytest.mark.ui


class _Host(QMainWindow, MainWindowStatusMixin):
    status_message = Signal(str, int)
    tz_refresh_result = Signal(object, float)

    def __init__(self) -> None:
        super().__init__()
        self._sync_in_flight = False
        self._resync_in_flight = False
        self._tz_refresh_in_flight = False
        self._tz_refresh_last_attempt = 0.0

    def _kickoff_resync_async(self) -> None:
        return None

    def _kickoff_tz_refresh_async(self, force: bool = False) -> None:
        return None

    def _kickoff_network_sync_async(self) -> None:
        return None

    def _current_location_label(self) -> str:
        return "Algiers | DZ"


def test_status_bar_shows_network_state(monkeypatch: pytest.MonkeyPatch, qapp) -> None:
    import app.main_window_status as module

    monkeypatch.setattr(module.QTimer, "start", lambda self, interval: None)
    monkeypatch.setattr(
        module,
        "authoritative_now",
        lambda allow_network=False: (__import__("datetime").datetime.now(), "ok"),
    )
    monkeypatch.setattr(module, "db_health_status", lambda: "DB: ok")
    monkeypatch.setattr(
        module,
        "get_network_status_snapshot",
        lambda sync_in_flight=False: {
            "state": "pending",
            "pending_api": 2,
            "pending_media": 1,
            "failed_api": 0,
            "pending_total": 3,
            "circuit": {},
        },
    )

    host = _Host()
    host._init_status_bar()

    assert host.net_label.text() == "Net: Pending 3"
    assert host.net_label.property("statusState") == "orange"


def test_status_bar_shows_store_unavailable_tooltip(monkeypatch: pytest.MonkeyPatch, qapp) -> None:
    import app.main_window_status as module

    monkeypatch.setattr(module.QTimer, "start", lambda self, interval: None)
    monkeypatch.setattr(
        module,
        "authoritative_now",
        lambda allow_network=False: (__import__("datetime").datetime.now(), "ok"),
    )
    monkeypatch.setattr(module, "db_health_status", lambda: "DB: ok")
    monkeypatch.setattr(
        module,
        "get_network_status_snapshot",
        lambda sync_in_flight=False: {
            "state": "error",
            "pending_api": 0,
            "pending_media": 0,
            "failed_api": 0,
            "pending_total": 0,
            "pending_creates": 0,
            "needs_review": 0,
            "blocked_ops": 0,
            "store_error": True,
            "circuit": {},
        },
    )

    host = _Host()
    host._init_status_bar()

    assert host.net_label.text() == "Net: Sync issues"
    assert "temporarily unavailable" in host.net_label.toolTip()
