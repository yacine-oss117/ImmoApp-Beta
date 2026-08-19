from __future__ import annotations

from core.runtime.hub_runtime_profile import HubMemoryPressureSnapshot
from core.utils import memory_guard


def _pressure(state: str) -> HubMemoryPressureSnapshot:
    return HubMemoryPressureSnapshot(state=state, reason=f"test_{state}")


def test_adaptive_chunk_size_defaults_to_ceiling_without_memory_pressure(monkeypatch) -> None:
    monkeypatch.setattr(memory_guard, "snapshot_hub_memory_pressure", lambda: _pressure("green"))
    assert memory_guard.adaptive_chunk_size(floor=50, ceiling=500) == 500


def test_adaptive_chunk_size_scales_down_under_yellow_pressure(monkeypatch) -> None:
    monkeypatch.setattr(memory_guard, "snapshot_hub_memory_pressure", lambda: _pressure("yellow"))
    value = memory_guard.adaptive_chunk_size(
        floor=100,
        ceiling=1000,
        pressure_threshold=80.0,
    )
    assert value == 550


def test_adaptive_chunk_size_returns_floor_under_red_pressure(monkeypatch) -> None:
    monkeypatch.setattr(memory_guard, "snapshot_hub_memory_pressure", lambda: _pressure("red"))
    assert memory_guard.adaptive_chunk_size(floor=100, ceiling=1000) == 100
