"""
Fail-soft regression tests for startup warmup and match dropdown loading.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

pytest.importorskip("PySide6")

from app.views.match_dropdown_controller import MatchDropdownController  # noqa: E402
from app.widgets.splash_shared import warm_tab_data  # noqa: E402

pytestmark = pytest.mark.ui


class _FailingCrmTab:
    def refresh(self) -> None:
        raise RuntimeError("CRM unavailable")


@dataclass
class _WarmTabHost:
    crm_tab: _FailingCrmTab | None = None
    clients_tab: object | None = None
    listings_tab: object | None = None
    match_tab: object | None = None


@dataclass
class _DummySelect:
    items: list[str] = field(default_factory=list)
    index: int = 0
    text: str = ""

    def currentIndex(self) -> int:
        return self.index

    def currentText(self) -> str:
        return self.text

    def setItems(self, items: list[str]) -> None:
        self.items = list(items)

    def setEditText(self, text: str) -> None:
        self.text = text


@dataclass
class _DummySpin:
    value_int: int = 0

    def value(self) -> int:
        return self.value_int


@dataclass
class _DummyUi:
    client_select: _DummySelect
    min_matches: _DummySpin


@dataclass
class _DummyWorkerController:
    errors: list[str] = field(default_factory=list)

    def show_error(self, message: str) -> None:
        self.errors.append(message)

    def start_background_count(self, _client_ids: list[int]) -> None:
        return None


def test_warm_tab_data_does_not_raise_when_crm_refresh_fails() -> None:
    host = _WarmTabHost(crm_tab=_FailingCrmTab())
    warm_tab_data(host, "CRM")


def test_match_dropdown_returns_empty_when_fetch_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.views import match_dropdown_controller as module

    def _raise_fetch(*_args: object, **_kwargs: object) -> list[object]:
        raise RuntimeError("API unavailable")

    monkeypatch.setattr(module, "fetch_clients", _raise_fetch)

    ui = _DummyUi(client_select=_DummySelect(), min_matches=_DummySpin())
    workers = _DummyWorkerController()

    controller = MatchDropdownController(
        ui=ui,
        worker_controller=workers,
        parent=None,
        max_dropdown_clients=100,
        profile_threshold_ms=0.0,
    )

    clients = controller.refresh_dropdown()

    assert clients == []
    assert workers.errors
    assert ui.client_select.items == []
