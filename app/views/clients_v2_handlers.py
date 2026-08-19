"""
Event handling and UI lifecycle helpers for ClientsTabV2.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, cast

from PySide6.QtCore import QModelIndex, QObject, QTimer, Qt
from PySide6.QtWidgets import QComboBox, QLineEdit, QPushButton, QTreeView, QWidget

from app.utils.i18n import tr_factory
from app.views.base_tab_handlers import BaseTabHandlersMixin
from app.views.client_sql_model import ClientSQLModel
from app.views.table_popups import show_phone_menu
from app.views.tree_expand_controller import TreeExpandController
from app.widgets.demande_panel import DemandePanel

logger = logging.getLogger(__name__)
_TR = tr_factory("ClientsTabV2")

if TYPE_CHECKING:
    from app.models import Client


class ClientsTabHandlersMixin(BaseTabHandlersMixin):
    """Mixin for event handlers and UI lifecycle helpers."""

    _column_settings_prefix = "clients_tab"
    _first_paint_log_label = "Clients tab"
    _model: ClientSQLModel
    _expand_controller: TreeExpandController
    _demande_panels: list[DemandePanel]
    _demandes_container: QWidget
    _add_demande_btn: QPushButton
    search_bar: QLineEdit
    filter_handicap: QComboBox | None
    tree: QTreeView
    refresh_clients_cb: Callable[[], None] | None
    _first_paint_logged: bool
    _swap_started_at: float | None

    def _load_client_for_edit(self, client: Client) -> None: ...
    def _get_client_for_edit(self, client_id: int) -> Client | None: ...
    def _edit_demande(self, demande_id: int, client_id: int) -> None: ...
    def _delete_demande_row(self, demande_id: int, client_id: int) -> None: ...
    def _delete_client(self, client_id: int) -> None: ...

    def _cleanup(self) -> None:
        """Disconnect heavy signals and clear nested panels on destroy."""
        try:
            self.tree.viewport().removeEventFilter(cast(QObject, self))
        except RuntimeError:
            logger.debug("Failed to remove ClientsTabV2 event filter", exc_info=True)
        try:
            self._expand_controller.cancel_pending()
        except RuntimeError:
            logger.debug("Failed to cancel ClientsTabV2 expand controller", exc_info=True)
        for panel in self._demande_panels[:]:
            panel.deleteLater()
        self._demande_panels.clear()

    def _on_client_section_toggled(self, collapsed: bool) -> None:
        """Show/hide demandes container when client section expands/collapses."""
        visible = not collapsed
        self._demandes_container.setVisible(visible)
        self._add_demande_btn.setVisible(visible)

    def refresh_table(self, force_reload: bool = True) -> None:
        """Refresh the tree with current data."""
        self._expand_controller.cancel_pending()
        search = self.search_bar.text().strip()
        handicap = self.filter_handicap.currentIndex() if self.filter_handicap else 0
        self._apply_filters(search, handicap)

    def _get_first_paint_callback(self) -> Callable[[], None] | None:
        return self.refresh_clients_cb

    def _on_double_click(self, index: QModelIndex) -> None:
        """Handle double-click on a row."""
        client_id, demande_id, node_type = self._get_node_ids(index)
        if node_type == "client" and client_id is not None:
            client = self._get_client_for_edit(client_id)
            if client:
                self._load_client_for_edit(client)
                page_scroll = getattr(self, "_page_scroll", None)
                if page_scroll is not None:
                    page_scroll.scroll_to_editor()

    def _on_selection_changed(self, current: QModelIndex, _previous: QModelIndex) -> None:
        """Populate the editor when a client row becomes the active selection."""
        if not current.isValid():
            return
        client_id, _demande_id, node_type = self._get_node_ids(current)
        if node_type != "client" or client_id is None:
            return
        client = self._get_client_for_edit(client_id)
        if client:
            page_scroll = getattr(self, "_page_scroll", None)
            keep_table_focused = bool(
                page_scroll is not None and page_scroll.records_are_focused()
            )
            self._load_client_for_edit(client)
            if keep_table_focused and page_scroll is not None:
                QTimer.singleShot(0, page_scroll.scroll_to_records)

    def _on_tree_clicked(self, index: QModelIndex) -> None:
        """Handle single click on tree - show phone popup for phone column."""
        if index.column() != 1:
            return

        phone = index.data(int(Qt.ItemDataRole.DisplayRole))
        if not phone:
            return

        show_phone_menu(cast(QWidget, self), str(phone))

    def _on_edit_action(self, index: QModelIndex) -> None:
        """Handle edit action from delegate."""
        client_id, demande_id, node_type = self._get_node_ids(index)
        if node_type == "client" and client_id is not None:
            client = self._get_client_for_edit(client_id)
            if client:
                self._load_client_for_edit(client)
                page_scroll = getattr(self, "_page_scroll", None)
                if page_scroll is not None:
                    page_scroll.scroll_to_editor()
            return
        if node_type == "demande" and client_id is not None and demande_id is not None:
            self._edit_demande(demande_id, client_id)

    def _on_delete_action(self, index: QModelIndex) -> None:
        """Handle delete action from delegate."""
        client_id, demande_id, node_type = self._get_node_ids(index)
        if node_type == "client" and client_id is not None:
            self._delete_client(client_id)
            return
        if node_type == "demande" and client_id is not None and demande_id is not None:
            self._delete_demande_row(demande_id, client_id)

    def _get_node_ids(self, index: QModelIndex) -> tuple[int | None, int | None, str | None]:
        if not index.isValid():
            return None, None, None
        node_type_obj = self._model.data(index, ClientSQLModel.ROLE_NODE_TYPE)
        node_type = node_type_obj if isinstance(node_type_obj, str) else None
        client_id_obj = self._model.data(index, ClientSQLModel.ROLE_CLIENT_ID)
        client_id = client_id_obj if isinstance(client_id_obj, int) else None
        demande_id_obj = self._model.data(index, ClientSQLModel.ROLE_DEMANDE_ID)
        demande_id = demande_id_obj if isinstance(demande_id_obj, int) else None
        return client_id, demande_id, node_type
