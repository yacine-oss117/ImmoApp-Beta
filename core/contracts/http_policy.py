"""Shared HTTP policy contract for route metadata and budgets."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

RetryClass = Literal[
    "CHEAP_READ",
    "EXPENSIVE_READ",
    "IDEMPOTENCY_KEY_WRITE",
    "CAS_WRITE",
    "NO_RETRY",
]
CostClass = Literal["CHEAP", "BOUNDED", "EXPENSIVE"]
ReplayMode = Literal["NONE", "FULL_SAFE", "REFERENCE_ONLY"]

HTTP_POLICY_VERSION = "2026-02-21.v14"


@dataclass(frozen=True)
class RouteBudget:
    p95_ms: int
    max_payload_bytes: int
    max_scan_rows: int


@dataclass(frozen=True)
class RoutePolicy:
    policy_id: str
    retry_class: RetryClass
    cost_class: CostClass
    replay_mode: ReplayMode
    breaker_score: int
    alert_budget: RouteBudget
    contract_budget: RouteBudget | None = None
    sla_facing: bool = False

    def __post_init__(self) -> None:
        _validate_budget(self.alert_budget, label=f"{self.policy_id}.alert_budget")
        if self.contract_budget is not None:
            _validate_budget(self.contract_budget, label=f"{self.policy_id}.contract_budget")
            _validate_budget_tiers(
                alert=self.alert_budget,
                contract=self.contract_budget,
                policy_id=self.policy_id,
            )
        if self.sla_facing and self.contract_budget is None:
            raise ValueError(
                f"Route policy '{self.policy_id}' is SLA-facing and must define contract_budget."
            )


_ALERT_DEFAULTS: dict[CostClass, RouteBudget] = {
    "CHEAP": RouteBudget(p95_ms=250, max_payload_bytes=262_144, max_scan_rows=1_000),
    "BOUNDED": RouteBudget(p95_ms=1_000, max_payload_bytes=1_048_576, max_scan_rows=5_000),
    "EXPENSIVE": RouteBudget(p95_ms=5_000, max_payload_bytes=2_097_152, max_scan_rows=20_000),
}


def _validate_budget(budget: RouteBudget, *, label: str) -> None:
    if budget.p95_ms <= 0:
        raise ValueError(f"{label}.p95_ms must be > 0")
    if budget.max_payload_bytes <= 0:
        raise ValueError(f"{label}.max_payload_bytes must be > 0")
    if budget.max_scan_rows <= 0:
        raise ValueError(f"{label}.max_scan_rows must be > 0")


def _validate_budget_tiers(
    *,
    alert: RouteBudget,
    contract: RouteBudget,
    policy_id: str,
) -> None:
    # Alert budget must be stricter-or-equal to the contractual envelope.
    if alert.p95_ms > contract.p95_ms:
        raise ValueError(f"{policy_id}: alert_budget.p95_ms must be <= contract_budget.p95_ms")
    if alert.max_payload_bytes > contract.max_payload_bytes:
        raise ValueError(
            f"{policy_id}: alert_budget.max_payload_bytes must be <= contract_budget.max_payload_bytes"
        )
    if alert.max_scan_rows > contract.max_scan_rows:
        raise ValueError(
            f"{policy_id}: alert_budget.max_scan_rows must be <= contract_budget.max_scan_rows"
        )


def _slugify_policy_id(route_path: str) -> str:
    cleaned = route_path.strip().strip("/")
    if not cleaned:
        return "root"
    out = []
    for ch in cleaned:
        if ch.isalnum():
            out.append(ch.lower())
        else:
            out.append("_")
    slug = "".join(out)
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug.strip("_") or "route"


def _classify_cost(route_path: str) -> CostClass:
    lowered = route_path.lower()
    if "/all/" in lowered or "rebuild" in lowered or lowered.startswith("import/"):
        return "EXPENSIVE"
    if "changes/" in lowered or "batch" in lowered or "counts/" in lowered:
        return "BOUNDED"
    return "CHEAP"


def default_route_policy(route_path: str, *, methods: tuple[str, ...]) -> RoutePolicy:
    method_set = {m.upper() for m in methods}
    write_methods = {"POST", "PUT", "PATCH", "DELETE"}
    if method_set and method_set.issubset({"GET", "HEAD", "OPTIONS"}):
        retry_class: RetryClass = "CHEAP_READ"
        replay_mode: ReplayMode = "NONE"
    elif method_set & {"PUT", "PATCH", "DELETE"}:
        retry_class = "CAS_WRITE"
        replay_mode = "REFERENCE_ONLY"
    elif method_set & write_methods:
        retry_class = "IDEMPOTENCY_KEY_WRITE"
        replay_mode = "FULL_SAFE"
    else:
        retry_class = "NO_RETRY"
        replay_mode = "NONE"

    cost_class = _classify_cost(route_path)
    breaker = 0 if cost_class == "CHEAP" else (1 if cost_class == "BOUNDED" else 2)
    return RoutePolicy(
        policy_id=f"route.{_slugify_policy_id(route_path)}",
        retry_class=retry_class,
        cost_class=cost_class,
        replay_mode=replay_mode,
        breaker_score=breaker,
        alert_budget=_ALERT_DEFAULTS[cost_class],
        contract_budget=None,
    )


def policy_to_dict(policy: RoutePolicy) -> dict[str, object]:
    payload = asdict(policy)
    payload["alert_budget"] = asdict(policy.alert_budget)
    payload["contract_budget"] = (
        asdict(policy.contract_budget) if policy.contract_budget is not None else None
    )
    return payload


__all__ = [
    "CostClass",
    "HTTP_POLICY_VERSION",
    "ReplayMode",
    "RetryClass",
    "RouteBudget",
    "RoutePolicy",
    "default_route_policy",
    "policy_to_dict",
]
