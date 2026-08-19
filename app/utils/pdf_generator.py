"""
PDF Generator - Secure contract PDF generation with anti-fraud features.

Features:
- Guilloche pattern background (anti-counterfeit)
- Watermark with "ORIGINAL" text AND agency logo
- PDF encryption with password protection
- Unique serial number
- E-signature placeholders for 3 parties
- QR code for verification (future)

Usage:
    from app.utils.pdf_generator import generate_contract_pdf

    pdf_path = generate_contract_pdf(
        contract_data={"..."},
        articles=[{"title": "...", "content": "..."}, ...],
        output_path="/path/to/contract.pdf"
    )
"""

import logging
import os
from collections.abc import Mapping, Sequence
from datetime import datetime

from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.utils.pdf_layout import (
    PAGE_HEIGHT,
    PAGE_WIDTH,
    _build_articles,
    _build_signatures,
    _draw_guilloche_pattern,
    _draw_watermark,
    _get_styles,
    _HasPage,
)
from app.utils.pdf_palette import PDF_PAGE_NUMBER, PDF_TABLE_TEXT

logger = logging.getLogger(__name__)


def _draw_page_number(canvas_obj: canvas.Canvas, doc: _HasPage, serial: str) -> None:
    """Draw page number and serial at bottom of each page."""
    canvas_obj.saveState()
    canvas_obj.setFont("Helvetica", 8)
    canvas_obj.setFillColor(PDF_PAGE_NUMBER)

    # Page number on right
    page_num = f"Page {doc.page}"
    canvas_obj.drawRightString(PAGE_WIDTH - 20 * mm, 10 * mm, page_num)

    # Serial on left
    canvas_obj.drawString(20 * mm, 10 * mm, f"Réf: {serial}")

    canvas_obj.restoreState()


class ContractTemplate:
    """Custom page template with security features."""

    def __init__(
        self, agency_logo_path: str | None = None, agency_name: str = "", serial_number: str = ""
    ):
        self.agency_logo_path = agency_logo_path
        self.agency_name = agency_name
        self.serial_number = serial_number

    def on_page(self, canvas_obj: canvas.Canvas, doc: _HasPage) -> None:
        """Called for every page."""
        _draw_guilloche_pattern(canvas_obj, doc)
        _draw_watermark(canvas_obj, doc, self.agency_logo_path, self.agency_name)
        _draw_page_number(canvas_obj, doc, self.serial_number)


def _build_header(styles: dict[str, ParagraphStyle], serial: str, date: str) -> list[object]:
    """Build the contract header elements."""
    elements = []

    # Main title
    elements.append(Paragraph("CONTRAT DE LOCATION", styles["title"]))
    elements.append(Paragraph("(Bail de Location)", styles["subtitle"]))

    # Contract info box
    info_data = [
        ["Numéro de contrat:", serial],
        ["Date:", date],
    ]
    info_table = Table(info_data, colWidths=[100, 200])
    info_table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("TEXTCOLOR", (0, 0), (-1, -1), PDF_TABLE_TEXT),
                ("ALIGN", (0, 0), (0, -1), "RIGHT"),
                ("ALIGN", (1, 0), (1, -1), "LEFT"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    elements.append(info_table)
    elements.append(Spacer(1, 20))

    return elements


def generate_contract_pdf(
    contract_data: Mapping[str, object],
    articles: Sequence[Mapping[str, object]],
    signatures: Mapping[str, Mapping[str, object]],
    output_path: str,
    agency_logo_path: str | None = None,
    agency_name: str = "",
    encrypt: bool = True,
    password: str = "",
) -> str:
    """
    Generate a secure contract PDF with anti-fraud features.

    Args:
        contract_data: Dict with contract info (serial, date, etc.)
        articles: List of article dicts with title/content
        signatures: Dict with agency/owner/tenant signature info
        output_path: Where to save the PDF
        agency_logo_path: Path to agency logo for watermark
        agency_name: Agency name for footer
        encrypt: Whether to encrypt the PDF
        password: Optional password for PDF protection

    Returns:
        The output path on success
    """
    logger.info(f"Generating contract PDF: {output_path}")

    serial = str(contract_data.get("serial_number") or "N/A")
    date = str(contract_data.get("date") or datetime.now().strftime("%d/%m/%Y"))

    # Create the document
    doc = SimpleDocTemplate(
        output_path,
        pagesize=(PAGE_WIDTH, PAGE_HEIGHT),
        rightMargin=20 * mm,
        leftMargin=20 * mm,
        topMargin=25 * mm,
        bottomMargin=25 * mm,
    )

    # Create page template with security features
    template = ContractTemplate(agency_logo_path, agency_name, serial)

    # Get styles
    styles = _get_styles()

    # Build content
    elements = []
    elements.extend(_build_header(styles, serial, date))
    elements.extend(_build_articles(styles, articles))
    elements.extend(_build_signatures(styles, signatures))

    # Add footer note
    elements.append(Spacer(1, 30))
    elements.append(
        Paragraph(
            f"Document généré le {datetime.now().strftime('%d/%m/%Y à %H:%M')} | Réf: {serial}",
            styles["footer"],
        )
    )

    # Build PDF with security template
    doc.build(elements, onFirstPage=template.on_page, onLaterPages=template.on_page)

    # Apply encryption if requested
    if encrypt and password:
        try:
            from pypdf import PdfReader, PdfWriter

            reader = PdfReader(output_path)
            writer = PdfWriter()

            for page in reader.pages:
                writer.add_page(page)

            # Encrypt with password, restrict copying/printing
            writer.encrypt(
                user_password=password,
                owner_password=password,
                permissions_flag=0b0000,  # Restrict all
            )

            with open(output_path, "wb") as f:
                writer.write(f)

            logger.info("PDF encrypted with password protection")
        except ImportError:
            logger.warning("pypdf not available, skipping encryption")
        except (OSError, RuntimeError, ValueError) as exc:
            logger.error("Failed to encrypt PDF", exc_info=True)
            raise RuntimeError("Failed to encrypt PDF") from exc

    logger.info(f"Contract PDF generated: {output_path}")
    return output_path


def generate_contract_preview(
    contract_data: Mapping[str, object],
    articles: Sequence[Mapping[str, object]],
    signatures: Mapping[str, Mapping[str, object]],
    agency_logo_path: str | None = None,
    agency_name: str = "",
) -> str:
    """
    Generate a preview PDF in temp folder.

    Returns:
        Path to the preview PDF
    """
    import tempfile

    output_path = os.path.join(
        tempfile.gettempdir(), f"contract_preview_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    )

    return generate_contract_pdf(
        contract_data=contract_data,
        articles=articles,
        signatures=signatures,
        output_path=output_path,
        agency_logo_path=agency_logo_path,
        agency_name=agency_name,
        encrypt=False,  # No encryption for preview
    )
