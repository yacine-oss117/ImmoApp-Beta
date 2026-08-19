"""
Match results header helpers.
"""

from __future__ import annotations

from app.utils.i18n import tr_factory
from app.views.base import QLabel, QWidget

_TR = tr_factory("MatchResultsHeader")


def build_results_header(
    parent: QWidget,
    total_unique_offers: int,
    score_threshold: float = 0.0,
    full_count: int | None = None,
) -> QLabel:
    """Create the results header label."""
    header = QLabel(
        format_results_header_text(total_unique_offers, score_threshold, full_count),
        parent=parent,
    )
    header.setObjectName("matchResultsHeader")
    header.setToolTip(
        _TR(
            "Total unique matches counts distinct offers across all demandes. "
            "Per-demande counts are shown inside each section."
        )
    )
    return header


def format_results_header_text(
    total_unique_offers: int,
    score_threshold: float = 0.0,
    full_count: int | None = None,
) -> str:
    """Build the HTML text for the results header label."""
    notes: list[str] = []
    if score_threshold and score_threshold > 0:
        threshold_note = _TR("score >= {score:.1f}").format(score=score_threshold)
        if full_count is not None:
            threshold_note += _TR(", full: {count}").format(count=full_count)
        notes.append(threshold_note)
    note_text = f" ({'; '.join(notes)})" if notes else ""
    return _TR("<b>Total unique matches: {count}{note}</b>").format(
        count=total_unique_offers, note=note_text
    )
