"""
Clients Tab V2 - QTreeView implementation with SQL-backed model.

Uses ClientSQLModel for scalable, paginated loading and SQL filtering.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QModelIndex
from PySide6.QtWidgets import QWidget

from app.models import Demande
from app.services.demande_repository import delete_demande
from app.utils.i18n import tr_factory
from app.views.base import BaseTableTab
from app.views.client_sql_model import ClientSQLModel
from app.views.clients_v2_actions import ClientsTabActionsMixin
from app.views.clients_v2_handlers import ClientsTabHandlersMixin
from app.views.clients_v2_ui import ClientsTabUi, build_clients_tab_ui
from app.views.imports.import_experience import build_import_banner
from app.views.imports.wizard_dialog import open_import_wizard
from app.views.tree_expand_controller import TreeExpandController
from app.widgets.demande_panel import DemandePanel

_TR = tr_factory("ClientsTabV2")


class ClientsTabV2(ClientsTabActionsMixin, ClientsTabHandlersMixin, BaseTableTab):
    """
    Clients tab built on QTreeView + ClientSQLModel.

    Owns the client form, demande panels, and tree filtering lifecycle.
    Cleans up event filters and nested panels on destroy to avoid leaks.
    """

    SORTABLE_COLS: set[int] = {0, 5, 6, 7, 9, 10}

    def __init__(
        self,
        refresh_match_counts_cb: Callable[[], None] | None = None,
        refresh_clients_cb: Callable[[], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.refresh_match_counts_cb = refresh_match_counts_cb
        self.refresh_clients_cb = refresh_clients_cb
        self.editing_id: int | None = None
        self._demande_panels: list[DemandePanel] = []

        self._model = ClientSQLModel(self)
        self._ui: ClientsTabUi = build_clients_tab_ui(self, self._model)
        self._form = self._ui.form

        self._client_section = self._ui.client_section
        self._demandes_container = self._ui.demandes_container
        self._demandes_layout = self._ui.demandes_layout
        self._demandes_empty = self._ui.demandes_empty
        self._page_scroll = self._ui.page_scroll
        self._add_demande_btn = self._ui.add_demande_btn
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
        self._action_delegate = self._ui.action_delegate
        self._first_paint_logged = False

        self._client_section.collapsed_changed.connect(self._on_client_section_toggled)
        self._add_demande_btn.clicked.connect(lambda _checked=False: self._add_demande_panel())
        self.save_btn.clicked.connect(self.save_client)
        self.clear_btn.clicked.connect(self.clear_form)
        self.search_bar.textChanged.connect(self._on_search_changed)
        self.tree.doubleClicked.connect(self._on_double_click)
        self.tree.clicked.connect(self._on_tree_clicked)
        selection_model = self.tree.selectionModel()
        if selection_model is not None:
            selection_model.currentChanged.connect(self._on_selection_changed)
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
        self._ui.focus_table_btn.clicked.connect(
            lambda _checked=False: self._page_scroll.scroll_to_records()
        )
        self._empty_add_btn.clicked.connect(lambda: self._client_section.expand())
        self._empty_import_btn.clicked.connect(self._open_import_wizard)
        self._empty_clear_btn.clicked.connect(self.search_bar.clear)
        self._model.modelAboutToBeReset.connect(self._expand_controller.cancel_pending)
        self._model.modelReset.connect(self._update_empty_state)

        self._sync_demande_summary_state()
        self.refresh_table()
        self.destroyed.connect(self._cleanup)

    def _open_import_wizard(self) -> None:
        final_state = open_import_wizard(self, entity_type_hint="client")
        if final_state is None:
            return
        rows_changed = self._import_changed_rows(final_state)
        self._restore_post_import_view(clear_search=rows_changed)
        summary = final_state.experience_summary if final_state is not None else None
        if rows_changed and self.refresh_clients_cb:
            self.refresh_clients_cb()
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
        if clear_search and self.search_bar.text().strip():
            signals_were_blocked = self.search_bar.blockSignals(True)
            self.search_bar.clear()
            self.search_bar.blockSignals(signals_were_blocked)
        self.refresh_table()
        if clear_search:
            self.tree.scrollToTop()

    def _update_empty_state(self) -> None:
        show_empty = self._model.rowCount() == 0
        filtered_empty = show_empty and bool(self.search_bar.text().strip())
        if filtered_empty:
            self._empty_title.setText(_TR("No results match your search"))
            self._empty_text.setText(_TR("Clear the search to see all clients and requests again."))
        else:
            self._empty_title.setText(_TR("No clients yet"))
            self._empty_text.setText(
                _TR("Use the form above to add a client, or use the Import button in the toolbar.")
            )
        self._empty_state.setVisible(show_empty)
        self._empty_add_btn.setVisible(False)
        self._empty_import_btn.setVisible(False)
        self._empty_clear_btn.setVisible(filtered_empty)
        self.tree.setVisible(True)

    def _add_demande_panel(self, data: Demande | None = None) -> DemandePanel | None:
        """Add a compact request summary, using a modal editor for new requests."""
        num = len(self._demande_panels) + 1
        panel = DemandePanel(demande_number=num, parent=self._demandes_container)
        panel.delete_requested.connect(lambda p=panel: self._remove_demande_panel(p))

        if data is not None:
            panel.set_data(data)
        elif not panel.edit_request(new_request=True):
            panel.deleteLater()
            return None

        self._demande_panels.append(panel)
        self._demandes_layout.addWidget(panel)
        self._sync_demande_summary_state()
        return panel

    def _sync_demande_summary_state(self) -> None:
        """Keep the compact request-list empty state in sync."""
        has_requests = bool(self._demande_panels)
        self._demandes_empty.setVisible(not has_requests)
        self._demandes_container.setVisible(has_requests)

    def _remove_demande_panel(self, panel: DemandePanel) -> None:
        """Remove a demande panel."""
        if panel in self._demande_panels:
            if panel.demande_id > 0:
                delete_demande(panel.demande_id)
                refresh_table = getattr(self, "refresh_table", None)
                if callable(refresh_table):
                    refresh_table()
                refresh_match_counts_cb = getattr(self, "refresh_match_counts_cb", None)
                if refresh_match_counts_cb:
                    refresh_match_counts_cb()

            self._demande_panels.remove(panel)
            self._demandes_layout.removeWidget(panel)
            panel.deleteLater()

            for i, p in enumerate(self._demande_panels):
                p.set_number(i + 1)
            self._sync_demande_summary_state()
