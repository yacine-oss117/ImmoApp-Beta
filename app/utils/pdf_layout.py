"""
Layout helpers for contract PDF generation.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfgen import canvas

from app.utils.pdf_layout_helpers import (
    _build_articles as _build_articles_impl,
)
from app.utils.pdf_layout_helpers import (
    _build_signatures as _build_signatures_impl,
)
from app.utils.pdf_layout_helpers import (
    _draw_guilloche_pattern as _draw_guilloche_pattern_impl,
)
from app.utils.pdf_layout_helpers import (
    _draw_watermark as _draw_watermark_impl,
)
from app.utils.pdf_layout_helpers import (
    _get_styles as _get_styles_impl,
)
from app.utils.pdf_layout_helpers import (
    _HasPage,
)

# Page dimensions
PAGE_WIDTH, PAGE_HEIGHT = A4


def _draw_guilloche_pattern(canvas_obj: canvas.Canvas, doc: _HasPage) -> None:
    _draw_guilloche_pattern_impl(canvas_obj, doc, page_width=PAGE_WIDTH, page_height=PAGE_HEIGHT)


def _draw_watermark(
    canvas_obj: canvas.Canvas,
    doc: _HasPage,
    agency_logo_path: str | None = None,
    agency_name: str = "",
) -> None:
    _draw_watermark_impl(
        canvas_obj,
        doc,
        page_width=PAGE_WIDTH,
        page_height=PAGE_HEIGHT,
        agency_logo_path=agency_logo_path,
        agency_name=agency_name,
    )


def _get_styles() -> dict[str, ParagraphStyle]:
    return _get_styles_impl()


def _build_articles(
    styles: dict[str, ParagraphStyle], articles: Sequence[Mapping[str, object]]
) -> list[object]:
    return _build_articles_impl(styles, articles)


def _build_signatures(
    styles: dict[str, ParagraphStyle], signatures: Mapping[str, Mapping[str, object]]
) -> list[object]:
    return _build_signatures_impl(styles, signatures, page_width=PAGE_WIDTH)
