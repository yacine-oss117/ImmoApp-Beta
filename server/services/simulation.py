"""
Simulation API entrypoints.
"""

from __future__ import annotations

from server.pg.simulation_schema import (
    SIM_SCHEMA,
    SIM_TABLES,
    clone_public_to_sim,
    drop_sim_schema,
    ensure_sim_schema,
    reset_sim_schema,
    save_sim_to_public,
    simulation_status,
)
from server.pg.simulation_seed import seed_fake_data
from server.pg.uow import get_current_schema


def get_active_schema() -> str:
    """Return the currently active search path / schema."""
    return get_current_schema()


__all__ = [
    "SIM_SCHEMA",
    "SIM_TABLES",
    "clone_public_to_sim",
    "drop_sim_schema",
    "ensure_sim_schema",
    "reset_sim_schema",
    "save_sim_to_public",
    "seed_fake_data",
    "simulation_status",
    "get_active_schema",
]
