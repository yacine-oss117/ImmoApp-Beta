"""
Reference data seeding helpers.
"""

from __future__ import annotations

import logging

from core.data.agency_settings_repository import DEFAULT_SETTINGS
from core.data.locations import ALGERIAN_LOCATIONS
from core.data.lookup_seed_data import ACTIONS, PROPERTY_TYPES, WILAYAS
from core.data.wa_templates_defaults import DEFAULT_TEMPLATES
from core.utils.row_casts import row_optional_int, row_optional_str
from core.utils.time import normalize_timestamp, utc_now_iso

from .uow import PgSession

logger = logging.getLogger(__name__)


def seed_reference_data(session: PgSession) -> None:
    """Seed lookup tables and default settings.

    Uses set_config to set app.current_agency_id so that tenant-scoped tables
    (custom_locations, wa_templates, agency_settings) get their agency_id
    populated via DB DEFAULT rather than explicit column values.
    """
    default_agency_id = get_default_agency_id(session)

    # Non-tenant lookup tables (no agency_id)
    session.executemany(
        "INSERT INTO property_types (id, name, name_ar) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
        PROPERTY_TYPES,
    )
    session.execute("UPDATE property_types SET requires_floor = TRUE WHERE id IN (1, 4)")
    session.executemany(
        "INSERT INTO actions (id, name, name_ar) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
        ACTIONS,
    )
    session.executemany(
        "INSERT INTO wilayas (id, name, code, name_ar) VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING",
        WILAYAS,
    )

    if default_agency_id is not None:
        # Set tenant context so DB DEFAULT fills agency_id
        session.execute(
            "SELECT set_config('app.current_agency_id', %s, true)",
            (str(default_agency_id),),
        )

        # custom_locations: omit agency_id, DB DEFAULT fills it
        session.executemany(
            "INSERT INTO custom_locations (name) VALUES (%s) ON CONFLICT DO NOTHING",
            [(loc,) for loc in ALGERIAN_LOCATIONS],
        )

        # Check if wa_templates need seeding (RLS will scope the count)
        count_row = session.execute("SELECT COUNT(*) AS total FROM wa_templates").fetchone()
        if count_row and "total" in count_row:
            raw_total = count_row["total"]
            count = int(raw_total) if isinstance(raw_total, (int, float, str)) else 0
        else:
            count = 0

        if count == 0:
            for tpl in DEFAULT_TEMPLATES:
                is_default_raw = tpl.get("is_default", 0)
                is_default = (
                    int(is_default_raw) if isinstance(is_default_raw, (int, float, str)) else 0
                )
                # Omit agency_id from INSERT - DB DEFAULT fills it
                session.execute(
                    """
                    INSERT INTO wa_templates (name, template, is_default, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (
                        tpl["name"],
                        tpl["template"],
                        is_default,
                        normalize_timestamp(tpl.get("created_at")) or utc_now_iso(),
                        normalize_timestamp(tpl.get("updated_at")) or utc_now_iso(),
                    ),
                )

        # agency_settings: omit agency_id, DB DEFAULT fills it
        for key, value in DEFAULT_SETTINGS.items():
            session.execute(
                "INSERT INTO agency_settings (key, value, updated_at) "
                "VALUES (%s, %s, CURRENT_TIMESTAMP) "
                "ON CONFLICT (agency_id, key) DO NOTHING",
                (key, value),
            )
    else:
        logger.warning("Skipping tenant seed data: no default agency available")


def get_default_agency_id(session: PgSession) -> int | None:
    """Return the first agency id if the accounts table exists."""
    row = session.execute("SELECT to_regclass('public.accounts_agency') AS name").fetchone()
    if not row or not row_optional_str(row, "name"):
        return None
    agency_row = session.execute("SELECT id FROM accounts_agency ORDER BY id LIMIT 1").fetchone()
    if not agency_row:
        return None
    return row_optional_int(agency_row, "id")
