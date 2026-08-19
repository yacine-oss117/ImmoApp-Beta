"""
Audit log table registry (PostgreSQL-backed).
"""

from __future__ import annotations

AUDIT_TABLES: dict[str, str] = {
    "clients": "id",
    "listings": "id",
    "demandes": "id",
    "offers": "id",
    "offer_photos": "id",
    "visits": "id",
    "contracts": "id",
    "contract_articles": "id",
    "wa_templates": "id",
    "agency_settings": "key",
    "custom_locations": "id",
    "locations": "location_id",
    "property_types": "id",
    "actions": "id",
    "wilayas": "id",
}
