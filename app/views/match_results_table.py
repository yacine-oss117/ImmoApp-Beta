"""
Backward-compatible re-exports for match result section/table builders.
"""

from app.views.match_results_section_builder import build_demande_section
from app.views.match_results_table_builder import build_matches_table

__all__ = ["build_demande_section", "build_matches_table"]
