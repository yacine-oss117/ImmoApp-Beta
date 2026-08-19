from __future__ import annotations

import ast
from pathlib import Path

_REPO_ROOT = Path(__file__).parents[3]
_API_DIR = _REPO_ROOT / "server" / "api"


def _is_api_view_decorator(expr: ast.expr) -> bool:
    if isinstance(expr, ast.Call):
        func = expr.func
    else:
        func = expr
    if isinstance(func, ast.Name):
        return func.id in {"api_view", "drf_api_view"}
    return False


def _extract_route_args(expr: ast.expr) -> tuple[str | None, int | None]:
    if not isinstance(expr, ast.Call):
        return None, None
    if not isinstance(expr.func, ast.Name) or expr.func.id != "route":
        return None, None
    route_path: str | None = None
    order: int | None = None
    if expr.args:
        arg = expr.args[0]
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            route_path = arg.value
    for kw in expr.keywords:
        if kw.arg != "order":
            continue
        if isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, int):
            order = kw.value.value
    return route_path, order


def _collect_route_decorators() -> list[tuple[str, int | None, str]]:
    routes: list[tuple[str, int | None, str]] = []
    for file_path in sorted(_API_DIR.glob("views_*.py")):
        source = file_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(file_path))
        for node in tree.body:
            if not isinstance(node, ast.FunctionDef):
                continue
            for decorator in node.decorator_list:
                path, order = _extract_route_args(decorator)
                if path is not None:
                    routes.append((path, order, f"{file_path.name}:{node.name}"))
    return routes


def test_route_registry_preserves_api_path_count() -> None:
    routes = _collect_route_decorators()
    paths = [route[0] for route in routes]
    assert len(paths) == 185, f"Expected 185 API routes, found {len(paths)}"
    assert len(paths) == len(set(paths)), "Duplicate API paths detected"


def test_route_registry_contains_core_contract_paths() -> None:
    routes = _collect_route_decorators()
    paths = {route[0] for route in routes}
    expected = {
        "health/",
        "meta/policy/",
        "clients/",
        "clients/changes/",
        "listings/",
        "offers/<int:offer_id>/",
        "matches/client/<int:client_id>/",
        "crm/contracts/",
        "audit/logs/",
        "import/upload/",
        "import/<str:session_id>/review/",
        "import/<str:session_id>/cancel/",
        "auth/register/",
        "hub/front-door/identity/",
        "hub-manager/owner-state/",
        "hub-manager/authorizations/",
        "hub-manager/authorizations/consume/",
    }
    missing = sorted(expected - paths)
    assert not missing, f"Missing core API paths: {missing}"


def test_routes_have_stable_order_assignment() -> None:
    routes = _collect_route_decorators()
    missing_order = sorted(origin for _, order, origin in routes if order is None)
    assert not missing_order, f"@route decorators missing explicit order: {missing_order}"


def test_all_api_views_have_route_decorator() -> None:
    missing: list[str] = []
    for file_path in sorted(_API_DIR.glob("views_*.py")):
        source = file_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(file_path))
        for node in tree.body:
            if not isinstance(node, ast.FunctionDef):
                continue
            has_api_view = any(_is_api_view_decorator(d) for d in node.decorator_list)
            if not has_api_view:
                continue
            has_route = any(_extract_route_args(d)[0] is not None for d in node.decorator_list)
            if not has_route:
                missing.append(f"{file_path.name}:{node.name}")
    assert not missing, f"API endpoints missing @route decorator: {missing}"
