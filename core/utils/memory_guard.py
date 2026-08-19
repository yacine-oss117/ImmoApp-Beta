"""Adaptive chunk sizing helpers based on Hub runtime pressure facts."""

from __future__ import annotations

from core.runtime.hub_runtime_profile import (
    PRESSURE_RED,
    PRESSURE_YELLOW,
    snapshot_hub_memory_pressure,
)


def adaptive_chunk_size(
    *,
    floor: int = 50,
    ceiling: int = 1000,
    pressure_threshold: float = 80.0,
) -> int:
    """Return a chunk size scaled by memory pressure.

    If memory detection is unavailable, this returns ``ceiling``.
    """
    floor = max(1, int(floor))
    ceiling = max(floor, int(ceiling))
    pressure = snapshot_hub_memory_pressure()
    if pressure.state == PRESSURE_RED:
        return floor
    if pressure.state == PRESSURE_YELLOW:
        return max(floor, int((floor + ceiling) / 2))
    return ceiling


__all__ = ["adaptive_chunk_size"]
