"""
PDF color palette constants.
"""

from __future__ import annotations

from reportlab.lib import colors

# Keep PDF palette stable and independent from runtime UI theme state.
_PDF_BLUE_NAVY = "#172554"
_PDF_BLUE_700 = "#1d4ed8"
_PDF_SLATE_700 = "#334155"

PDF_GUILLOCHE_LIGHT = colors.Color(0.92, 0.94, 0.96)
PDF_GUILLOCHE_DARK = colors.Color(0.85, 0.90, 0.95)
PDF_WATERMARK = colors.Color(0.8, 0.8, 0.8, alpha=0.15)
PDF_WATERMARK_LIGHT = colors.Color(0.8, 0.8, 0.8, alpha=0.08)
PDF_FOOTER_TEXT = colors.Color(0.6, 0.6, 0.6)
PDF_PAGE_NUMBER = colors.gray
PDF_TITLE = colors.HexColor(_PDF_BLUE_NAVY)
PDF_ARTICLE_TITLE = colors.HexColor(_PDF_BLUE_700)
PDF_TABLE_TEXT = colors.HexColor(_PDF_SLATE_700)

__all__ = [
    "PDF_GUILLOCHE_LIGHT",
    "PDF_GUILLOCHE_DARK",
    "PDF_WATERMARK",
    "PDF_WATERMARK_LIGHT",
    "PDF_FOOTER_TEXT",
    "PDF_PAGE_NUMBER",
    "PDF_TITLE",
    "PDF_ARTICLE_TITLE",
    "PDF_TABLE_TEXT",
]
