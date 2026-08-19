"""
Helper routines for PDF layout (watermarks, guilloche, and sections).
"""

from __future__ import annotations

import html
import math
import os
from collections.abc import Mapping, Sequence
from typing import Protocol

from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

from app.utils.pdf_palette import (
    PDF_ARTICLE_TITLE,
    PDF_FOOTER_TEXT,
    PDF_GUILLOCHE_DARK,
    PDF_GUILLOCHE_LIGHT,
    PDF_TITLE,
    PDF_WATERMARK,
    PDF_WATERMARK_LIGHT,
)


class _HasPage(Protocol):
    page: int


def _escape_pdf_text(value: object, *, multiline: bool = False) -> str:
    text = str(value or "")
    escaped = html.escape(text, quote=True)
    if multiline:
        escaped = escaped.replace("\n", "<br/>")
    return escaped


def _draw_guilloche_pattern(
    canvas_obj: canvas.Canvas, doc: _HasPage, *, page_width: float, page_height: float
) -> None:
    """
    Draw a complex guilloche pattern (spirograph-style) for anti-fraud.
    Uses parametric equations for banknote-quality visuals.
    """
    canvas_obj.saveState()

    # Configuration
    center_x = page_width / 2
    center_y = page_height / 2

    # 1. Background micro-mesh (very subtle)
    canvas_obj.setStrokeColor(PDF_GUILLOCHE_LIGHT)
    canvas_obj.setLineWidth(0.2)

    for i in range(0, int(page_width), 10):
        canvas_obj.line(i, 0, i + 50, page_height)
        canvas_obj.line(i + 50, 0, i, page_height)

    # 2. Main Guilloche Rims (Harmonograph/Spirograph logic)
    # x = (R - r) * cos(t) + d * cos((R - r) / r * t)
    # y = (R - r) * sin(t) - d * sin((R - r) / r * t)

    canvas_obj.setStrokeColor(PDF_GUILLOCHE_DARK)
    canvas_obj.setLineWidth(0.5)

    r = 2
    d = 80
    for radius in (150, 200, 250):
        path = canvas_obj.beginPath()
        steps = 1000
        for t in range(steps + 1):
            theta = 2 * math.pi * t / steps * 5  # 5 loops

            # Parametric equation
            x = (radius - r) * math.cos(theta) + d * math.cos((radius - r) / r * theta)
            y = (radius - r) * math.sin(theta) - d * math.sin((radius - r) / r * theta)

            if t == 0:
                path.moveTo(center_x + x, center_y + y)
            else:
                path.lineTo(center_x + x, center_y + y)

        canvas_obj.drawPath(path)

    canvas_obj.restoreState()


def _draw_watermark(
    canvas_obj: canvas.Canvas,
    doc: _HasPage,
    *,
    page_width: float,
    page_height: float,
    agency_logo_path: str | None = None,
    agency_name: str = "",
) -> None:
    """
    Draw watermarks using correct layering and alpha blending.
    """
    canvas_obj.saveState()

    # 1. "ORIGINAL" Diagonal Watermark (Multiple instances)
    canvas_obj.setFont("Helvetica-Bold", 60)
    canvas_obj.setFillColor(PDF_WATERMARK)  # 15% opacity gray

    # Draw primary diagonal
    canvas_obj.translate(page_width / 2, page_height / 2)
    canvas_obj.rotate(45)
    canvas_obj.drawCentredString(0, 0, "ORIGINAL")

    # Draw smaller secondary diagonals
    canvas_obj.setFont("Helvetica-Bold", 30)
    canvas_obj.setFillColor(PDF_WATERMARK_LIGHT)
    canvas_obj.drawCentredString(0, 200, "ORIGINAL")
    canvas_obj.drawCentredString(0, -200, "ORIGINAL")

    canvas_obj.restoreState()

    # 2. Agency Name (if logo missing) or Logo
    if agency_logo_path and os.path.exists(agency_logo_path):
        canvas_obj.saveState()
        try:
            # Draw logo in center with transparency
            logo_width = 200
            logo_height = 200
            x = (page_width - logo_width) / 2
            y = (page_height - logo_height) / 2

            # Note: ReportLab image transparency depends on source file
            canvas_obj.setFillAlpha(0.1)  # Set global alpha for subsequent operations
            canvas_obj.drawImage(
                agency_logo_path,
                x,
                y,
                width=logo_width,
                height=logo_height,
                mask="auto",
                preserveAspectRatio=True,
                anchor="c",
            )
        finally:
            canvas_obj.restoreState()

    # Agency name at bottom
    if agency_name:
        canvas_obj.saveState()
        canvas_obj.setFont("Helvetica", 8)
        canvas_obj.setFillColor(PDF_FOOTER_TEXT)
        canvas_obj.drawCentredString(page_width / 2, 15 * mm, agency_name)
        canvas_obj.restoreState()


