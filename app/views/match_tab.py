"""
Match tab orchestration (UI wiring + controllers).
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from PySide6.QtCore import QTimer

from app.models import Client
from app.services.listing_repository import get_listing_by_id
from app.services.match_count_state import MatchCountState
from app.services.match_models import ClientMatchResult
from app.utils.i18n import tr_factory
from app.views.base import BaseTableTab, QWidget
from app.views.match_dropdown import build_client_display
from app.views.match_dropdown_controller import MatchDropdownController
from app.views.match_results_controller import MatchResultsController
from app.views.match_state import MatchSelectionState
from app.views.match_tab_actions import MatchTabActionsMixin
from app.views.match_ui import MatchUiWidgets, build_match_ui
from app.views.match_workers import MatchWorkerController
from app.widgets.user_feedback import ActionFeedbackState, UserFacingMessage, show_user_message

logger = logging.getLogger(__name__)
_TR = tr_factory("MatchTab")

_PROFILE_THRESHOLD_MS = 100.0
_MAX_DROPDOWN_CLIENTS = 1000


class MatchTab(MatchTabActionsMixin, BaseTableTab):
    """
    Match Tab - Matches clients with listings using demandes/offers.

    Features:
        - Client dropdown with [N] match counts
        - Background computation (non-blocking)
        - Accordion results grouped by demande
        - Per-demande match counts in headers
        - Shuts down workers and clears UI state on teardown
    """

    def __init__(
        self,
        refresh_crm_cb: Callable[[], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.refresh_crm_cb = refresh_crm_cb
        self._feedback_state = ActionFeedbackState()
        self._match_counts_dirty_flag = False
        self._last_match_result: ClientMatchResult | None = None

        self.ui = build_match_ui(
            parent=self,
            on_client_search=self._on_client_search,
            on_filter_changed=self._on_filter_changed,
            on_run_match=self._on_run_match_clicked,
            on_save_settings=self._save_settings,
        )
        self._alias_ui_attrs(self.ui)
        self._notice_banner = self.ui.notice_banner
        self._run_btn_default_text = self.run_btn.text()

        self._worker_controller = MatchWorkerController(
            parent=self,
            on_count_ready=self._on_count_ready,
            on_all_finished=self._on_workers_finished,
            on_refresh=self._on_workers_refresh,
            progress_text=self.ui.progress_label.setText,
            progress_show=self.ui.progress_label.show,
            progress_hide=self.ui.progress_label.hide,
            progress_style=self._set_progress_state,
            error_style="error",
        )

        self._dropdown_controller = MatchDropdownController(
            ui=self.ui,
            worker_controller=self._worker_controller,
            parent=self,
            max_dropdown_clients=_MAX_DROPDOWN_CLIENTS,
            profile_threshold_ms=_PROFILE_THRESHOLD_MS,
        )

        self._selection: MatchSelectionState = self._dropdown_controller.selection
        self._match_counts: MatchCountState = self._dropdown_controller.match_counts

        self._results_controller = MatchResultsController(
            parent=self,
            results_container=self.ui.results_container,
            results_layout=self.ui.results_layout,
            scroll_area=self.ui.scroll_area,
            placeholder=self.ui.placeholder,
            get_listing_by_id=get_listing_by_id,
            get_selected_client_id=self._dropdown_controller.get_selected_client_id,
            get_limit_per_demande=lambda: int(self.limit.value()),
            get_score_threshold=lambda: float(self.threshold.value()),
            sender_provider=self.sender,
            refresh_crm_cb=self.refresh_crm_cb,
            feedback_cb=self._show_feedback,
        )

        QTimer.singleShot(50, self._load_counts_from_cache_or_compute)
        self.destroyed.connect(self._cleanup_all_workers)

    def _alias_ui_attrs(self, ui: MatchUiWidgets) -> None:
        """Expose UI widgets on the instance for compatibility."""
        self.notice_banner = ui.notice_banner
        self.client_select = ui.client_select
        self.min_matches = ui.min_matches
        self.threshold = ui.threshold
        self.limit = ui.limit
        self.run_btn = ui.run_btn
        self.progress_label = ui.progress_label
        self.results_container = ui.results_container
        self.results_layout = ui.results_layout
        self.scroll_area = ui.scroll_area
        self.placeholder = ui.placeholder

    def _show_feedback(
        self, message: UserFacingMessage, auto_dismiss_ms: int | None = None
    ) -> None:
        self._feedback_state.current = message
        self._feedback_state.auto_dismiss_ms = auto_dismiss_ms
        show_user_message(self._notice_banner, message, auto_dismiss_ms=auto_dismiss_ms)

    # =========================================================================
    # PUBLIC HOOKS (used by MainWindow/splash/tests)
    # =========================================================================

    def _load_counts_from_cache_or_compute(self) -> None:
        """Load counts for visible clients, compute missing in background."""
        self._reset_progress_style()
        self._maybe_refresh_dirty_counts()
        try:
            self._dropdown_controller.load_counts_from_cache_or_compute()
        except Exception:
            logger.error("Match count preload failed", exc_info=True)
            self._worker_controller.show_error(_TR("Failed to preload matches"))

    def _cleanup_all_workers(self) -> None:
        """Stop background workers on shutdown."""
        self._worker_controller.cleanup_all()

    def stop_background_workers(self) -> bool:
        """Safety wrapper for main window."""
        return bool(self._worker_controller.stop_all())

    def refresh_clients(self) -> None:
        """Refresh dropdown clients (used after client edits)."""
        self._reset_progress_style()
        self._dropdown_controller.refresh_dropdown_and_ignore()

    def select_client(self, client_id: int) -> None:
        """Programmatically select a client and run match."""
        self._dropdown_controller.select_client(client_id, self._on_run_match_clicked)

    def mark_all_dirty(self) -> None:
        """Mark all match counts as dirty and trigger recompute."""
        self._dropdown_controller.mark_all_dirty()

    def reset_view(self) -> None:
        """Clear UI results and reset counts after a DB swap."""
        self.run_btn.setEnabled(True)
        self.run_btn.setText(self._run_btn_default_text)
        self.progress_label.hide()
        self._last_match_result = None
        self._results_controller.clear_results()
        self.placeholder.show()
        self.scroll_area.hide()
        self.mark_all_dirty()

    @property
    def _match_counts_dirty(self) -> bool:
        return bool(self._match_counts_dirty_flag)

    @_match_counts_dirty.setter
    def _match_counts_dirty(self, value: bool) -> None:
        self._match_counts_dirty_flag = bool(value)

    # =========================================================================
    # UI EVENT HANDLERS
    # =========================================================================

    def _on_client_search(self, text: str) -> None:
        """DB-backed search for client dropdown."""
        self._dropdown_controller.handle_client_search(text)

    def _on_filter_changed(self) -> None:
        """Handle min matches filter updates."""
        self._save_settings()
        self._dropdown_controller.refresh_dropdown_and_ignore()

    def _on_count_ready(self, client_id: int, count: int) -> None:
        """Update cached match count for a client."""
        self._dropdown_controller.on_count_ready(client_id, count)

    def _on_workers_refresh(self) -> None:
        """Refresh dropdown after background workers finish."""
        self._dropdown_controller.refresh_dropdown_and_ignore()

    def _on_workers_finished(self) -> None:
        """No-op hook for worker completion."""

    # =========================================================================
    # TEST COMPATIBILITY (used by app/tests/test_match_dropdown.py)
    # =========================================================================

    def _force_add_client_to_dropdown(self, client: Client) -> str:
        """Insert a specific client into the dropdown even if filtered out."""
        dropdown_controller = getattr(self, "_dropdown_controller", None)
        if isinstance(dropdown_controller, MatchDropdownController):
            return dropdown_controller.force_add_client_to_dropdown(client)

        dropdown = self.ui.client_select
        items = list(getattr(dropdown, "items", []))

        count = self._match_counts.get_count(client.id)
        display = build_client_display(client, count)

        if display in self._selection.id_map and self._selection.id_map[display] != client.id:
            display = _TR("{display} (id {id})").format(display=display, id=client.id)

        if display not in items:
            items.append(display)
        self._selection.id_map[display] = client.id
        if client.id not in self._selection.ids_by_index:
            self._selection.ids_by_index.append(client.id)

        dropdown.setItems(items)
        if count is None:
            self._worker_controller.start_background_count([client.id])
        return display
