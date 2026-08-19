"""
Regression tests for MainWindow tab controller host parenting.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QMainWindow, QTabWidget, QWidget  # noqa: E402

from app import main_window_tabs as tabs_module  # noqa: E402
from app.main_window_controllers import MainWindowTabController  # noqa: E402

pytestmark = pytest.mark.ui


class _Host(QMainWindow):
    def _navigate_to_match(self, _client_id: int) -> None:
        return None


def test_tab_controller_uses_host_widget_parent(monkeypatch: pytest.MonkeyPatch, qapp) -> None:
    def _fake_dashboard(
        on_lead_click_cb,
        on_open_clients_cb=None,
        on_open_properties_cb=None,
        on_open_matches_cb=None,
    ):
        return QWidget()

    monkeypatch.setattr(tabs_module, "DashboardTab", _fake_dashboard)
    monkeypatch.setattr(MainWindowTabController, "_create_match_tab", lambda self: QWidget())
    monkeypatch.setattr(MainWindowTabController, "_create_clients_tab", lambda self: QWidget())
    monkeypatch.setattr(MainWindowTabController, "_create_listings_tab", lambda self: QWidget())
    monkeypatch.setattr(MainWindowTabController, "_create_crm_tab", lambda self: QWidget())

    host = _Host()
    controller = MainWindowTabController(host)
    controller._init_tabs()

    central = host.centralWidget()
    assert isinstance(central, QTabWidget)
    assert central.parent() is host