def _get_styles() -> dict[str, ParagraphStyle]:
    """Get custom paragraph styles for the contract."""
    styles = getSampleStyleSheet()

    return {
        "title": ParagraphStyle(
            "ContractTitle",
            parent=styles["Heading1"],
            fontSize=18,
            alignment=TA_CENTER,
            spaceAfter=12,
            textColor=PDF_TITLE,
            fontName="Helvetica-Bold",
        ),
        "subtitle": ParagraphStyle(
            "ContractSubtitle",
            parent=styles["Normal"],
            fontSize=12,
            alignment=TA_CENTER,
            spaceAfter=24,
            textColor=PDF_FOOTER_TEXT,
        ),
        "article_title": ParagraphStyle(
            "ArticleTitle",
            parent=styles["Heading2"],
            fontSize=11,
            spaceBefore=16,
            spaceAfter=8,
            textColor=PDF_ARTICLE_TITLE,
            fontName="Helvetica-Bold",
        ),
        "article_content": ParagraphStyle(
            "ArticleContent",
            parent=styles["Normal"],
            fontSize=10,
            alignment=TA_JUSTIFY,
            spaceAfter=8,
            leading=14,
        ),
        "signature_label": ParagraphStyle(
            "SignatureLabel",
            parent=styles["Normal"],
            fontSize=9,
            alignment=TA_CENTER,
            spaceBefore=4,
        ),
        "footer": ParagraphStyle(
            "Footer",
            parent=styles["Normal"],
            fontSize=8,
            alignment=TA_CENTER,
            textColor=PDF_FOOTER_TEXT,
        ),
    }


def _build_articles(
    styles: dict[str, ParagraphStyle], articles: Sequence[Mapping[str, object]]
) -> list[object]:
    """Build the article elements."""
    elements = []

    for article in articles:
        # Article title
        title_raw = article.get("title")
        if title_raw:
            title = _escape_pdf_text(title_raw)
        else:
            title = _escape_pdf_text(f"Article {article.get('article_number', '')}")
        elements.append(Paragraph(title, styles["article_title"]))

        # Article content - handle newlines
        content = _escape_pdf_text(article.get("content") or "", multiline=True)
        elements.append(Paragraph(content, styles["article_content"]))

    return elements


def _build_signatures(
    styles: dict[str, ParagraphStyle],
    signatures: Mapping[str, Mapping[str, object]],
    *,
    page_width: float,
) -> list[object]:
    """
    Build the signature section.

    Args:
        signatures: Dict with keys "agency", "owner", "tenant"
            Each value has "name" and optionally "image_path"
    """
    elements = []

    elements.append(Spacer(1, 30))
    elements.append(
        Paragraph(
            "SIGNATURES",
            ParagraphStyle("SigTitle", fontSize=12, fontName="Helvetica-Bold", alignment=TA_CENTER),
        )
    )
    elements.append(Spacer(1, 20))

    # Build signature boxes
    sig_data = []
    sig_row = []

    for role, label in [
        ("agency", "L'Agence"),
        ("owner", "Le Bailleur"),
        ("tenant", "Le Locataire"),
    ]:
        sig_info = signatures.get(role, {})
        name = _escape_pdf_text(sig_info.get("name") or "_______________")

        # Signature content
        sig_content = f"""
        <para align="center">
        <b>{label}</b><br/><br/>
        <br/><br/><br/>
        ___________________<br/>
        {name}
        </para>
        """
        sig_row.append(Paragraph(sig_content, styles["signature_label"]))

    sig_data.append(sig_row)

    sig_table = Table(sig_data, colWidths=[page_width / 3.5] * 3)
    sig_table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("TOPPADDING", (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
            ]
        )
    )
    elements.append(sig_table)

    return elements
