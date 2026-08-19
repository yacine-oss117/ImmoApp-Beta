"""
Dropdown controller for match tab client selection and counts.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

from app.models import Client
from app.services.client_repository import fetch_clients, get_client_by_id
from app.services.match_cache_sync import store_client_match_count
from app.services.match_count_state import MatchCountState
from app.utils.i18n import tr_factory
from app.views.base import QWidget
from app.views.match_dropdown import build_client_display, build_client_dropdown_data
from app.views.match_state import MatchSelectionState
from app.views.match_ui import MatchUiWidgets
from app.views.match_workers import MatchWorkerController

logger = logging.getLogger(__name__)
_TR = tr_factory("MatchDropdownController")


class MatchDropdownController:
    """Manage the match dropdown state and background count updates."""

    def __init__(
        self,
        *,
        ui: MatchUiWidgets,
        worker_controller: MatchWorkerController,
        parent: QWidget,
        max_dropdown_clients: int,
        profile_threshold_ms: float,
    ) -> None:
        self._ui = ui
        self._worker_controller = worker_controller
        self._parent = parent
        self._max_dropdown_clients = max_dropdown_clients
        self._profile_threshold_ms = profile_threshold_ms
        self._match_counts: MatchCountState = MatchCountState()
        self._selection = MatchSelectionState()
        self._search_update_in_progress = False

    @property
    def selection(self) -> MatchSelectionState:
        """Expose selection state for legacy compatibility."""
        return self._selection

    @property
    def match_counts(self) -> MatchCountState:
        """Expose match count state for legacy compatibility."""
        return self._match_counts

    def load_counts_from_cache_or_compute(self) -> None:
        """Load counts for visible clients, compute missing in background."""
        start = time.perf_counter()
        clients = self.refresh_dropdown()
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        if elapsed_ms >= self._profile_threshold_ms:
            logger.info(
                "MatchTab dropdown refresh %.1fms (clients=%d)",
                elapsed_ms,
                len(clients),
            )
        missing = self._match_counts.missing_ids([c.id for c in clients])
        if missing:
            self._worker_controller.start_background_count(missing)

    def on_count_ready(self, client_id: int, count: int) -> None:
        """Update cached match count for a client."""
        self._match_counts.set_count(client_id, count)

    def refresh_dropdown(self, search: str = "") -> list[Client]:
        """Refresh the client dropdown with current match counts."""
        start = time.perf_counter()
        selected_id = self._selection.get_selected_id(
            self._ui.client_select.currentIndex(),
            self._ui.client_select.currentText(),
        )

        try:
            clients = fetch_clients(
                limit=self._max_dropdown_clients,
                search=search,
                status="active",
                fields=["id", "family_name", "phone"],
            )
        except Exception:
            logger.error("Failed to load clients for match dropdown", exc_info=True)
            self._worker_controller.show_error(_TR("Failed to load clients"))
            empty_dropdown = build_client_dropdown_data(
                clients=[],
                counts=self._match_counts,
                min_matches=self._ui.min_matches.value(),
            )
            self._selection.update(empty_dropdown)
            self._ui.client_select.setItems(empty_dropdown.items)
            return []
        try:
            from app.services.match_cache import get_cached_counts_batch

            cached = get_cached_counts_batch([c.id for c in clients])
            self._match_counts.update_counts(cached)
        except Exception:
            logger.error("Failed to get cached counts batch", exc_info=True)
            self._worker_controller.show_error(_TR("Cache read failed"))

        min_filter = self._ui.min_matches.value()

        dropdown = build_client_dropdown_data(
            clients=clients,
            counts=self._match_counts,
            min_matches=min_filter,
        )
        self._selection.update(dropdown)
        self._ui.client_select.setItems(dropdown.items)
        if search:
            self._ui.client_select.setEditText(search)

        if selected_id:
            index = self._selection.find_index_for_id(selected_id)
            if index is not None:
                self._ui.client_select.setCurrentIndex(index)

        elapsed_ms = (time.perf_counter() - start) * 1000.0
        if elapsed_ms >= self._profile_threshold_ms:
            logger.info(
                "MatchTab dropdown build %.1fms (search='%s' clients=%d)",
                elapsed_ms,
                search[:32],
                len(clients),
            )
        return clients

    def refresh_dropdown_and_ignore(self) -> None:
        """Refresh dropdown and ignore the returned client list."""
        self.refresh_dropdown()

    def handle_client_search(self, text: str) -> None:
        """DB-backed search for client dropdown."""
        if self._search_update_in_progress:
            return
        self._search_update_in_progress = True
        try:
            clients = self.refresh_dropdown(search=text.strip())
            missing = self._match_counts.missing_ids([c.id for c in clients])
            if missing:
                self._worker_controller.start_background_count(missing)
        finally:
            self._search_update_in_progress = False

    def get_selected_client_id(self) -> int | None:
        """Get the selected client ID from the dropdown."""
        return self._selection.get_selected_id(
            self._ui.client_select.currentIndex(),
            self._ui.client_select.currentText(),
        )

    def select_client(self, client_id: int, run_match: Callable[[], None]) -> None:
        """Programmatically select a client and run match."""
        index = self._selection.find_index_for_id(client_id)
        if index is not None:
            self._ui.client_select.setCurrentIndex(index)
            run_match()
            return

        target_text = self._selection.find_text_for_id(client_id)
        if target_text:
            self._ui.client_select.setCurrentText(target_text)
            run_match()
            return

        client = get_client_by_id(client_id)
        if client is None:
            logger.debug("Client %s not found in database", client_id)
            return
        self.force_add_client_to_dropdown(client)
        run_match()

    def force_add_client_to_dropdown(self, client: Client) -> str:
        """Force add a client to the dropdown even if filtered out."""
        count = self._match_counts.get_count(client.id)
        display = build_client_display(client, count)

        if display in self._selection.id_map and self._selection.id_map[display] != client.id:
            display = _TR("{display} (id {id})").format(display=display, id=client.id)

        id_to_display: dict[int, str] = {}
        for existing_text, cid in self._selection.id_map.items():
            id_to_display.setdefault(cid, existing_text)

        items: list[str] = []
        for cid in self._selection.ids_by_index:
            display_text = id_to_display.get(cid)
            if display_text:
                items.append(display_text)

        if display not in self._selection.id_map:
            self._selection.id_map[display] = client.id
            self._selection.ids_by_index.append(client.id)
            items.append(display)

        if items:
            self._ui.client_select.setItems(items)

        index = self._selection.find_index_for_id(client.id)
        if index is not None:
            self._ui.client_select.setCurrentIndex(index)
        else:
            self._ui.client_select.setCurrentText(display)

        if count is None:
            self._worker_controller.start_background_count([client.id])

        return display

    def mark_all_dirty(self) -> None:
        """Mark all match counts as dirty and trigger recompute."""
        self._match_counts.clear()
        self._worker_controller.cleanup_all()
        clients = self.refresh_dropdown()
        missing = self._match_counts.missing_ids([c.id for c in clients])
        if missing:
            self._worker_controller.start_background_count(missing)

    def sync_match_count(self, client_id: int, count: int, refresh_dropdown: bool = True) -> None:
        """Keep cached counts aligned with canonical match results."""
        self._match_counts.set_count(client_id, count)
        if not store_client_match_count(client_id, count, context="match tab"):
            logger.warning("Match count cache persistence skipped for client %s", client_id)
        if refresh_dropdown:
            self.refresh_dropdown()
