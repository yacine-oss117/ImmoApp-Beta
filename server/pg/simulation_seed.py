"""
Simulation fake-data generation helpers.
"""

from __future__ import annotations

import random

from core.constants import (
    CLIENT_ACTIONS,
    CLIENT_FURNISHED,
    CLIENT_TYPES,
    LISTING_ACTIONS,
    LISTING_FURNISHED,
    LISTING_TYPES,
)
from core.data import client_repo_write, listing_repo_write, lookup_tables
from core.data.demande_repo_write_create import create_demande
from core.data.match_cache import mark_all_dirty
from core.data.offer_repo_write import create_offer
from core.utils.row_casts import row_optional_int, row_optional_str, row_str
from core.utils.time import utc_now_iso

from .simulation_schema import SIM_SCHEMA, reset_sim_schema
from .simulation_seed_helpers import (
    beds_from_surface,
    coords_from_location,
    fake_phone,
    index_locations,
    map_link,
    pick_budget,
    pick_choice,
    pick_floor,
    pick_listing_location,
    pick_scope,
    pick_surface,
    pick_wilaya_location,
    round_currency,
)
from .uow import PgSession, admin_transaction, get_current_agency_id, get_uow, use_schema

_FAKE_SEED = 42
_DEFAULT_CLIENTS = 30
_DEFAULT_LISTINGS = 30
_DEFAULT_DEMANDES_PER_CLIENT = 1
_DEFAULT_OFFERS_PER_LISTING = 1
_NATIONWIDE_PROB = 0.0
_WILAYA_ONLY_PROB = 0.05

__all__ = ["SIM_SCHEMA", "seed_fake_data"]


def seed_fake_data(
    *,
    client_count: int = _DEFAULT_CLIENTS,
    listing_count: int = _DEFAULT_LISTINGS,
    demandes_per_client: int = _DEFAULT_DEMANDES_PER_CLIENT,
    offers_per_listing: int = _DEFAULT_OFFERS_PER_LISTING,
) -> dict[str, int]:
    """Create fake data in the simulation schema."""
    reset_sim_schema()
    rng = random.Random(_FAKE_SEED)
    client_types = [t for t in CLIENT_TYPES if t] or ["apartment"]
    listing_types = [t for t in LISTING_TYPES if t] or ["apartment"]
    client_actions = CLIENT_ACTIONS or ["buy"]
    listing_actions = LISTING_ACTIONS or ["sell"]
    client_furnished = [v for v in CLIENT_FURNISHED if v] or ["any"]
    listing_furnished = [v for v in LISTING_FURNISHED if v and v != "any"] or ["yes"]
    agency_id = _resolve_agency_id()
    with use_schema(SIM_SCHEMA):
        with get_uow().transaction() as session:
            locations = _fetch_names(session, "custom_locations") or ["Centre, Algiers - 16"]
            wilaya_locations = index_locations(locations)
            wilayas = list(wilaya_locations.keys()) or ["Algiers - 16"]
            type_ids = _lookup_ids(session, "type")
            action_ids = _lookup_ids(session, "action")
            wilaya_ids = _lookup_ids(session, "wilaya")
            default_type_id = _first_lookup_id(type_ids, "type")
            default_action_id = _first_lookup_id(action_ids, "action")
            default_wilaya_id = _first_lookup_id(wilaya_ids, "wilaya")
            now = utc_now_iso()

            for idx in range(client_count):
                scope = pick_scope(rng, _NATIONWIDE_PROB, _WILAYA_ONLY_PROB)
                wilaya, location = pick_wilaya_location(
                    rng,
                    scope=scope,
                    wilayas=wilayas,
                    locations=locations,
                    wilaya_locations=wilaya_locations,
                )
                action = pick_choice(rng, client_actions)
                prop_type = pick_choice(rng, client_types)
                surface = pick_surface(rng, prop_type)
                beds = beds_from_surface(surface, rng)
                budget = pick_budget(rng, surface, action)
                budget_max = round_currency(budget * rng.uniform(1.05, 1.35))
                floor_min = rng.randint(0, 2)
                floor_max = floor_min + rng.randint(2, 8)
                client_id = client_repo_write.upsert_client(
                    session,
                    {
                        "family_name": f"Sim Client {idx + 1}",
                        "phone": fake_phone(idx),
                        "remarks": f"Simulated client {idx + 1}",
                        "tags": pick_choice(rng, ["lead", "vip", "cold", "hot"]),
                        "is_vip": 1 if rng.random() < 0.05 else 0,
                        "status": "active",
                        "created_at": now,
                        "created_loc": location or wilaya or "algeria",
                        "updated_at": now,
                        "agency_id": agency_id,
                    },
                )
                for d_idx in range(demandes_per_client):
                    demand_surface = surface * rng.uniform(0.9, 1.2)
                    budget_min = round_currency(budget * rng.uniform(0.7, 0.95))
                    budget_max = round_currency(budget * rng.uniform(1.05, 1.35))
                    surface_min = max(20.0, demand_surface * 0.8)
                    surface_max = max(surface_min, demand_surface * 1.4)
                    floor_min = rng.randint(0, 2)
                    floor_max = floor_min + rng.randint(2, 8)
                    create_demande(
                        session,
                        {
                            "client_id": client_id,
                            "type": prop_type,
                            "type_id": _require_lookup_id(
                                type_ids, prop_type, "type", default_id=default_type_id
                            ),
                            "action": action,
                            "action_id": _require_lookup_id(
                                action_ids, action, "action", default_id=default_action_id
                            ),
                            "wilaya": wilaya,
                            "wilaya_id": _require_lookup_id(
                                wilaya_ids, wilaya, "wilaya", default_id=default_wilaya_id
                            ),
                            "locations": location,
                            "beds_min": beds,
                            "surface_min": surface_min,
                            "surface_max": surface_max,
                            "budget_min": budget_min,
                            "budget_max": budget_max,
                            "furnished": pick_choice(rng, client_furnished),
                            "floor_min": floor_min,
                            "floor_max": floor_max,
                            "elevator": 1 if floor_min >= 2 and rng.random() < 0.4 else 0,
                            "tags": pick_choice(rng, ["urgent", "standard", "investor"]),
                            "remarks": f"Simulated demande {idx + 1}-{d_idx + 1}",
                            "agency_id": agency_id,
                        },
                    )

            for idx in range(listing_count):
                wilaya, location = pick_listing_location(
                    rng,
                    wilayas=wilayas,
                    locations=locations,
                    wilaya_locations=wilaya_locations,
                )
                action = pick_choice(rng, listing_actions)
                prop_type = pick_choice(rng, listing_types)
                surface = pick_surface(rng, prop_type)
                beds = beds_from_surface(surface, rng)
                budget = pick_budget(rng, surface, action)
                floor = pick_floor(rng, prop_type)
                elevator = 1 if floor >= 3 and rng.random() < 0.7 else 0
                lat, lon = coords_from_location(location)
                listing_id = listing_repo_write.upsert_listing(
                    session,
                    {
                        "family_name": f"Sim Owner {idx + 1}",
                        "phone": fake_phone(1000 + idx),
                        "remarks": f"Simulated listing {idx + 1}",
                        "is_vip": 1 if rng.random() < 0.04 else 0,
                        "status": "available",
                        "created_at": now,
                        "created_loc": location,
                        "updated_at": now,
                        "agency_id": agency_id,
                    },
                )
                for o_idx in range(offers_per_listing):
                    offer_surface = surface * rng.uniform(0.95, 1.05)
                    offer_budget = budget * rng.uniform(0.9, 1.1)
                    create_offer(
                        session,
                        listing_id,
                        {
                            "type": prop_type,
                            "type_id": _require_lookup_id(
                                type_ids, prop_type, "type", default_id=default_type_id
                            ),
                            "action": action,
                            "action_id": _require_lookup_id(
                                action_ids, action, "action", default_id=default_action_id
                            ),
                            "wilaya": wilaya,
                            "wilaya_id": _require_lookup_id(
                                wilaya_ids, wilaya, "wilaya", default_id=default_wilaya_id
                            ),
                            "location": location,
                            "beds": beds,
                            "surface": offer_surface,
                            "budget": round_currency(offer_budget),
                            "furnished": pick_choice(rng, listing_furnished),
                            "floor": floor,
                            "elevator": elevator,
                            "link": map_link(lat, lon),
                            "latitude": lat,
                            "longitude": lon,
                            "remarks": f"Simulated offer {idx + 1}-{o_idx + 1}",
                            "agency_id": agency_id,
                        },
                    )

            mark_all_dirty(session)

            return {
                "clients": client_count,
                "listings": listing_count,
                "demandes": client_count * demandes_per_client,
                "offers": listing_count * offers_per_listing,
            }


