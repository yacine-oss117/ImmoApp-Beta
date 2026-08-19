"""
Focused tests for ClientsTabV2 helpers and tree expansion logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QModelIndex
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QApplication, QPushButton, QTreeView

from app.views import clients_v2 as clients_module
from app.views import clients_v2_actions as clients_actions_module
from app.views.clients_v2 import ClientsTabV2
from app.views.clients_v2_actions import ClientsTabActionsMixin
from app.views.tree_expand_controller import TreeExpandController

pytestmark = pytest.mark.ui


@dataclass
class DummyPanel:
    demande_id: int
    deleted: bool = False
    number: int | None = None

    def deleteLater(self) -> None:
        self.deleted = True

    def set_number(self, number: int) -> None:
        self.number = number


class DummyLayout:
    def __init__(self) -> None:
        self.removed: list[DummyPanel] = []

    def removeWidget(self, panel: DummyPanel) -> None:
        self.removed.append(panel)


def test_remove_demande_panel_deletes_and_renumbers(monkeypatch: pytest.MonkeyPatch) -> None:
    deleted: list[int] = []

    def fake_delete_demande(demande_id: int) -> None:
        deleted.append(demande_id)

    monkeypatch.setattr(clients_module, "delete_demande", fake_delete_demande)

    panel_one = DummyPanel(demande_id=5)
    panel_two = DummyPanel(demande_id=0)
    layout = DummyLayout()

    class DummyTab(ClientsTabActionsMixin):
        def __init__(self) -> None:
            self._demande_panels = [panel_one, panel_two]
            self._demandes_layout = layout

    tab = DummyTab()

    ClientsTabV2._remove_demande_panel(tab, panel_one)

    assert deleted == [5]
    assert panel_one.deleted is True
    assert panel_one not in tab._demande_panels
    assert panel_two.number == 1
    assert layout.removed == [panel_one]


def test_tree_expand_controller_expands_loaded_rows(qapp: QApplication) -> None:
    tree = QTreeView()
    model = QStandardItemModel()
    model.appendRow(QStandardItem("Row 1"))
    model.appendRow(QStandardItem("Row 2"))
    tree.setModel(model)

    class Adapter:
        def loaded_root_rows(self) -> list[int]:
            return list(range(model.rowCount()))

        def index(
            self,
            row: int,
            column: int,
            parent: QModelIndex | None = None,
        ) -> QModelIndex:
            parent_index = parent if parent is not None else QModelIndex()
            return model.index(row, column, parent_index)

    button = QPushButton()
    controller = TreeExpandController(
        tree,
        Adapter(),
        expanded_label="+",
        collapsed_label="-",
        parent=tree,
    )
    controller.bind_button(button)
    controller.set_all_expanded(True)
    while controller._expand_queue:
        controller._process_expand_queue()

    assert button.text() == "+"
    assert tree.isExpanded(model.index(0, 0))


def test_selection_change_loads_client_into_editor() -> None:
    loaded: list[object] = []
    client = SimpleNamespace(id=41, family_name="Selected Client")

    class DummyTab(ClientsTabActionsMixin):
        def _get_node_ids(self, index: QModelIndex) -> tuple[int | None, int | None, str | None]:
            assert index.isValid()
            return 41, None, "client"

        def _get_client_for_edit(self, client_id: int) -> object | None:
            return client if client_id == 41 else None

        def _load_client_for_edit(self, value: object) -> None:
            loaded.append(value)

    model = QStandardItemModel()
    model.appendRow(QStandardItem("Row 1"))
    current = model.index(0, 0)

    ClientsTabV2._on_selection_changed(DummyTab(), current, QModelIndex())

    assert loaded == [client]


def test_save_client_auth_failure_uses_named_session_dialog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dialogs: list[dict[str, str]] = []

    class FakeMessageBox:
        class Icon:
            Warning = "warning"

        class StandardButton:
            Ok = "ok"

        def __init__(
            self,
            _icon: object,
            title: str,
            text: str,
            _buttons: object,
            _parent: object,
        ) -> None:
            self.title = title
            self.text = text
            self.object_name = ""
            self.accessible_name = ""

        def setObjectName(self, value: str) -> None:
            self.object_name = value

        def setAccessibleName(self, value: str) -> None:
            self.accessible_name = value

        def exec(self) -> int:
            dialogs.append(
                {
                    "title": self.title,
                    "text": self.text,
                    "object_name": self.object_name,
                    "accessible_name": self.accessible_name,
                }
            )
            return 0

    class TextControl:
        def __init__(self, value: str) -> None:
            self._value = value

        def text(self) -> str:
            return self._value

    class CheckControl:
        def isChecked(self) -> bool:
            return False

    class DummyTab(ClientsTabActionsMixin):
        editing_id = None
        editing_row_version = None
        editing_created_at = ""
        editing_created_loc = ""
        _demande_panels: list[object] = []
        refresh_match_counts_cb = None

        def __init__(self) -> None:
            self._form = SimpleNamespace(
                family_name=TextControl("Inactive User"),
                phone=TextControl("0555123456"),
                is_vip=CheckControl(),
            )

        def _get_cached_location(self) -> str:
            return "local"

    def fake_upsert_client(_payload: object) -> int:
        raise PermissionError("auth required")

    monkeypatch.setattr(clients_actions_module, "QMessageBox", FakeMessageBox)
    monkeypatch.setattr(clients_actions_module, "upsert_client", fake_upsert_client)

    ClientsTabActionsMixin.save_client(DummyTab())

    assert dialogs == [
        {
            "title": "Session needs attention",
            "text": (
                "Your session or permissions changed while this page was open. "
                "Sign in again and try again."
            ),
            "object_name": "clientsAuthRequiredMessageBox",
            "accessible_name": "Session needs attention",
        }
    ]
