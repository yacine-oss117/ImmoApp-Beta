from __future__ import annotations

from pathlib import Path


def test_route_registry_uses_explicit_policy_registry() -> None:
    registry = Path("server/api/route_registry.py").read_text(encoding="utf-8")
    explicit = Path("core/contracts/route_policy_registry.py").read_text(encoding="utf-8")
    assert "get_explicit_route_policy" in registry
    assert "policy: RoutePolicy | None = None" not in registry
    assert "default_route_policy" not in registry
    assert "ROUTE_POLICIES" in explicit
