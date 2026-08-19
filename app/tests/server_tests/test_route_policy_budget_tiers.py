from __future__ import annotations

from core.contracts.route_policy_registry import ROUTE_POLICIES


def test_sla_routes_require_contract_budgets_and_tier_ordering() -> None:
    sla_routes = 0
    for route_path, policy in ROUTE_POLICIES.items():
        if not policy.sla_facing:
            continue
        sla_routes += 1
        assert (
            policy.contract_budget is not None
        ), f"SLA-facing route missing contract budget: {route_path}"
        assert policy.alert_budget.p95_ms <= policy.contract_budget.p95_ms
        assert policy.alert_budget.max_payload_bytes <= policy.contract_budget.max_payload_bytes
        assert policy.alert_budget.max_scan_rows <= policy.contract_budget.max_scan_rows
    assert sla_routes > 0, "At least one route must be marked SLA-facing."
