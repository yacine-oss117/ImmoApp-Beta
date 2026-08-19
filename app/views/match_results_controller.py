"""
Match tab results controller for rendering and actions.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject

from app.models import Listing
from app.services.match_models import ClientMatchResult, MatchResult
from app.services.match_service import expand_matches_for_demande, get_matches_for_demande
from app.utils.i18n import tr_factory
from app.views.base import QLabel, QScrollArea, QVBoxLayout, QWidget
from app.views.match_results import (
    MatchResultsDeps,
    build_demande_section,
    build_results_header,
    format_results_header_text,
)
from app.views.match_results_controller_actions import MatchResultsActionHandlers
from app.widgets.collapsible_section import CollapsibleSection
from app.widgets.user_feedback import UserFacingMessage

_TR = tr_factory("MatchResultsController")


class MatchResultsController:
    """Render and manage match result sections for the Match tab."""

    def __init__(
        self,
        *,
        parent: QWidget,
        results_container: QWidget,
        results_layout: QVBoxLayout,
        scroll_area: QScrollArea,
        placeholder: QLabel,
        get_listing_by_id: Callable[[int], Listing | None],
        get_selected_client_id: Callable[[], int | None],
        get_limit_per_demande: Callable[[], int],
        get_score_threshold: Callable[[], float],
        sender_provider: Callable[[], QObject | None],
        refresh_crm_cb: Callable[[], None] | None,
        feedback_cb: Callable[[UserFacingMessage, int | None], None] | None,
    ) -> None:
        self._parent = parent
        self._results_container = results_container
        self._results_layout = results_layout
        self._scroll_area = scroll_area
        self._placeholder = placeholder
        self._default_placeholder_text = placeholder.text()
        self._get_listing_by_id = get_listing_by_id
        self._get_selected_client_id = get_selected_client_id
        self._get_limit_per_demande = get_limit_per_demande
        self._get_score_threshold = get_score_threshold
        self._sender_provider = sender_provider
        self._actions = MatchResultsActionHandlers(
            parent=parent,
            sender_provider=sender_provider,
            get_selected_client_id=get_selected_client_id,
            refresh_crm_cb=refresh_crm_cb,
            feedback_cb=feedback_cb,
        )
        self._header_label: QLabel | None = None
        self._header_context: tuple[int, float] | None = None
        self._current_result: ClientMatchResult | None = None
        self._sections: dict[int, CollapsibleSection] = {}

    def display_results(
        self,
        result: ClientMatchResult,
        score_threshold: float = 0.0,
        full_count: int | None = None,
    ) -> None:
        """Display match results in accordion UI grouped by demande."""
        self._current_result = result
        self.clear_results()

        # Keep empty state explicit to avoid showing a blank panel.
        if not result.demande_results:
            self._placeholder.setText(
                _TR("This client has no demandes yet. Add at least one demande in Clients tab.")
            )
            self._placeholder.show()
            self._scroll_area.hide()
            return

        self._placeholder.setText(self._default_placeholder_text)
        self._placeholder.hide()
        self._scroll_area.show()

        deps = MatchResultsDeps(
            get_listing_by_id=self._get_listing_by_id,
            create_action_buttons=self._actions.create_action_buttons,
            on_phone_click=self._actions.on_phone_click,
            on_position_click=self._actions.on_position_click,
            on_load_more=self._on_load_more_click,
            on_show_all=self._on_show_all_click,
            allow_pagination=score_threshold <= 0,
        )

        header = build_results_header(
            parent=self._results_container,
            total_unique_offers=result.total_unique_offers,
            score_threshold=score_threshold,
            full_count=full_count,
        )
        self._header_label = header
        self._header_context = (result.total_unique_offers, score_threshold)
        self._results_layout.insertWidget(0, header)

        for i, demande_result in enumerate(result.demande_results):
            section = build_demande_section(
                parent=self._results_container,
                demande_result=demande_result,
                deps=deps,
            )
            self._results_layout.insertWidget(i + 1, section)
            self._sections[demande_result.demande_id] = section

        self._expand_match_sections()

    def clear_results(self) -> None:
        """Clear all demande sections from results."""
        while self._results_layout.count() > 1:  # Keep the stretch
            item = self._results_layout.takeAt(0)
            widget = item.widget() if item else None
            if widget:
                widget.deleteLater()
        self._header_label = None
        self._header_context = None
        self._current_result = None
        self._sections.clear()

    def update_full_count(self, full_count: int) -> None:
        """Update the header with a newly computed full count."""
        if not self._header_label or not self._header_context:
            return
        total_unique_offers, score_threshold = self._header_context
        self._header_label.setText(
            format_results_header_text(
                total_unique_offers,
                score_threshold,
                full_count,
            )
        )

    def _expand_match_sections(self) -> None:
        """Expand visible demande sections so match actions are immediately accessible."""
        for i in range(self._results_layout.count()):
            widget = self._results_layout.itemAt(i).widget()
            if isinstance(widget, CollapsibleSection):
                widget.set_expanded(True)

    def _get_sender_demande_id(self) -> int | None:
        sender = self._sender_provider()
        if sender is None:
            return None
        demande_obj = sender.property("demande_id")
        if isinstance(demande_obj, int):
            return demande_obj
        if isinstance(demande_obj, str):
            try:
                return int(demande_obj)
            except ValueError:
                return None
        return None

    def _find_demande_result(self, demande_id: int) -> MatchResult | None:
        if not self._current_result:
            return None
        for item in self._current_result.demande_results:
            if item.demande_id == demande_id:
                return item
        return None

    def _refresh_demande_section(self, demande_id: int, *, deps: MatchResultsDeps) -> None:
        section = self._sections.get(demande_id)
        demande_result = self._find_demande_result(demande_id)
        if not section or not demande_result:
            return
        expanded = not section.is_collapsed()
        index = self._results_layout.indexOf(section)
        if index < 0:
            return
        item = self._results_layout.takeAt(index)
        widget = item.widget() if item else None
        if widget:
            widget.setParent(None)
            widget.deleteLater()

        new_section = build_demande_section(
            parent=self._results_container,
            demande_result=demande_result,
            deps=deps,
        )
        new_section.set_expanded(expanded)
        self._sections[demande_id] = new_section
        self._results_layout.insertWidget(index, new_section)

    def _fetch_matches_for_demande(
        self,
        demande_id: int,
        *,
        offset: int,
        limit: int,
        score_threshold: float,
    ) -> MatchResult | None:
        return get_matches_for_demande(
            demande_id,
            limit=limit,
            offset=offset,
            score_threshold=score_threshold,
        )

    def _on_load_more_click(self) -> None:
        demande_id = self._get_sender_demande_id()
        if demande_id is None:
            return
        self._load_more_matches(demande_id, show_all=False)

    def _on_show_all_click(self) -> None:
        demande_id = self._get_sender_demande_id()
        if demande_id is None:
            return
        self._load_more_matches(demande_id, show_all=True)

    def _load_more_matches(self, demande_id: int, *, show_all: bool) -> None:
        demande_result = self._find_demande_result(demande_id)
        if not demande_result:
            return
        score_threshold = float(self._get_score_threshold() or 0.0)
        if score_threshold > 0:
            return
        visible_count = len(demande_result.matches)
        if visible_count >= demande_result.total_count:
            return

        limit = int(self._get_limit_per_demande() or 0)
        if limit <= 0:
            limit = 50
        offset = 0 if show_all else visible_count
        fetch_limit = demande_result.total_count if show_all else limit

        if show_all:
            try:
                expand_matches_for_demande(demande_id)
            except RuntimeError:
                pass

        try:
            refreshed = self._fetch_matches_for_demande(
                demande_id,
                offset=offset,
                limit=fetch_limit,
                score_threshold=score_threshold,
            )
        except RuntimeError:
            return
        if not refreshed:
            return

        if show_all:
            demande_result.matches = list(refreshed.matches)
        else:
            existing_ids = {m.offer.id for m in demande_result.matches}
            for match in refreshed.matches:
                if match.offer.id not in existing_ids:
                    demande_result.matches.append(match)
        demande_result.total_count = refreshed.total_count

        deps = MatchResultsDeps(
            get_listing_by_id=self._get_listing_by_id,
            create_action_buttons=self._actions.create_action_buttons,
            on_phone_click=self._actions.on_phone_click,
            on_position_click=self._actions.on_position_click,
            on_load_more=self._on_load_more_click,
            on_show_all=self._on_show_all_click,
            allow_pagination=score_threshold <= 0,
        )
        self._refresh_demande_section(demande_id, deps=deps)
