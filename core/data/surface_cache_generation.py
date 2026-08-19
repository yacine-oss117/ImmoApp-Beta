"""Durable scoped generations for mutation-sensitive cached read surfaces."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Literal

from core.matcher.ports.db import DbSession
from core.models_cast import as_int

CLIENTS_SURFACE: Literal["clients_surface"] = "clients_surface"
LISTINGS_SURFACE: Literal["listings_surface"] = "listings_surface"
USERS_SURFACE: Literal["users_surface"] = "users_surface"
INVITES_AGENCY_SURFACE: Literal["invites_agency_surface"] = "invites_agency_surface"
INVITES_ACTOR_SURFACE: Literal["invites_actor_surface"] = "invites_actor_surface"
NOTIFICATIONS_AGENCY_SURFACE: Literal["notifications_agency_surface"] = (
    "notifications_agency_surface"
)
NOTIFICATIONS_ROLE_SURFACE: Literal["notifications_role_surface"] = "notifications_role_surface"
NOTIFICATIONS_OWNER_SURFACE: Literal["notifications_owner_surface"] = "notifications_owner_surface"
NOTIFICATIONS_ACTOR_SURFACE: Literal["notifications_actor_surface"] = "notifications_actor_surface"
NOTIFICATIONS_GLOBAL_SURFACE: Literal["notifications_global_surface"] = (
    "notifications_global_surface"
)

SurfaceName = Literal[
    "clients_surface",
    "listings_surface",
    "users_surface",
    "invites_agency_surface",
    "invites_actor_surface",
    "notifications_agency_surface",
    "notifications_role_surface",
    "notifications_owner_surface",
    "notifications_actor_surface",
    "notifications_global_surface",
]

GLOBAL_SCOPE_KEY: Literal["global"] = "global"
ScopeRequest = tuple[str, str, int | None]

_KNOWN_SURFACES = {
    CLIENTS_SURFACE,
    LISTINGS_SURFACE,
    USERS_SURFACE,
    INVITES_AGENCY_SURFACE,
    INVITES_ACTOR_SURFACE,
    NOTIFICATIONS_AGENCY_SURFACE,
    NOTIFICATIONS_ROLE_SURFACE,
    NOTIFICATIONS_OWNER_SURFACE,
    NOTIFICATIONS_ACTOR_SURFACE,
    NOTIFICATIONS_GLOBAL_SURFACE,
}


def agency_scope_key(agency_id: int) -> str:
    agency_id = int(agency_id)
    if agency_id <= 0:
        raise ValueError("agency_id is required for agency-scoped cache generations")
    return f"agency:{agency_id}"


def actor_scope_key(actor_id: int) -> str:
    actor_id = int(actor_id)
    if actor_id <= 0:
        raise ValueError("actor_id is required for actor-scoped cache generations")
    return f"actor:{actor_id}"


def role_scope_key(*, agency_id: int, role: str) -> str:
    normalized_role = str(role or "").strip().lower()
    if not normalized_role:
        raise ValueError("role is required for role-scoped cache generations")
    return f"role:{int(agency_id)}:{normalized_role}"


def owner_scope_key(*, agency_id: int) -> str:
    return f"owner:{int(agency_id)}"


def global_scope_key() -> str:
    return GLOBAL_SCOPE_KEY


def _normalize_surface(surface: str) -> SurfaceName:
    normalized = str(surface or "").strip().lower()
    if normalized not in _KNOWN_SURFACES:
        raise ValueError(f"Unsupported surface cache generation scope: {surface!r}")
    return normalized  # type: ignore[return-value]


def _normalize_scope_request(
    *, surface: str, scope_key: str, agency_id: int | None
) -> ScopeRequest:
    normalized_surface = _normalize_surface(surface)
    normalized_scope_key = str(scope_key or "").strip().lower()
    if not normalized_scope_key:
        raise ValueError("scope_key is required for surface cache generations")
    if normalized_scope_key == GLOBAL_SCOPE_KEY:
        return normalized_surface, GLOBAL_SCOPE_KEY, None
    normalized_agency_id = int(agency_id or 0)
    if normalized_agency_id <= 0:
        raise ValueError("agency_id is required for non-global surface cache generations")
    return normalized_surface, normalized_scope_key, normalized_agency_id


def _normalize_scope_requests(requests: Iterable[ScopeRequest]) -> list[ScopeRequest]:
    normalized: list[ScopeRequest] = []
    seen: set[tuple[str, str]] = set()
    for surface, scope_key, agency_id in requests:
        item = _normalize_scope_request(
            surface=surface,
            scope_key=scope_key,
            agency_id=agency_id,
        )
        dedupe_key = (item[0], item[1])
        if dedupe_key in seen:
            continue
        normalized.append(item)
        seen.add(dedupe_key)
    return normalized


def _first_row(result: object) -> dict[str, object] | None:
    fetchone = getattr(result, "fetchone", None)
    if callable(fetchone):
        row = fetchone()
        if row is None:
            return None
        return dict(row)

    fetchall = getattr(result, "fetchall", None)
    if callable(fetchall):
        rows = fetchall()
        if not rows:
            return None
        return dict(rows[0])

    return None


def _build_multi_row_placeholders(count: int) -> str:
    return ", ".join(["(%s, %s)"] * max(1, int(count)))


def read_generations(
    session: DbSession,
    *,
    requests: Iterable[ScopeRequest],
) -> dict[tuple[str, str], int]:
    normalized_requests = _normalize_scope_requests(requests)
    if not normalized_requests:
        return {}
    placeholders = _build_multi_row_placeholders(len(normalized_requests))
    params: list[object] = []
    defaults = {(surface, scope_key): 1 for surface, scope_key, _agency_id in normalized_requests}
    for surface, scope_key, _agency_id in normalized_requests:
        params.extend([surface, scope_key])
    rows = session.execute(
        f"""
        SELECT surface, scope_key, generation
        FROM surface_cache_generation
        WHERE (surface, scope_key) IN ({placeholders})
        """,
        params,
    ).fetchall()
    result = dict(defaults)
    for row in rows:
        row_dict = dict(row)
        surface = str(row_dict.get("surface") or "")
        scope_key = str(row_dict.get("scope_key") or "")
        if not surface or not scope_key:
            continue
        result[(surface, scope_key)] = max(1, as_int(row_dict.get("generation"), default=1))
    return result


def read_generation(
    session: DbSession,
    *,
    surface: str,
    scope_key: str,
    agency_id: int | None,
) -> int:
    normalized = _normalize_scope_request(surface=surface, scope_key=scope_key, agency_id=agency_id)
    generations = read_generations(session, requests=[normalized])
    return int(generations.get((normalized[0], normalized[1]), 1))


def _upsert_generation_sql() -> str:
    return """
        INSERT INTO surface_cache_generation (surface, scope_key, agency_id, generation, updated_at)
        VALUES (%s, %s, %s, 2, CURRENT_TIMESTAMP)
        ON CONFLICT (surface, scope_key)
        DO UPDATE SET
            generation = surface_cache_generation.generation + 1,
            agency_id = EXCLUDED.agency_id,
            updated_at = CURRENT_TIMESTAMP
        RETURNING generation
    """


def bump_generation(
    session: DbSession,
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
    row = _first_row(
        session.execute(
            _upsert_generation_sql(),
            (normalized_surface, normalized_scope_key, normalized_agency_id),
        )
    )
    if not row:
        return 1
    return max(1, as_int(row.get("generation"), default=1))


def bump_generations(
    session: DbSession,
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
        result[scope_key] = bump_generation(
            session,
            surface=normalized_surface,
            scope_key=scope_key,
            agency_id=agency_id,
        )
    return result


__all__ = [
    "CLIENTS_SURFACE",
    "GLOBAL_SCOPE_KEY",
    "INVITES_ACTOR_SURFACE",
    "INVITES_AGENCY_SURFACE",
    "LISTINGS_SURFACE",
    "NOTIFICATIONS_ACTOR_SURFACE",
    "NOTIFICATIONS_AGENCY_SURFACE",
    "NOTIFICATIONS_GLOBAL_SURFACE",
    "NOTIFICATIONS_OWNER_SURFACE",
    "NOTIFICATIONS_ROLE_SURFACE",
    "ScopeRequest",
    "SurfaceName",
    "USERS_SURFACE",
    "actor_scope_key",
    "agency_scope_key",
    "bump_generation",
    "bump_generations",
    "global_scope_key",
    "owner_scope_key",
    "read_generation",
    "read_generations",
    "role_scope_key",
]