def _resolve_agency_id() -> int:
    """Resolve the active agency id for simulation data."""
    current = get_current_agency_id()
    if current is not None:
        return current
    with admin_transaction() as session:
        row = session.execute("SELECT to_regclass('public.accounts_agency') AS name").fetchone()
        if not row or not row_optional_str(row, "name"):
            raise ValueError("No agency table found for simulation data")
        agency_row = session.execute(
            "SELECT id FROM accounts_agency ORDER BY id LIMIT 1"
        ).fetchone()
        if not agency_row:
            raise ValueError("No agency found for simulation data")
        agency_id = row_optional_int(agency_row, "id")
        if agency_id is None:
            raise ValueError("No agency found for simulation data")
        return agency_id


def _fetch_names(session: PgSession, table: str) -> list[str]:
    rows = session.execute(f"SELECT name FROM {table} ORDER BY id").fetchall()
    return [row_str(row, "name") for row in rows if row_optional_str(row, "name")]


def _lookup_ids(session: PgSession, kind: str) -> dict[str, int]:
    if kind == "type":
        return {
            name.strip().lower(): id_ for id_, name in lookup_tables.get_all_property_types(session)
        }
    if kind == "action":
        return {name.strip().lower(): id_ for id_, name in lookup_tables.get_all_actions(session)}
    if kind == "wilaya":
        out: dict[str, int] = {}
        for id_, name, code in lookup_tables.get_all_wilayas(session):
            out[name.strip().lower()] = id_
            out[code.strip().lower()] = id_
            if " - " in name:
                out[name.split(" - ", 1)[0].strip().lower()] = id_
        return out
    raise ValueError(f"Unsupported lookup kind: {kind}")


def _require_lookup_id(
    index: dict[str, int],
    value: str,
    kind: str,
    *,
    default_id: int | None = None,
) -> int:
    key = value.strip().lower()
    if key in index:
        return index[key]
    if " - " in key and key.split(" - ", 1)[0].strip() in index:
        return index[key.split(" - ", 1)[0].strip()]
    if default_id is not None:
        return default_id
    raise ValueError(f"Simulation seed could not resolve {kind}: {value}")


def _first_lookup_id(index: dict[str, int], kind: str) -> int:
    if not index:
        raise ValueError(f"No lookup ids available for {kind}.")
    return next(iter(index.values()))
