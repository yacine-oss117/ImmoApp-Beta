from __future__ import annotations

import ast
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
_ROOT_URLS = _REPO_ROOT / "server" / "immoapp_server" / "urls.py"
_API_DIR = _REPO_ROOT / "server" / "api"

_PAGINATED_FUNCTIONS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("server/api/views_clients_list.py", ("clients_list", "clients_deleted")),
    ("server/api/views_listings_list.py", ("listings_list", "listings_deleted")),
    ("server/api/views_demandes.py", ("demandes_deleted",)),
    ("server/api/views_offers.py", ("offers_deleted", "offer_photos_endpoint")),
    ("server/api/views_crm_contracts.py", ("crm_contracts", "crm_contracts_deleted")),
    ("server/api/views_crm_visits.py", ("crm_visits", "crm_visits_deleted")),
    ("server/api/views_notifications.py", ("notifications_list",)),
    ("server/api/views_locations.py", ("locations_endpoint",)),
    ("server/api/views_users.py", ("users_list",)),
)


def _assert_root_version_prefix() -> None:
    text = _ROOT_URLS.read_text(encoding="utf-8")
    required = 'path("api/v1/", include("server.api.urls"))'
    if required not in text:
        raise SystemExit(
            "verify_api_contract_policies: missing canonical API prefix mapping "
            f"{required!r} in {_ROOT_URLS}"
        )


def _assert_api_url_paths_relative() -> None:
    for value in _collect_route_paths():
        if value.startswith("/") or value.startswith("api/") or value.startswith("v1/"):
            raise SystemExit(
                "verify_api_contract_policies: API route entries must be relative to /api/v1, "
                f"found {value!r}"
            )


def _assert_policy_contract_metadata() -> None:
    import django

    django.setup()
    from core.contracts.http_policy import HTTP_POLICY_VERSION, RoutePolicy
    from core.contracts.route_policy_registry import ROUTE_POLICIES
    from core.contracts.semantic_header_registry import semantic_header_registry_hash
    from server.api.route_registry import iter_registered_routes

    if not HTTP_POLICY_VERSION.strip():
        raise SystemExit("verify_api_contract_policies: HTTP_POLICY_VERSION must not be empty")
    _ = semantic_header_registry_hash()
    sla_facing_count = 0
    for spec in iter_registered_routes():
        policy = spec.policy
        if spec.path not in ROUTE_POLICIES:
            raise SystemExit(
                "verify_api_contract_policies: missing explicit route policy for "
                f"{spec.path}. Add it to core/contracts/route_policy_registry.py."
            )
        if not policy.policy_id:
            raise SystemExit(
                f"verify_api_contract_policies: missing policy_id for route {spec.path}"
            )
        _assert_budget_values(policy=policy, route_path=spec.path)
        if policy.sla_facing:
            sla_facing_count += 1
    if sla_facing_count <= 0:
        raise SystemExit(
            "verify_api_contract_policies: at least one route must be marked sla_facing."
        )


def _assert_budget_values(*, policy: "RoutePolicy", route_path: str) -> None:
    alert = policy.alert_budget
    if alert.p95_ms <= 0 or alert.max_payload_bytes <= 0 or alert.max_scan_rows <= 0:
        raise SystemExit(
            f"verify_api_contract_policies: invalid alert budget for route {route_path}"
        )
    contract = policy.contract_budget
    if policy.sla_facing and contract is None:
        raise SystemExit(
            f"verify_api_contract_policies: route {route_path} is sla_facing but has no contract_budget"
        )
    if contract is None:
        return
    if contract.p95_ms <= 0 or contract.max_payload_bytes <= 0 or contract.max_scan_rows <= 0:
        raise SystemExit(
            f"verify_api_contract_policies: invalid contract budget for route {route_path}"
        )
    if alert.p95_ms > contract.p95_ms:
        raise SystemExit(
            f"verify_api_contract_policies: route {route_path} violates p95 tier rule "
            "(alert_budget must be <= contract_budget)."
        )
    if alert.max_payload_bytes > contract.max_payload_bytes:
        raise SystemExit(
            f"verify_api_contract_policies: route {route_path} violates payload tier rule "
            "(alert_budget must be <= contract_budget)."
        )
    if alert.max_scan_rows > contract.max_scan_rows:
        raise SystemExit(
            f"verify_api_contract_policies: route {route_path} violates scan tier rule "
            "(alert_budget must be <= contract_budget)."
        )


def _get_function_source(path: Path, name: str) -> str:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            segment = ast.get_source_segment(source, node)
            if segment:
                return segment
    raise SystemExit(f"verify_api_contract_policies: function {name} not found in {path}")


def _assert_paginated_contracts() -> None:
    for rel_path, functions in _PAGINATED_FUNCTIONS:
        path = _REPO_ROOT / rel_path
        if not path.exists():
            raise SystemExit(f"verify_api_contract_policies: missing file {rel_path}")
        for function_name in functions:
            segment = _get_function_source(path, function_name)
            has_list_helper = "list_response(" in segment
            has_items_total = '"items"' in segment and '"total"' in segment
            if not (has_list_helper or has_items_total):
                raise SystemExit(
                    "verify_api_contract_policies: paginated endpoint contract violation - "
                    f"{rel_path}:{function_name} must return items+total or list_response()."
                )


def _collect_route_paths() -> list[str]:
    routes: list[str] = []
    for path in sorted(_API_DIR.glob("views_*.py")):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        for node in tree.body:
            if not isinstance(node, ast.FunctionDef):
                continue
            for decorator in node.decorator_list:
                if not isinstance(decorator, ast.Call):
                    continue
                if not isinstance(decorator.func, ast.Name) or decorator.func.id != "route":
                    continue
                if not decorator.args:
                    continue
                first = decorator.args[0]
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    routes.append(first.value)
    return routes


def main() -> None:
    _assert_root_version_prefix()
    _assert_api_url_paths_relative()
    _assert_policy_contract_metadata()
    _assert_paginated_contracts()
    print("verify_api_contract_policies: OK")


if __name__ == "__main__":
    main()
