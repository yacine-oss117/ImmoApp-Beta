"""
Demande section builder for match results.
"""

from __future__ import annotations

import html

from app.services.match_models import MatchResult
from app.utils.i18n import tr_factory
from app.views.base import QHBoxLayout, QLabel, QPushButton, Qt, QVBoxLayout, QWidget
from app.views.match_results_table_builder import build_matches_table
from app.views.match_results_types import MatchResultsDeps
from app.widgets.collapsible_section import CollapsibleSection

_TR = tr_factory("MatchResultsTable")


def build_demande_section(
    parent: QWidget,
    demande_result: MatchResult,
    deps: MatchResultsDeps,
) -> CollapsibleSection:
    """Create a collapsible section for a single demande's results."""
    count = demande_result.count

    visible_count = len(demande_result.matches)
    count_label = f"{count}" if visible_count == count else f"{visible_count}/{count}"
    safe_summary = html.escape(demande_result.demande_summary or "")
    title = f"<b>[{count_label}]</b> {safe_summary}"

    section = CollapsibleSection("", parent=parent)
    section.setObjectName(f"matchDemandeSection_{demande_result.demande_id}")
    section.set_trusted_title_html(title)
    section.set_expanded(False)

    if count > 0:
        table = build_matches_table(section, demande_result.matches, deps)
        actions_panel = QWidget(section)
        actions_panel.setObjectName(f"matchActionsList_{demande_result.demande_id}")
        actions_panel.setAccessibleName(_TR("Match actions"))
        actions_panel.setAccessibleDescription(
            _TR("Primary actions for each visible match result.")
        )
        actions_panel.setProperty("matchActionsList", True)
        actions_layout = QVBoxLayout(actions_panel)
        actions_layout.setContentsMargins(4, 2, 4, 2)
        actions_layout.setSpacing(4)

        for index, match in enumerate(demande_result.matches):
            offer = match.offer
            listing = deps.get_listing_by_id(match.listing_id)
            owner_name = listing.family_name if listing else ""
            offer_id = int(getattr(offer, "id", 0) or 0)
            action_row = QWidget(actions_panel)
            action_row.setObjectName(
                f"matchActionRow_listing_{match.listing_id}_offer_{offer_id}_{index}"
            )
            action_row.setProperty("matchActionRow", True)
            action_row_layout = QHBoxLayout(action_row)
            action_row_layout.setContentsMargins(0, 0, 0, 0)
            action_row_layout.setSpacing(8)

            label_text = owner_name or offer.location or str(match.listing_id)
            action_label = QLabel(label_text, action_row)
            action_label.setObjectName(
                f"matchActionLabel_listing_{match.listing_id}_offer_{offer_id}_{index}"
            )
            action_label.setProperty("immoMuted", True)

            action_row_layout.addWidget(action_label)
            action_row_layout.addStretch()
            action_row_layout.addWidget(
                deps.create_action_buttons(match.listing_id, offer, action_row)
            )
            actions_layout.addWidget(action_row)

        needs_pagination = deps.allow_pagination and visible_count < count
        container = QWidget(section)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(actions_panel)
        layout.addWidget(table)
        if needs_pagination:
            controls = QWidget(container)
            controls_layout = QHBoxLayout(controls)
            controls_layout.setContentsMargins(4, 0, 4, 0)
            controls_layout.setSpacing(8)

            info = QLabel(
                _TR("Showing {visible} of {total}").format(visible=visible_count, total=count),
                controls,
            )
            info.setProperty("immoMuted", True)

            load_more_btn = QPushButton(_TR("Load more"), controls)
            load_more_btn.setObjectName(f"matchLoadMoreButton_{demande_result.demande_id}")
            load_more_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            load_more_btn.setAccessibleName(_TR("Load more matches"))
            load_more_btn.setAccessibleDescription(
                _TR("Load the next page of matches for this demande.")
            )
            load_more_btn.setProperty("immoVariant", "secondary")
            load_more_btn.setProperty("demande_id", demande_result.demande_id)
            load_more_btn.clicked.connect(deps.on_load_more)

            show_all_btn = QPushButton(_TR("Show all"), controls)
            show_all_btn.setObjectName(f"matchShowAllButton_{demande_result.demande_id}")
            show_all_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            show_all_btn.setAccessibleName(_TR("Show all matches"))
            show_all_btn.setAccessibleDescription(
                _TR("Compute and show all matches for this demande.")
            )
            show_all_btn.setProperty("immoVariant", "ghost")
            show_all_btn.setProperty("demande_id", demande_result.demande_id)
            show_all_btn.clicked.connect(deps.on_show_all)

            controls_layout.addWidget(info)
            controls_layout.addStretch()
            controls_layout.addWidget(load_more_btn)
            controls_layout.addWidget(show_all_btn)

            layout.addWidget(controls)
        section.set_content(container)
    else:
        no_match_label = QLabel(_TR("No matching listings found"), parent=section)
        no_match_label.setObjectName("matchNoResultsLabel")
        no_match_label.setProperty("matchNoResults", True)
        no_match_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        section.set_content(no_match_label)

    return section
