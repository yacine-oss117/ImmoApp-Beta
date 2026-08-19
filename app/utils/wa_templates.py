"""
WhatsApp template context helpers.
"""

from __future__ import annotations

from datetime import datetime

from app.services.agency_settings_repository import get_agency_name
from app.shared_types import TemplateContext


def build_template_context(
    *,
    client_name: str,
    location: str,
    price: str,
    property_type: str = "property",
    agency_name: str | None = None,
    date: str | None = None,
    time: str | None = None,
) -> TemplateContext:
    """Build a consistent TemplateContext for WhatsApp message rendering."""
    now = datetime.now()
    return {
        "client_name": client_name,
        "agency_name": agency_name or get_agency_name(),
        "date": date or now.strftime("%d/%m/%Y"),
        "time": time or now.strftime("%H:%M"),
        "location": location,
        "price": price,
        "type": property_type,
    }
