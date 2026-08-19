"""Add @route decorators to API endpoint functions based on server/api/urls.py."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "server" / "api"
URLS_PATH = API_DIR / "urls.py"
VIEWS_GLOB = "views_*.py"
ROUTE_IMPORT = "from server.api.route_registry import route"


@dataclass(frozen=True)
class RouteEntry:
    order: int
    path: str
    function_name: str


@dataclass(frozen=True)
class FunctionLocation:
    file_path: Path
    function_name: str
    insert_lineno: int
    already_has_route: bool


def _parse_routes() -> list[RouteEntry]:
    tree = ast.parse(URLS_PATH.read_text(encoding="utf-8"), filename=str(URLS_PATH))
    entries: list[RouteEntry] = []

    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(target, ast.Name) and target.id == "urlpatterns" for target in node.targets
        ):
            continue
        if not isinstance(node.value, ast.List):
            continue
        for order, element in enumerate(node.value.elts):
            if not isinstance(element, ast.Call):
                continue
            if not isinstance(element.func, ast.Name) or element.func.id != "path":
                continue
            if len(element.args) < 2:
                continue
            route_arg = element.args[0]
            view_arg = element.args[1]
            if not (isinstance(route_arg, ast.Constant) and isinstance(route_arg.value, str)):
                continue
            if not (
                isinstance(view_arg, ast.Attribute)
                and isinstance(view_arg.value, ast.Name)
                and view_arg.value.id == "views"
            ):
                continue
            entries.append(
                RouteEntry(
                    order=order,
                    path=route_arg.value,
                    function_name=view_arg.attr,
                )
            )

    if entries:
        return entries

    # Post-cutover fallback: infer routes from existing @route decorators.
    entries.extend(_parse_routes_from_decorators())

    if not entries:
        raise RuntimeError("No route entries found in static urls.py or runtime route registry.")
    return entries


def _parse_routes_from_decorators() -> list[RouteEntry]:
    entries: list[RouteEntry] = []
    for file_path in sorted(API_DIR.glob(VIEWS_GLOB)):
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
                if not (isinstance(first, ast.Constant) and isinstance(first.value, str)):
                    continue
                order: int | None = None
                for kw in decorator.keywords:
                    if kw.arg == "order" and isinstance(kw.value, ast.Constant):
                        if isinstance(kw.value.value, int):
                            order = kw.value.value
                if order is None:
                    continue
                entries.append(
                    RouteEntry(
                        order=order,
                        path=first.value,
                        function_name=node.name,
                    )
                )
    entries.sort(key=lambda item: (item.order, item.path))
    return entries


def _collect_function_locations() -> dict[str, FunctionLocation]:
    locations: dict[str, FunctionLocation] = {}
    for file_path in sorted(API_DIR.glob(VIEWS_GLOB)):
        source = file_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(file_path))
        lines = source.splitlines()
        for node in tree.body:
            if not isinstance(node, ast.FunctionDef):
                continue
            decorator_lines = [decorator.lineno for decorator in node.decorator_list]
            insert_lineno = min(decorator_lines) if decorator_lines else node.lineno
            start_idx = insert_lineno - 1
            end_idx = node.lineno - 1
            decorator_block = "\n".join(lines[start_idx:end_idx])
            has_route = "@route(" in decorator_block
            if node.name in locations:
                raise RuntimeError(f"Duplicate function name across views files: {node.name}")
            locations[node.name] = FunctionLocation(
                file_path=file_path,
                function_name=node.name,
                insert_lineno=insert_lineno,
                already_has_route=has_route,
            )
    return locations


def _ensure_route_import(lines: list[str]) -> list[str]:
    if any(line.strip() == ROUTE_IMPORT for line in lines):
        return lines

    insert_at = 0
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("from __future__ import"):
            insert_at = idx + 1
    if insert_at == 0:
        for idx, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("import ") or stripped.startswith("from "):
                insert_at = idx
                break
    lines.insert(insert_at, ROUTE_IMPORT)
    return lines


def main() -> int:
    routes = _parse_routes()
    locations = _collect_function_locations()

    updates: dict[Path, list[tuple[int, str]]] = {}
    missing: list[str] = []

    for entry in routes:
        location = locations.get(entry.function_name)
        if location is None:
            missing.append(entry.function_name)
            continue
        if location.already_has_route:
            continue
        updates.setdefault(location.file_path, []).append(
            (
                location.insert_lineno,
                f"@route({entry.path!r}, order={entry.order})",
            )
        )

    if missing:
        raise RuntimeError(f"Route functions not found in views files: {sorted(set(missing))}")

    for file_path, insertions in updates.items():
        lines = file_path.read_text(encoding="utf-8").splitlines()
        lines = _ensure_route_import(lines)
        for lineno, decorator in sorted(insertions, key=lambda item: item[0], reverse=True):
            lines.insert(lineno - 1, decorator)
        file_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"Updated {file_path.relative_to(ROOT)} with {len(insertions)} route decorators.")

    if not updates:
        print("No updates needed; route decorators already in sync.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
