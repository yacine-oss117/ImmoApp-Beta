"""
Postgres-backed dashboard snapshot queries (raw SQL).

Note: agency_id is optional to allow superuser cross-tenant reads.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from typing import cast

from core.utils.row_casts import row_int
from server.pg.uow import get_uow

DASHBOARD_MAX_ITEMS = int(os.environ.get("DASHBOARD_MAX_ITEMS", "5"))


def fetch_dashboard_stats() -> dict[str, object]:
    """Fetch current dashboard statistics directly from Postgres."""
    return _compute_dashboard_stats()


def _coerce_json_list(value: object) -> list[dict[str, object]]:
    if value is None:
        return []
    if isinstance(value, list):
        return [cast(dict[str, object], item) for item in value if isinstance(item, dict)]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        if isinstance(parsed, list):
            return [cast(dict[str, object], item) for item in parsed if isinstance(item, dict)]
    return []


def _compute_dashboard_stats() -> dict[str, object]:
    today = datetime.now().strftime("%Y-%m-%d")
    three_months_from_now = (datetime.now() + timedelta(days=90)).strftime("%Y-%m-%d")

    with get_uow().session() as session:
        query = f"""
            WITH
                client_count AS (
                    SELECT COUNT(*) AS value
                    FROM clients c
                    WHERE c.status = 'active'
                      AND c.deleted_at IS NULL
                ),
                listing_count AS (
                    SELECT COUNT(*) AS value
                    FROM listings l
                    WHERE l.status = 'available'
                      AND l.deleted_at IS NULL
                ),
                today_visits AS (
                    SELECT jsonb_agg(row_to_json(v)) AS items
                    FROM (
                        SELECT v.id, v.client_id, v.listing_id, v.scheduled_date, v.scheduled_time,
                               v.status, v.notes, c.family_name AS client_name,
                               ol.location AS listing_location
                        FROM visits v
                        LEFT JOIN clients c ON c.id = v.client_id
                        LEFT JOIN listings l ON l.id = v.listing_id
                        LEFT JOIN LATERAL (
                            SELECT o.location
                            FROM offers o
                            WHERE o.listing_id = l.id
                              AND o.deleted_at IS NULL
                            ORDER BY o.updated_at DESC NULLS LAST, o.id DESC
                            LIMIT 1
                        ) ol ON true
                        WHERE v.status = 'scheduled'
                          AND v.scheduled_date = %s
                          AND v.deleted_at IS NULL
                          AND (c.deleted_at IS NULL OR c.id IS NULL)
                          AND (l.deleted_at IS NULL OR l.id IS NULL)
                        ORDER BY v.scheduled_time
                        LIMIT {DASHBOARD_MAX_ITEMS}
                    ) v
                ),
                pending_contracts AS (
                    SELECT jsonb_agg(row_to_json(p)) AS items
                    FROM (
                        SELECT co.id, co.client_id, co.listing_id, co.contract_type, co.status,
                               co.created_at, c.family_name AS client_name,
                               ol.location AS listing_location
                        FROM contracts co
                        LEFT JOIN clients c ON c.id = co.client_id
                        LEFT JOIN listings l ON l.id = co.listing_id
                        LEFT JOIN LATERAL (
                            SELECT o.location
                            FROM offers o
                            WHERE o.listing_id = l.id
                              AND o.deleted_at IS NULL
                            ORDER BY o.updated_at DESC NULLS LAST, o.id DESC
                            LIMIT 1
                        ) ol ON true
                        WHERE co.status = 'pending_signature'
                          AND co.deleted_at IS NULL
                          AND (c.deleted_at IS NULL OR c.id IS NULL)
                          AND (l.deleted_at IS NULL OR l.id IS NULL)
                        ORDER BY co.created_at DESC
                        LIMIT {DASHBOARD_MAX_ITEMS}
                    ) p
                ),
                expiring_contracts AS (
                    SELECT jsonb_agg(row_to_json(e)) AS items
                    FROM (
                        SELECT co.id, co.client_id, co.listing_id, co.contract_type, co.end_date,
                               c.family_name AS client_name,
                               ol.location AS listing_location
                        FROM contracts co
                        LEFT JOIN clients c ON c.id = co.client_id
                        LEFT JOIN listings l ON l.id = co.listing_id
                        LEFT JOIN LATERAL (
                            SELECT o.location
                            FROM offers o
                            WHERE o.listing_id = l.id
                              AND o.deleted_at IS NULL
                            ORDER BY o.updated_at DESC NULLS LAST, o.id DESC
                            LIMIT 1
                        ) ol ON true
                        WHERE co.status = 'signed'
                          AND co.end_date IS NOT NULL
                          AND co.end_date <= %s
                          AND co.deleted_at IS NULL
                          AND (c.deleted_at IS NULL OR c.id IS NULL)
                          AND (l.deleted_at IS NULL OR l.id IS NULL)
                        ORDER BY co.end_date
                        LIMIT {DASHBOARD_MAX_ITEMS}
                    ) e
                ),
                hot_leads AS (
                    SELECT jsonb_agg(row_to_json(h)) AS items
                    FROM (
                        SELECT m.client_id,
                               c.family_name AS family_name,
                               c.phone AS phone,
                               m.count,
                               m.computed_at,
                               m.is_dirty
                        FROM match_counts_cache m
                        JOIN clients c ON c.id = m.client_id
                        WHERE m.is_dirty = 0
                          AND m.count >= 5
                          AND c.status = 'active'
                          AND c.deleted_at IS NULL
                        ORDER BY m.count DESC
                        LIMIT {DASHBOARD_MAX_ITEMS}
                    ) h
                )
            SELECT
                (SELECT value FROM client_count) AS client_count,
                (SELECT value FROM listing_count) AS listing_count,
                (SELECT items FROM today_visits) AS today_visits,
                (SELECT items FROM pending_contracts) AS pending_contracts,
                (SELECT items FROM expiring_contracts) AS expiring_contracts,
                (SELECT items FROM hot_leads) AS hot_leads;
        """
        params: list[object] = [
            today,
            three_months_from_now,
        ]
        row = session.execute(query, params).fetchone() or {}
        client_count = row_int(row, "client_count") if row else 0
        listing_count = row_int(row, "listing_count") if row else 0
        visits = _coerce_json_list(row.get("today_visits"))
        pending = _coerce_json_list(row.get("pending_contracts"))
        expiring = _coerce_json_list(row.get("expiring_contracts"))
        hot_leads = _coerce_json_list(row.get("hot_leads"))

    return {
        "client_count": client_count,
        "listing_count": listing_count,
        "today_visits": visits,
        "pending_contracts": pending,
        "expiring_contracts": expiring,
        "hot_leads": hot_leads,
    }
