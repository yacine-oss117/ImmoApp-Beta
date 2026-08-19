"""
Event handlers and UI helpers for ListingsTabV2.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, cast

from PySide6.QtCore import QEvent, QModelIndex, QObject, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QComboBox,
    QLabel,
    QLineEdit,
    QPushButton,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from app.models import Offer
from app.utils.i18n import tr_factory
from app.views.base_tab_handlers import BaseTabHandlersMixin
from app.views.listing_sql_model import ListingSQLModel
from app.views.listings_v2_map_preview import open_details_map, set_map_preview
from app.views.listings_v2_offer_panels import (
    add_offer_panel,
    on_offer_expanded,
    remove_offer_panel,
)
from app.views.table_popups import show_location_menu, show_phone_menu
from app.views.tree_expand_controller import TreeExpandController
from app.widgets.offer_panel import OfferPanel

if TYPE_CHECKING:
    from app.widgets.collapsible_section import CollapsibleSection

logger = logging.getLogger(__name__)
_TR = tr_factory("ListingsTabV2")


class ListingsTabHandlersMixin(BaseTabHandlersMixin):
    """Behavior mixin for event handlers and UI helpers."""

    _column_settings_prefix = "listings_tab"
    _first_paint_log_label = "Listings tab"
    _model: ListingSQLModel
    _expand_controller: TreeExpandController
    _offer_panels: list[OfferPanel]
    _offers_container: QWidget
    _offers_layout: QVBoxLayout
    _listing_section: CollapsibleSection
    search_bar: QLineEdit
    filter_handicap: QComboBox | None
    tree: QTreeView
    _details_label: QLabel
    _coords_label: QLabel
    _open_map_btn: QPushButton
    _map_url: str | None
    refresh_match_counts_cb: Callable[[], None] | None
    _first_paint_logged: bool
    _swap_started_at: float | None

    if TYPE_CHECKING:

        def _edit_listing(self, listing_id: int) -> None: ...
        def _edit_offer_dialog(self, listing_id: int, offer_id: int) -> None: ...
        def _delete_listing(self, listing_id: int) -> None: ...
        def _delete_offer(self, listing_id: int, offer_id: int) -> None: ...

    def _cleanup(self) -> None:
        """Disconnect heavy signals and clear nested panels on destroy."""
        try:
            self.tree.viewport().removeEventFilter(cast(QObject, self))
        except RuntimeError:
            logger.debug("Failed to remove ListingsTabV2 event filter", exc_info=True)
        try:
            self.search_bar.removeEventFilter(cast(QObject, self))
        except RuntimeError:
            logger.debug("Failed to remove ListingsTabV2 search filter", exc_info=True)
        try:
            self._expand_controller.cancel_pending()
        except RuntimeError:
            logger.debug("Failed to cancel ListingsTabV2 expand controller", exc_info=True)
        for panel in self._offer_panels[:]:
            panel.deleteLater()
        self._offer_panels.clear()

    def _on_listing_section_toggled(self, collapsed: bool) -> None:
        """Show/hide offers container when listing section expands/collapses."""
        self._offers_container.setVisible(not collapsed)

    def _add_offer_panel(self, data: Offer | Mapping[str, object] | None = None) -> OfferPanel:
        """Add a new offer panel."""
        return add_offer_panel(self, data)

    def _on_offer_expanded(self, expanded_panel: OfferPanel) -> None:
        """Accordion behavior: collapse other panels when one expands."""
        on_offer_expanded(self, expanded_panel)

    def _remove_offer_panel(self, panel: OfferPanel, *, delete_persisted: bool = True) -> None:
        """Remove an offer panel."""
        remove_offer_panel(self, panel, delete_persisted=delete_persisted)

    def _on_double_click(self, index: QModelIndex) -> None:
        """Handle double-click for editing."""
        listing_id, offer_id, node_type = self._get_node_ids(index)
        if node_type == "listing" and listing_id is not None:
            self._edit_listing(listing_id)
            return
        if node_type == "offer" and listing_id is not None and offer_id is not None:
            self._edit_offer_dialog(listing_id, offer_id)

    def _on_tree_clicked(self, index: QModelIndex) -> None:
        """Handle single click on tree - show popup for phone (col 1) or location (col 4)."""
        col = index.column()

        if col == 1:
            self._show_listing_phone(index)
            return

        if col == 4:
            self._show_location_popup(index)

    def _on_selection_changed(self, current: QModelIndex, _previous: QModelIndex) -> None:
        """Load selected listings for editing and preview selected offers."""
        if not current.isValid():
            self._set_map_preview(None)
            return

        listing_id, _offer_id, node_type = self._get_node_ids(current)
        if node_type == "listing" and listing_id is not None:
            self._set_map_preview(None)
            self._edit_listing(listing_id)
            return

        obj = current.internalPointer()
        if isinstance(obj, Offer):
            self._set_map_preview(obj)
        else:
            self._set_map_preview(None)

    def _set_map_preview(self, offer: Offer | None) -> None:
        set_map_preview(self, offer)

    def _open_details_map(self) -> None:
        open_details_map(self)

    def _on_edit_action(self, index: QModelIndex) -> None:
        """Handle edit action button click."""
        listing_id, offer_id, node_type = self._get_node_ids(index)
        if node_type == "listing" and listing_id is not None:
            self._edit_listing(listing_id)
            return
        if node_type == "offer" and listing_id is not None and offer_id is not None:
            self._edit_offer_dialog(listing_id, offer_id)

    def _on_delete_action(self, index: QModelIndex) -> None:
        """Handle delete action button click."""
        listing_id, offer_id, node_type = self._get_node_ids(index)
        if node_type == "listing" and listing_id is not None:
            self._delete_listing(listing_id)
            return
        if node_type == "offer" and listing_id is not None and offer_id is not None:
            self._delete_offer(listing_id, offer_id)

    def refresh_table(self, force_reload: bool = True) -> None:
        """Refresh the table."""
        self._expand_controller.cancel_pending()
        search = self.search_bar.text().strip()
        handicap = self.filter_handicap.currentIndex() if self.filter_handicap else 0

        self._apply_filters(search, handicap)

        if self._expand_controller.all_expanded:
            self._expand_controller.set_loaded_expanded(True)

        if self.refresh_match_counts_cb:
            self.refresh_match_counts_cb()

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        """Event filter for search bar."""
        if obj == self.search_bar and event.type() == QEvent.Type.KeyPress:
            key_event = event
            if isinstance(key_event, QKeyEvent) and key_event.key() == Qt.Key.Key_Escape:
                self.search_bar.clear()
                return True
        return bool(BaseTabHandlersMixin.eventFilter(self, obj, event))

    def _get_first_paint_callback(self) -> Callable[[], None] | None:
        return self.refresh_match_counts_cb

    def _get_node_ids(self, index: QModelIndex) -> tuple[int | None, int | None, str | None]:
        if not index.isValid():
            return None, None, None
        node_type_obj = self._model.data(index, ListingSQLModel.ROLE_NODE_TYPE)
        node_type = node_type_obj if isinstance(node_type_obj, str) else None
        listing_id_obj = self._model.data(index, ListingSQLModel.ROLE_LISTING_ID)
        listing_id = listing_id_obj if isinstance(listing_id_obj, int) else None
        offer_id_obj = self._model.data(index, ListingSQLModel.ROLE_OFFER_ID)
        offer_id = offer_id_obj if isinstance(offer_id_obj, int) else None
        return listing_id, offer_id, node_type

    def _show_listing_phone(self, index: QModelIndex) -> None:
        node_type = self._model.data(index, ListingSQLModel.ROLE_NODE_TYPE)
        if node_type != "listing":
            return
        phone_obj = index.data(int(Qt.ItemDataRole.DisplayRole))
        if not phone_obj:
            return
        show_phone_menu(cast(QWidget, self), str(phone_obj))

    def _show_location_popup(self, index: QModelIndex) -> None:
        location_obj = index.data(int(Qt.ItemDataRole.DisplayRole))
        if not location_obj:
            return
        show_location_menu(cast(QWidget, self), str(location_obj))
