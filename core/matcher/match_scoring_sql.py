"""
SQL scoring expression used by precompute jobs.

The formula mirrors `calculate_score` from `match_scoring.py` to keep
precomputed ranks consistent with runtime expectations.
"""

from __future__ import annotations

SCORE_RAW_SQL = """
(
    CASE
        WHEN COALESCE(NULLIF(BTRIM(LOWER(d.type)), ''), '') = ''
          OR COALESCE(NULLIF(BTRIM(LOWER(o.type)), ''), '') = ''
          OR BTRIM(LOWER(d.type)) = BTRIM(LOWER(o.type))
        THEN 2.0 ELSE 0.0
    END
    +
    CASE
        WHEN EXISTS (
            SELECT 1
            FROM demande_locations dlx
            WHERE dlx.demande_id = d.id
        ) THEN
            CASE
                WHEN EXISTS (
                    SELECT 1
                    FROM demande_locations dl
                    JOIN offer_locations ol ON ol.location_id = dl.location_id
                    WHERE dl.demande_id = d.id
                      AND ol.offer_id = o.id
                )
                THEN 2.0 ELSE 0.0
            END
        ELSE 1.0
    END
    +
    CASE
        WHEN d.budget_max IS NOT NULL
         AND d.budget_max > 0
         AND o.budget IS NOT NULL
         AND o.budget <= d.budget_max
        THEN LEAST(
            2.0,
            (1.0 - (o.budget::double precision / NULLIF(d.budget_max::double precision, 0.0))) * 4.0
        )
        ELSE 0.0
    END
    +
    CASE
        WHEN d.surface_min IS NOT NULL
         AND d.surface_min > 0
         AND o.surface IS NOT NULL
         AND o.surface >= d.surface_min
        THEN LEAST(
            2.0,
            (
                (o.surface::double precision - d.surface_min::double precision)
                / GREATEST(1.0, d.surface_min::double precision)
            ) * 2.0
        )
        ELSE 0.0
    END
    +
    CASE
        WHEN d.beds_min IS NOT NULL
         AND d.beds_min > 0
         AND o.beds IS NOT NULL
         AND o.beds >= d.beds_min
        THEN LEAST(1.0, (o.beds::double precision - d.beds_min::double precision) * 0.3)
        ELSE 0.0
    END
    +
    CASE
        WHEN COALESCE(NULLIF(BTRIM(LOWER(d.furnished)), ''), '') NOT IN ('', 'any')
         AND BTRIM(LOWER(d.furnished)) = BTRIM(LOWER(COALESCE(o.furnished, '')))
        THEN 1.0
        ELSE 0.0
    END
)
"""

SCORE_SQL = f"ROUND(LEAST({SCORE_RAW_SQL}, 10.0)::numeric, 2)::double precision"

__all__ = ["SCORE_RAW_SQL", "SCORE_SQL"]
