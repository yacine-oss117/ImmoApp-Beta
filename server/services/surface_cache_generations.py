"""Django-transaction helpers for durable scoped cache generations."""

from __future__ import annotations

from collections.abc import Iterable

from django.db import connection

from core.data.surface_cache_generation import (
    _normalize_scope_request,
    _normalize_scope_requests,
    _normalize_surface,
    _upsert_generation_sql,
)


def bump_generation_in_atomic(
    *,
    surface: str,
    scope_key: str,
    agency_id: int | None,
) -> int:
    normalized_surface, normalized_scope_key, normalized_agency_id = _normalize_scope_request(
        surface=surface,
        scope_key=scope_key,
        agency_id=agency_id,
    )
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                set_config('app.current_agency_id', %s, true),
                set_config('app.is_superuser', %s, true)
            """,
            (
                str(normalized_agency_id or ""),
                "true" if normalized_agency_id is None else "false",
            ),
        )
        cursor.execute(
            _upsert_generation_sql(),
            (normalized_surface, normalized_scope_key, normalized_agency_id),
        )
        row = cursor.fetchone()
    if not row:
        return 1
    return max(1, int(row[0] or 1))


def bump_generations_in_atomic(
    *,
    surface: str,
    scopes: Iterable[tuple[str, int | None]],
) -> dict[str, int]:
    normalized_surface = _normalize_surface(surface)
    result: dict[str, int] = {}
    normalized_scopes = _normalize_scope_requests(
        (normalized_surface, scope_key, agency_id) for scope_key, agency_id in scopes
    )
    for _surface, scope_key, agency_id in normalized_scopes:
        result[scope_key] = bump_generation_in_atomic(
            surface=normalized_surface,
            scope_key=scope_key,
            agency_id=agency_id,
        )
    return result


__all__ = ["bump_generation_in_atomic", "bump_generations_in_atomic"]
