"""Service wrapper for simulation schema controls."""

from __future__ import annotations

from collections.abc import Mapping

from app.services.api_client import JsonValue, api_get, api_post
from app.services.api_config import get_api_schema, set_api_schema


def _as_dict(response: JsonValue | None) -> dict[str, object]:
    if isinstance(response, Mapping):
        return {str(key): value for key, value in response.items()}
    return {}


def simulation_status() -> dict[str, object]:
    """Fetch the current simulation schema status."""
    return _as_dict(api_get("/simulation/status"))


def simulation_start(
    *,
    mode: str = "seed",
    client_count: int | None = None,
    listing_count: int | None = None,
    demandes_per_client: int | None = None,
    offers_per_listing: int | None = None,
) -> dict[str, object]:
    """Start a simulation schema by seeding fake data or cloning public."""
    payload: dict[str, JsonValue] = {"mode": mode}
    if client_count is not None:
        payload["client_count"] = client_count
    if listing_count is not None:
        payload["listing_count"] = listing_count
    if demandes_per_client is not None:
        payload["demandes_per_client"] = demandes_per_client
    if offers_per_listing is not None:
        payload["offers_per_listing"] = offers_per_listing
    return _as_dict(api_post("/simulation/start", payload))


def simulation_save() -> dict[str, object]:
    """Overwrite the real database with simulation data (destructive)."""
    return _as_dict(api_post("/simulation/save"))


def simulation_delete() -> None:
    """Drop the simulation schema."""
    api_post("/simulation/delete")


def set_simulation_active(active: bool) -> None:
    """Persist the schema override for simulation mode."""
    set_api_schema("sim" if active else None)


def is_simulation_active() -> bool:
    """Return True if the client is currently targeting the sim schema."""
    return (get_api_schema() or "") == "sim"
