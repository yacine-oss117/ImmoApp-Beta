"""Contract serial helpers for agency settings."""

from __future__ import annotations

from app.services.agency_settings_cache import get_contract_serial_prefix
from app.services.api_client import api_post, as_dict


def generate_contract_serial() -> str:
    """Generate a new unique contract serial number via the API."""
    prefix = get_contract_serial_prefix()
    response = api_post("/settings/agency/serial", {"prefix": prefix})
    payload = as_dict(response)
    return str(payload.get("serial", ""))


__all__ = ["generate_contract_serial"]
