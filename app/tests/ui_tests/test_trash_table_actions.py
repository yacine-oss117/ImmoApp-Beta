"""
Behavior tests for TrashTable restore/purge actions.
"""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from app.views.dialogs.trash_table import TrashTable

pytestmark = pytest.mark.ui


def test_trash_table_restore_calls_handler(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    restored: list[int] = []

    def fetch_items(limit: int, offset: int) -> list[object]:
        _ = (limit, offset)
        return []

    def render_row(_item: object) -> list[str]:
        return ["1"]

    def restore_item(item_id: int) -> None:
        restored.append(item_id)

    def purge_item(_item_id: int) -> None:
        return None

    def always_yes(*_args: object, **_kwargs: object) -> QMessageBox.StandardButton:
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", always_yes)

    table = TrashTable(
        headers=["ID"],
        fetch_items=fetch_items,
        render_row=render_row,
        restore_item=restore_item,
        purge_item=purge_item,
    )

    table._restore(123)

    assert restored == [123]

    table.deleteLater()
    qapp.processEvents()


def test_trash_table_purge_calls_handler(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    purged: list[int] = []

    def fetch_items(limit: int, offset: int) -> list[object]:
        _ = (limit, offset)
        return []

    def render_row(_item: object) -> list[str]:
        return ["1"]

    def restore_item(_item_id: int) -> None:
        return None

    def purge_item(item_id: int) -> None:
        purged.append(item_id)

    def always_yes(*_args: object, **_kwargs: object) -> QMessageBox.StandardButton:
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "warning", always_yes)

    table = TrashTable(
        headers=["ID"],
        fetch_items=fetch_items,
        render_row=render_row,
        restore_item=restore_item,
        purge_item=purge_item,
    )

    table._purge(456)

    assert purged == [456]

    table.deleteLater()
    qapp.processEvents()
