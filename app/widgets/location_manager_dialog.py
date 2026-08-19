"""
Dialog to manage communes for a selected wilaya.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.services.locations import filter_locations_by_wilaya, get_wilaya_labels
from app.services.locations_repository import (
    add_location,
    delete_location,
    get_all_locations,
    update_location,
)
from app.utils.i18n import tr_factory
from app.widgets.location_events import LOCATION_EVENTS

logger = logging.getLogger(__name__)
_TR = tr_factory("ManageLocationsDialog")


class ManageLocationsDialog(QDialog):
    """Dialog to manage communes for a selected wilaya."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._changed = False
        self.setWindowTitle(_TR("Manage Locations"))
        self.setMinimumWidth(720)

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        main_row = QHBoxLayout()
        main_row.setSpacing(10)

        left_col = QVBoxLayout()
        left_label = QLabel(_TR("Wilayas"), self)
        self._wilaya_list = QListWidget(self)
        self._wilayas = get_wilaya_labels()
        self._wilaya_list.addItems(self._wilayas)
        self._wilaya_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._wilaya_list.setMinimumWidth(220)
        self._wilaya_list.itemSelectionChanged.connect(self._refresh_list)
        self._wilaya_list.setAccessibleName(_TR("Wilayas list"))
        self._wilaya_list.setAccessibleDescription(
            _TR("List of wilayas. Select one to filter communes.")
        )
        left_col.addWidget(left_label)
        left_col.addWidget(self._wilaya_list, 1)

        right_col = QVBoxLayout()
        right_col.setSpacing(6)

        communes_label = QLabel(_TR("Communes"), self)
        self._commune_search = QLineEdit(self)
        self._commune_search.setPlaceholderText(_TR("Search communes..."))
        self._commune_search.textChanged.connect(self._refresh_list)
        self._commune_search.setAccessibleName(_TR("Commune search"))
        self._commune_search.setAccessibleDescription(
            _TR("Search communes in the selected wilaya.")
        )

        self._list = QListWidget(self)
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._list.setMaximumHeight(220)
        self._list.itemSelectionChanged.connect(self._on_selection_changed)
        self._list.setAccessibleName(_TR("Commune list"))
        self._list.setAccessibleDescription(_TR("List of communes for the selected wilaya."))

        form_row = QHBoxLayout()
        self._commune = QLineEdit(self)
        self._commune.setPlaceholderText(_TR("Commune name"))
        self._commune.setAccessibleName(_TR("Commune name"))
        self._commune.setAccessibleDescription(_TR("Commune name input."))
        add_btn = QPushButton(_TR("Add"))
        add_btn.clicked.connect(self._add_location)
        add_btn.setAccessibleName(_TR("Add commune"))
        edit_btn = QPushButton(_TR("Edit"))
        edit_btn.clicked.connect(self._edit_location)
        edit_btn.setAccessibleName(_TR("Edit commune"))

        form_row.addWidget(self._commune, 2)
        form_row.addWidget(add_btn)
        form_row.addWidget(edit_btn)

        actions = QHBoxLayout()
        remove_btn = QPushButton(_TR("Remove Selected"))
        remove_btn.clicked.connect(self._remove_selected)
        remove_btn.setAccessibleName(_TR("Remove selected communes"))
        close_btn = QPushButton(_TR("Close"))
        close_btn.clicked.connect(self.accept)
        close_btn.setAccessibleName(_TR("Close"))
        actions.addWidget(remove_btn)
        actions.addStretch()
        actions.addWidget(close_btn)

        right_col.addWidget(communes_label)
        right_col.addWidget(self._commune_search)
        right_col.addWidget(self._list, 1)
        right_col.addLayout(form_row)
        right_col.addLayout(actions)

        main_row.addLayout(left_col, 1)
        main_row.addLayout(right_col, 2)

        layout.addLayout(main_row)

        if self._wilayas:
            self._wilaya_list.setCurrentRow(0)
        self._refresh_list()
        self.setTabOrder(self._wilaya_list, self._commune_search)
        self.setTabOrder(self._commune_search, self._list)
        self.setTabOrder(self._list, self._commune)
        self.setTabOrder(self._commune, add_btn)
        self.setTabOrder(add_btn, edit_btn)
        self.setTabOrder(edit_btn, remove_btn)
        self.setTabOrder(remove_btn, close_btn)

    @property
    def changed(self) -> bool:
        """Return True if any locations were modified during this dialog session."""
        return self._changed

    def _refresh_list(self) -> None:
        try:
            items = get_all_locations()
        except Exception:
            logger.error("Failed to load locations", exc_info=True)
            QMessageBox.warning(self, _TR("Error"), _TR("Failed to load locations."))
            items = []
        items = filter_locations_by_wilaya(items, self._selected_wilaya())
        search = (self._commune_search.text() or "").strip().lower()
        if search:
            items = [loc for loc in items if search in loc.lower()]
        self._list.clear()
        for loc in items:
            display = self._commune_only(loc)
            item = QListWidgetItem(display)
            item.setData(int(Qt.ItemDataRole.UserRole), loc)
            self._list.addItem(item)

    def _on_selection_changed(self) -> None:
        selected = self._list.selectedItems()
        if not selected:
            return
        full_name = selected[0].data(int(Qt.ItemDataRole.UserRole)) or selected[0].text()
        self._commune.setText(self._commune_only(full_name))

    def _add_location(self) -> None:
        commune = (self._commune.text() or "").strip()
        wilaya = self._selected_wilaya()
        full_name = commune
        if commune and wilaya and "," not in commune:
            full_name = f"{commune}, {wilaya}"
        try:
            added = add_location(full_name)
        except ValueError as exc:
            QMessageBox.warning(self, _TR("Error"), str(exc))
            return
        except Exception:
            logger.error("Failed to add location %s", full_name, exc_info=True)
            QMessageBox.critical(self, _TR("Error"), _TR("Failed to add location."))
            return
        if added:
            self._mark_changed()
            self._commune.clear()
            self._refresh_list()
        else:
            QMessageBox.information(self, _TR("Info"), _TR("This commune already exists."))

    def _edit_location(self) -> None:
        selected = self._list.selectedItems()
        if not selected:
            QMessageBox.warning(self, _TR("Validation"), _TR("Select a commune to edit."))
            return
        old_full = selected[0].data(int(Qt.ItemDataRole.UserRole)) or selected[0].text()
        commune = (self._commune.text() or "").strip()
        wilaya = self._selected_wilaya()
        new_full = commune
        if commune and wilaya and "," not in commune:
            new_full = f"{commune}, {wilaya}"
        try:
            if update_location(old_full, new_full):
                self._mark_changed()
                self._commune.clear()
                self._refresh_list()
            else:
                QMessageBox.warning(self, _TR("Error"), _TR("Could not update this commune."))
        except ValueError as exc:
            QMessageBox.warning(self, _TR("Error"), str(exc))

    def _remove_selected(self) -> None:
        selected = [
            i.data(int(Qt.ItemDataRole.UserRole)) or i.text() for i in self._list.selectedItems()
        ]
        if not selected:
            return
        reply = QMessageBox.question(
            self,
            _TR("Confirm"),
            _TR(
                "Remove selected communes from the internal list?\n"
                "Existing demandes/offers will not be changed."
            ),
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        changed = False
        for loc in selected:
            try:
                if delete_location(loc):
                    changed = True
            except ValueError as exc:
                QMessageBox.warning(self, _TR("Error"), str(exc))
        if changed:
            self._mark_changed()
            self._refresh_list()

    def _mark_changed(self) -> None:
        self._changed = True
        LOCATION_EVENTS.locationsChanged.emit()

    @staticmethod
    def _commune_only(location: str) -> str:
        if ", " in location:
            return location.split(", ", 1)[0]
        return location

    def _selected_wilaya(self) -> str:
        item = self._wilaya_list.currentItem()
        return item.text() if item else ""
