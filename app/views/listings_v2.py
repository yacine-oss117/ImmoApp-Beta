"""
Listings Tab V2 - QTreeView Implementation

High-performance table with hierarchical listings and expandable offers.
Matches the same architecture as ClientsTabV2.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

from PySide6.QtCore import QModelIndex, QTimer
from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import QWidget

from app.utils.i18n import tr_factory
from app.views.imports.import_experience import build_import_banner
from app.views.imports.wizard_dialog import open_import_wizard
from app.views.listing_sql_model import ListingSQLModel
from app.views.listings_v2_actions import ListingsTabActionsMixin
from app.views.listings_v2_handlers import ListingsTabHandlersMixin
from app.views.listings_v2_ui import ListingsTabUi, build_listings_tab_ui
from app.views.tree_expand_controller import TreeExpandController
from app.widgets.offer_panel import OfferPanel

logger = logging.getLogger(__name__)
_TR = tr_factory("ListingsTabV2")


class ListingsTabV2(ListingsTabActionsMixin, ListingsTabHandlersMixin, QWidget):
    """
    Listings tab built on QTreeView with a SQL-backed model.

    Features:
    - Hierarchical display: Listings with expandable Offers
    - Virtualized rendering for 60fps with 10,000+ rows
    - Prefix search across all fields
    - Column sorting
    - Inline action buttons (edit/delete)
    - Column separators for visual clarity
    - Cleans up event filters and offer panels on destroy
    """

    SORTABLE_COLS: set[int] = {0, 5, 6, 7, 10, 11}

    def __init__(
        self,
        refresh_match_counts_cb: Callable[[], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        start = time.perf_counter()
        self.refresh_match_counts_cb = refresh_match_counts_cb
        self.editing_id: int | None = None
        self._offer_panels: list[OfferPanel] = []

        model_start = time.perf_counter()
        self._model = ListingSQLModel(self)
        logger.debug(
            "ListingsTabV2: model created in %.1fms",
            (time.perf_counter() - model_start) * 1000.0,
        )
        model_ms = (time.perf_counter() - model_start) * 1000.0
        ui_start = time.perf_counter()
        self._ui: ListingsTabUi = build_listings_tab_ui(self, self._model)
        logger.debug(
            "ListingsTabV2: UI built in %.1fms",
            (time.perf_counter() - ui_start) * 1000.0,
        )
        ui_ms = (time.perf_counter() - ui_start) * 1000.0
        self._form = self._ui.form

        self._listing_section = self._ui.listing_section
        self._offers_container = self._ui.offers_container
        self._offers_layout = self._ui.offers_layout
        self._add_offer_btn = self._ui.add_offer_btn
        self.save_btn = self._ui.save_btn
        self.clear_btn = self._ui.clear_btn
        self.search_bar = self._ui.search_bar
        self._notice_banner = self._ui.notice_banner
        self._empty_state = self._ui.empty_state
        self._empty_add_btn = self._ui.empty_add_btn
        self._empty_import_btn = self._ui.empty_import_btn
        self._empty_clear_btn = self._ui.empty_clear_btn
        self._empty_title = self._ui.empty_title
        self._empty_text = self._ui.empty_text
        self.filter_handicap = None
        self.tree = self._ui.tree
        self._results_splitter = self._ui.splitter
        self._details_label = self._ui.details_label
        self._coords_label = self._ui.coords_label
        self._open_map_btn = self._ui.open_map_btn
        self._map_url = None
        self._action_delegate = self._ui.action_delegate
        self._first_paint_logged = False

        self._listing_section.collapsed_changed.connect(self._on_listing_section_toggled)
        self._add_offer_btn.clicked.connect(self._add_offer_panel)
        self.save_btn.clicked.connect(self.save_listing)
        self.clear_btn.clicked.connect(self.clear_form)
        self.search_bar.textChanged.connect(self._on_search_changed)
        self.tree.doubleClicked.connect(self._on_double_click)
        self.tree.clicked.connect(self._on_tree_clicked)
        selection_model = self.tree.selectionModel()
        if selection_model is not None:
            selection_model.currentChanged.connect(self._on_selection_changed)
        self._open_map_btn.clicked.connect(self._open_details_map)
        self._action_delegate.editClicked.connect(self._on_edit_action)
        self._action_delegate.deleteClicked.connect(self._on_delete_action)
        self.tree.header().sectionResized.connect(self._on_column_resized)
        self.tree.viewport().installEventFilter(self)

        self._expand_controller = TreeExpandController(
            self.tree,
            self._model,
            expanded_label="🔽",
            collapsed_label="▶️",
            parent=self,
        )
        self._expand_controller.bind_button(self._ui.expand_all_btn)
        self._ui.expand_all_btn.clicked.connect(self._expand_controller.toggle_expand_all)
        self._ui.import_btn.clicked.connect(self._open_import_wizard)
        self._empty_add_btn.clicked.connect(lambda: self._listing_section.expand())
        self._empty_import_btn.clicked.connect(self._open_import_wizard)
        self._empty_clear_btn.clicked.connect(self.search_bar.clear)
        self._model.modelAboutToBeReset.connect(self._expand_controller.cancel_pending)
        self._model.layoutChanged.connect(self._expand_controller.reapply_after_layout_change)
        self._model.modelReset.connect(self._update_empty_state)

        self._offers_container.setVisible(False)
        self.search_bar.installEventFilter(self)
        self._initial_refresh_done = False
        refresh_ms = 0.0
        total_ms = (time.perf_counter() - start) * 1000.0
        if total_ms >= 50:
            logger.info(
                "ListingsTabV2 init: model %.1fms ui %.1fms refresh %.1fms total %.1fms",
                model_ms,
                ui_ms,
                refresh_ms,
                total_ms,
            )
        self.destroyed.connect(self._cleanup)

    def showEvent(self, event: QShowEvent) -> None:
        """Trigger the first data refresh after the show event completes."""
        if not self._initial_refresh_done:
            QTimer.singleShot(0, self._run_initial_refresh)
        super().showEvent(event)

    def _run_initial_refresh(self) -> None:
        if self._initial_refresh_done:
            return
        refresh_start = time.perf_counter()
        self.refresh_table()
        logger.debug(
            "ListingsTabV2: refresh_table in %.1fms",
            (time.perf_counter() - refresh_start) * 1000.0,
        )
        self._initial_refresh_done = True

    def _open_import_wizard(self) -> None:
        final_state = open_import_wizard(self, entity_type_hint="listing")
        if final_state is None:
            return
        rows_changed = self._import_changed_rows(final_state)
        self._restore_post_import_view(clear_search=rows_changed)
        summary = final_state.experience_summary if final_state is not None else None
        if summary is not None:
            state, title, body = build_import_banner(summary)
            self._notice_banner.show_notice(state=state, title=title, body=body, show_details=False)

    @staticmethod
    def _import_changed_rows(final_state: object) -> bool:
        return any(
            int(getattr(final_state, field, 0) or 0) > 0
            for field in ("created_count", "updated_count")
        )

    def _restore_post_import_view(self, *, clear_search: bool) -> None:
        self._expand_controller.cancel_pending()
        self._expand_controller.set_all_expanded(False)
        self.tree.clearSelection()
        self.tree.setCurrentIndex(QModelIndex())
        self._set_map_preview(None)
        if clear_search and self.search_bar.text().strip():
            signals_were_blocked = self.search_bar.blockSignals(True)
            self.search_bar.clear()
            self.search_bar.blockSignals(signals_were_blocked)
        self.refresh_table()
        if clear_search:
            self.tree.scrollToTop()

    def prime_data(self) -> None:
        """Refresh data while splash is visible to avoid first-show jank."""
        if self._initial_refresh_done:
            return
        refresh_start = time.perf_counter()
        self.refresh_table()
        logger.debug(
            "ListingsTabV2: prime_data refresh in %.1fms",
            (time.perf_counter() - refresh_start) * 1000.0,
        )
        self._initial_refresh_done = True

    def _update_empty_state(self) -> None:
        show_empty = self._model.rowCount() == 0
        filtered_empty = show_empty and bool(self.search_bar.text().strip())
        if filtered_empty:
            self._empty_title.setText(_TR("No results match your search"))
            self._empty_text.setText(
                _TR("Clear the search to see all properties and offers again.")
            )
        else:
            self._empty_title.setText(_TR("No properties yet"))
            self._empty_text.setText(
                _TR(
                    "Use the form above to add a property, or use the Import button in the toolbar."
                )
            )
        self._empty_state.setVisible(show_empty)
        self._empty_add_btn.setVisible(False)
        self._empty_import_btn.setVisible(False)
        self._empty_clear_btn.setVisible(filtered_empty)
        self._results_splitter.setVisible(True)
