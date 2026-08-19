"""
Phase 4 guardrails: sync-ready backend contracts.

These tests ensure:
1) Every syncable table has a public delta endpoint.
2) Sync serializers include row_version + updated_at + deleted_at.
"""

from __future__ import annotations

import ast
from pathlib import Path

from server.api import response_schemas
from server.immoapp_server import settings_api

_REPO_ROOT = Path(__file__).parents[3]
_API_DIR = _REPO_ROOT / "server" / "api"
_SYNC_VIEWS_FILE = _API_DIR / "views_sync.py"


def _collect_route_paths() -> set[str]:
    routes: set[str] = set()
    for file_path in sorted(_API_DIR.glob("views_*.py")):
        source = file_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(file_path))
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
                    routes.add(first.value)
    return routes


def _sync_view_module() -> ast.Module:
    return ast.parse(_SYNC_VIEWS_FILE.read_text(encoding="utf-8"), filename=str(_SYNC_VIEWS_FILE))


def _sync_view_functions(tree: ast.Module) -> dict[str, ast.FunctionDef]:
    result: dict[str, ast.FunctionDef] = {}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            result[node.name] = node
    return result


def test_sync_endpoints_exist() -> None:
    """Ensure each syncable table has a /changes/ endpoint."""
    routes = _collect_route_paths()
    expected_paths = {
        "clients": "clients/changes/",
        "listings": "listings/changes/",
        "demandes": "demandes/changes/",
        "offers": "offers/changes/",
        "offer_photos": "offers/photos/changes/",
        "visits": "crm/visits/changes/",
        "contracts": "crm/contracts/changes/",
        "contract_articles": "crm/articles/changes/",
        "custom_locations": "locations/changes/",
        "wa_templates": "templates/changes/",
        "agency_settings": "settings/agency/changes/",
    }
    missing = [name for name, path in expected_paths.items() if path not in routes]
    assert not missing, f"Missing sync endpoints for: {', '.join(missing)}"


def test_sync_serializers_include_version_fields() -> None:
    """Ensure sync serializers include row_version, updated_at, deleted_at."""
    serializer_map = {
        "clients": response_schemas.ClientResponseSerializer,
        "listings": response_schemas.ListingResponseSerializer,
        "demandes": response_schemas.DemandeResponseSerializer,
        "offers": response_schemas.OfferResponseSerializer,
        "offer_photos": response_schemas.OfferPhotoResponseSerializer,
        "visits": response_schemas.VisitResponseSerializer,
        "contracts": response_schemas.ContractResponseSerializer,
        "contract_articles": response_schemas.ContractArticleResponseSerializer,
        "custom_locations": response_schemas.CustomLocationResponseSerializer,
        "wa_templates": response_schemas.TemplateResponseSerializer,
        "agency_settings": response_schemas.AgencySettingResponseSerializer,
    }
    required = {"row_version", "updated_at", "deleted_at"}
    missing: dict[str, set[str]] = {}
    for name, serializer_cls in serializer_map.items():
        fields = set(serializer_cls().fields.keys())
        required_missing = required - fields
        if required_missing:
            missing[name] = required_missing
    assert not missing, f"Sync serializer fields missing: {missing}"


def test_sync_views_use_explicit_secured_api_view_with_scoped_throttle() -> None:
    tree = _sync_view_module()
    sync_views = _sync_view_functions(tree)
    targets = (
        "clients_changes",
        "listings_changes",
        "demandes_changes",
        "offers_changes",
        "offer_photos_changes",
        "visits_changes",
        "contracts_changes",
        "contract_articles_changes",
        "custom_locations_changes",
        "templates_changes",
        "agency_settings_changes",
    )
    violations: list[str] = []
    for name in targets:
        fn = sync_views.get(name)
        if fn is None:
            violations.append(f"{name}: missing function")
            continue
        secured_call: ast.Call | None = None
        for decorator in fn.decorator_list:
            if (
                isinstance(decorator, ast.Call)
                and isinstance(decorator.func, ast.Name)
                and decorator.func.id == "secured_api_view"
            ):
                secured_call = decorator
                break
        if secured_call is None:
            violations.append(f"{name}: missing secured_api_view decorator")
            continue
        keyword_map = {kw.arg: kw.value for kw in secured_call.keywords if isinstance(kw.arg, str)}
        throttles = keyword_map.get("throttle_classes")
        if not (
            isinstance(throttles, ast.List)
            and any(
                isinstance(item, ast.Name) and item.id == "ScopedRateThrottle"
                for item in throttles.elts
            )
        ):
            violations.append(
                f"{name}: secured_api_view missing throttle_classes=[ScopedRateThrottle]"
            )
    assert not violations, "Sync decorator contract violations:\n" + "\n".join(violations)


def test_sync_views_assign_sync_throttle_scope() -> None:
    tree = _sync_view_module()
    expected = {
        "clients_changes",
        "listings_changes",
        "demandes_changes",
        "offers_changes",
        "offer_photos_changes",
        "visits_changes",
        "contracts_changes",
        "contract_articles_changes",
        "custom_locations_changes",
        "templates_changes",
        "agency_settings_changes",
    }
    assigned: set[str] = set()
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not (
            isinstance(target, ast.Attribute)
            and target.attr == "throttle_scope"
            and isinstance(target.value, ast.Name)
        ):
            continue
        if not (isinstance(node.value, ast.Constant) and node.value.value == "sync"):
            continue
        assigned.add(target.value.id)
    missing = sorted(expected - assigned)
    assert not missing, f"Missing throttle_scope='sync' assignments for: {', '.join(missing)}"


def test_sync_throttle_rate_is_configured() -> None:
    rates = settings_api.REST_FRAMEWORK.get("DEFAULT_THROTTLE_RATES", {})
    assert isinstance(rates, dict)
    assert "sync" in rates
    assert str(rates["sync"]).strip()
