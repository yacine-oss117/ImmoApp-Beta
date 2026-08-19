"""
Tests for match tab dropdown helpers and force-add behavior.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

pytest.importorskip("PySide6")

from app.models import Client  # noqa: E402
from app.views.match import MatchTab  # noqa: E402
from app.views.match_dropdown import build_client_display  # noqa: E402
from app.views.match_state import MatchSelectionState  # noqa: E402
from core.matcher.match_count_state import MatchCountState  # noqa: E402

pytestmark = pytest.mark.ui


@dataclass
class DummySelect:
    """Minimal dropdown stub for testing selection updates."""

    items: list[str] = field(default_factory=list)
    current_index: int | None = None
    current_text: str | None = None

    def setItems(self, items: list[str]) -> None:
        self.items = list(items)

    def setCurrentIndex(self, index: int) -> None:
        self.current_index = index

    def setCurrentText(self, text: str) -> None:
        self.current_text = text


@dataclass
class DummyWorkerController:
    """Capture background count requests."""

    count_requests: list[list[int]] = field(default_factory=list)

    def start_background_count(self, client_ids: list[int]) -> None:
        self.count_requests.append(list(client_ids))


@dataclass
class DummyMatchUi:
    """Minimal MatchUi surface for testing."""

    client_select: DummySelect


@dataclass
class DummyMatchTab:
    """Minimal MatchTab surface for testing _force_add_client_to_dropdown."""

    ui: DummyMatchUi
    _selection: MatchSelectionState
    _match_counts: MatchCountState
    _worker_controller: DummyWorkerController


def test_build_client_display_uses_name_phone_and_count() -> None:
    client = Client(id=1, family_name="Alice", phone="0555")
    assert build_client_display(client, None) == "[?] Alice | 0555"
    assert build_client_display(client, 3) == "[3] Alice | 0555"


def test_build_client_display_falls_back_to_phone_when_name_missing() -> None:
    client = Client(id=2, family_name="", phone="0666")
    assert build_client_display(client, 1) == "[1] 0666"


def test_force_add_client_to_dropdown_adds_missing_client_and_requests_count() -> None:
    selection = MatchSelectionState()
    match_counts = MatchCountState()
    client_select = DummySelect()
    workers = DummyWorkerController()
    tab = DummyMatchTab(
        ui=DummyMatchUi(client_select=client_select),
        _selection=selection,
        _match_counts=match_counts,
        _worker_controller=workers,
    )

    client = Client(id=10, family_name="Yacine", phone="0777")
    MatchTab._force_add_client_to_dropdown(tab, client)

    display = build_client_display(client, None)
    assert display in tab.ui.client_select.items
    assert tab._selection.id_map[display] == client.id
    assert tab._selection.ids_by_index == [client.id]
    assert workers.count_requests == [[client.id]]


def test_force_add_client_to_dropdown_handles_display_collision() -> None:
    selection = MatchSelectionState()
    match_counts = MatchCountState()
    client_select = DummySelect()
    workers = DummyWorkerController()
    tab = DummyMatchTab(
        ui=DummyMatchUi(client_select=client_select),
        _selection=selection,
        _match_counts=match_counts,
        _worker_controller=workers,
    )

    client_one = Client(id=1, family_name="Samir", phone="0999")
    client_two = Client(id=2, family_name="Samir", phone="0999")
    match_counts.set_count(client_one.id, 2)
    match_counts.set_count(client_two.id, 2)

    display_one = build_client_display(client_one, 2)
    selection.id_map[display_one] = client_one.id
    selection.ids_by_index.append(client_one.id)
    client_select.setItems([display_one])

    MatchTab._force_add_client_to_dropdown(tab, client_two)

    collision_display = f"{display_one} (id {client_two.id})"
    assert collision_display in tab.ui.client_select.items
    assert tab._selection.id_map[collision_display] == client_two.id
    assert tab._selection.ids_by_index == [client_one.id, client_two.id]
