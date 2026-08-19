"""
Match tab accordion rendering helpers.
"""

from __future__ import annotations

from app.views.match_results_header import build_results_header, format_results_header_text
from app.views.match_results_table import build_demande_section, build_matches_table
from app.views.match_results_types import MatchResultsDeps

__all__ = [
    "MatchResultsDeps",
    "build_results_header",
    "format_results_header_text",
    "build_demande_section",
    "build_matches_table",
]
