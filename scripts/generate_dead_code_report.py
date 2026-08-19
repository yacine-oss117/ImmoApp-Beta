from __future__ import annotations

import ast
import pathlib
from collections import defaultdict
from typing import Iterable

ROOT = pathlib.Path(__file__).resolve().parents[1]
CANDIDATE_ROOTS = [ROOT / "app", ROOT / "server", ROOT / "core"]
REFERENCE_ONLY_ROOTS = [ROOT / "scripts", ROOT / "tests", ROOT / "app" / "tests"]
CANDIDATE_IGNORE_PARTS = {"__pycache__", "migrations", "tests", "test_importer", "fixtures"}
REFERENCE_IGNORE_PARTS = {"__pycache__", "migrations", "fixtures"}
MANUAL_KEEP_MODULES = {
    # V14 diagnostics flow modules are contract-bearing and tested, even if
    # not yet wired to an always-visible UI action.
    "app.services.diagnostics_client",
    "app.services.diagnostics_export",
    "app.services.diagnostics_signing",
    "app.services.diagnostics_signing_windows",
    # The UI copy contract is loaded via file path by scripts/tests, not via
    # a normal import edge, so the static import graph must keep it explicitly.
    "app.ui.ui_copy_contract",
}


def iter_py_files(
    roots: Iterable[pathlib.Path],
    *,
    ignore_parts: set[str],
) -> Iterable[pathlib.Path]:
    for base in roots:
        if not base.exists():
            continue
        for path in base.rglob("*.py"):
            if any(part in ignore_parts for part in path.parts):
                continue
            yield path


def module_name(path: pathlib.Path) -> str:
    rel = path.relative_to(ROOT)
    return ".".join(rel.with_suffix("").parts)


def resolve_relative_import(mod: str, level: int, target: str) -> str:
    if level <= 0:
        return target
    parts = mod.split(".")
    package = parts[:-1]
    if level > 1:
        package = package[: -(level - 1)]
    if not package:
        return target
    if not target:
        return ".".join(package)
    return ".".join(package + target.split("."))


def collect_modules(
    roots: Iterable[pathlib.Path],
    *,
    ignore_parts: set[str],
) -> dict[str, pathlib.Path]:
    modules: dict[str, pathlib.Path] = {}
    for path in iter_py_files(roots, ignore_parts=ignore_parts):
        modules[module_name(path)] = path
    return modules


def collect_candidate_modules() -> dict[str, pathlib.Path]:
    return collect_modules(CANDIDATE_ROOTS, ignore_parts=CANDIDATE_IGNORE_PARTS)


def collect_reference_modules() -> dict[str, pathlib.Path]:
    return collect_modules(REFERENCE_ONLY_ROOTS, ignore_parts=REFERENCE_IGNORE_PARTS)


def collect_all_modules() -> dict[str, pathlib.Path]:
    modules = collect_candidate_modules()
    modules.update(collect_reference_modules())
    return modules


def build_module_aliases(modules: dict[str, pathlib.Path]) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for mod in modules:
        if mod.startswith("server."):
            trimmed = mod.removeprefix("server.")
            aliases[trimmed] = mod
        if mod.startswith("server.immoapp_server."):
            trimmed = mod.removeprefix("server.")
            aliases[trimmed] = mod
        if mod.startswith("server.accounts."):
            trimmed = mod.removeprefix("server.")
            aliases[trimmed] = mod
        if mod.startswith("server.imports."):
            trimmed = mod.removeprefix("server.")
            aliases[trimmed] = mod
    return aliases


def parse_settings_entrypoints() -> set[str]:
    settings_files = [
        ROOT / "server" / "immoapp_server" / "settings_base.py",
        ROOT / "server" / "immoapp_server" / "settings.py",
        ROOT / "server" / "immoapp_server" / "settings_api.py",
        ROOT / "server" / "immoapp_server" / "settings_auth.py",
        ROOT / "server" / "immoapp_server" / "settings_database.py",
        ROOT / "server" / "immoapp_server" / "settings_logging.py",
        ROOT / "server" / "immoapp_server" / "settings_security.py",
    ]
    entrypoints: set[str] = set()
    for path in settings_files:
        if not path.exists():
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                name = node.targets[0]
                if not isinstance(name, ast.Name):
                    continue
                if name.id in {
                    "INSTALLED_APPS",
                    "MIDDLEWARE",
                    "ROOT_URLCONF",
                    "ASGI_APPLICATION",
                    "WSGI_APPLICATION",
                }:
                    if isinstance(node.value, (ast.List, ast.Tuple)):
                        for item in node.value.elts:
                            if isinstance(item, ast.Constant) and isinstance(item.value, str):
                                value = item.value
                                entrypoints.add(value)
                                if name.id == "MIDDLEWARE" and "." in value:
                                    entrypoints.add(value.rsplit(".", 1)[0])
                                if name.id == "INSTALLED_APPS":
                                    entrypoints.add(f"{value}.apps")
                                    entrypoints.add(f"{value}.admin")
                    if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                        value = node.value.value
                        entrypoints.add(value)
                        if name.id == "MIDDLEWARE" and "." in value:
                            entrypoints.add(value.rsplit(".", 1)[0])
                        if name.id == "INSTALLED_APPS":
                            entrypoints.add(f"{value}.apps")
                            entrypoints.add(f"{value}.admin")
                if name.id == "REST_FRAMEWORK" and isinstance(node.value, ast.Dict):
                    for item in node.value.values:
                        if isinstance(item, ast.Constant) and isinstance(item.value, str):
                            value = item.value
                            entrypoints.add(value)
                            if "." in value:
                                entrypoints.add(value.rsplit(".", 1)[0])
                        if isinstance(item, (ast.List, ast.Tuple)):
                            for sub in item.elts:
                                if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                                    value = sub.value
                                    entrypoints.add(value)
                                    if "." in value:
                                        entrypoints.add(value.rsplit(".", 1)[0])
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                name = node.target
                value_node = node.value
                if value_node is None:
                    continue
                if name.id == "REST_FRAMEWORK" and isinstance(value_node, ast.Dict):
                    for item in value_node.values:
                        if isinstance(item, ast.Constant) and isinstance(item.value, str):
                            value = item.value
                            entrypoints.add(value)
                            if "." in value:
                                entrypoints.add(value.rsplit(".", 1)[0])
                        if isinstance(item, (ast.List, ast.Tuple)):
                            for sub in item.elts:
                                if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                                    value = sub.value
                                    entrypoints.add(value)
                                    if "." in value:
                                        entrypoints.add(value.rsplit(".", 1)[0])
    return entrypoints


def parse_urlconf_entrypoints() -> set[str]:
    urlconf = ROOT / "server" / "immoapp_server" / "urls.py"
    if not urlconf.exists():
        return set()
    entrypoints: set[str] = set()
    tree = ast.parse(urlconf.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            func_name = None
            if isinstance(func, ast.Name):
                func_name = func.id
            elif isinstance(func, ast.Attribute):
                func_name = func.attr
            if func_name != "include":
                continue
            if not node.args:
                continue
            arg = node.args[0]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                entrypoints.add(arg.value)
    return entrypoints


def dynamic_entrypoints(modules: dict[str, pathlib.Path]) -> set[str]:
    entrypoints: set[str] = set()
    api_dir = ROOT / "server" / "api"
    if api_dir.exists():
        for path in api_dir.glob("views_*.py"):
            entrypoints.add(f"server.api.{path.stem}")
        commands_dir = api_dir / "management" / "commands"
        if commands_dir.exists():
            for path in commands_dir.glob("*.py"):
                if path.stem == "__init__":
                    continue
                entrypoints.add(f"server.api.management.commands.{path.stem}")

    secret_store_dir = ROOT / "server" / "secret_store"
    if secret_store_dir.exists():
        for path in secret_store_dir.glob("openbao_runtime_*.py"):
            entrypoints.add(f"server.secret_store.{path.stem}")

    alembic_env = ROOT / "server" / "alembic" / "env.py"
    if alembic_env.exists():
        entrypoints.add("server.alembic.env")
    alembic_versions_dir = ROOT / "server" / "alembic" / "versions"
    if alembic_versions_dir.exists():
        for path in alembic_versions_dir.glob("*.py"):
            if path.stem == "__init__":
                continue
            entrypoints.add(f"server.alembic.versions.{path.stem}")

    if "server.api.task_names" in modules:
        entrypoints.add("server.api.task_names")

    return entrypoints


def build_import_graph(modules: dict[str, pathlib.Path]) -> dict[str, set[str]]:
    incoming: dict[str, set[str]] = defaultdict(set)
    aliases = build_module_aliases(modules)
    for mod, path in modules.items():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for name in node.names:
                    target = aliases.get(name.name, name.name)
                    if target in modules:
                        incoming[target].add(mod)
            elif isinstance(node, ast.ImportFrom):
                if node.module is None:
                    if node.level <= 0:
                        continue
                    base = resolve_relative_import(mod, node.level, "")
                    base = aliases.get(base, base)
                    for name in node.names:
                        sub = f"{base}.{name.name}" if base else name.name
                        sub = aliases.get(sub, sub)
                        if sub in modules:
                            incoming[sub].add(mod)
                    continue
                base = resolve_relative_import(mod, node.level, node.module)
                base = aliases.get(base, base)
                if base in modules:
                    incoming[base].add(mod)
                for name in node.names:
                    sub = f"{base}.{name.name}"
                    sub = aliases.get(sub, sub)
                    if sub in modules:
                        incoming[sub].add(mod)
    return incoming


def resolve_entrypoints(modules: dict[str, pathlib.Path]) -> set[str]:
    entrypoints = {
        "app.main",
        "server.manage",
        "server.immoapp_server.asgi",
        "server.immoapp_server.wsgi",
        "server.immoapp_server.settings",
        "server.immoapp_server.urls",
        "server.immoapp_server.celery",
        "server.immoapp_server.pycache",
    }
    raw_entrypoints = parse_settings_entrypoints()
    raw_entrypoints.update(parse_urlconf_entrypoints())
    raw_entrypoints.update(dynamic_entrypoints(modules))
    aliases = build_module_aliases(modules)
    entrypoints.update(raw_entrypoints)
    entrypoints.update({aliases.get(name, name) for name in raw_entrypoints})
    return entrypoints


def collect_dead_code_candidates() -> list[tuple[str, pathlib.Path]]:
    candidate_modules = collect_candidate_modules()
    modules = collect_all_modules()
    incoming = build_import_graph(modules)
    entrypoints = resolve_entrypoints(modules)

    orphans: list[tuple[str, pathlib.Path]] = []
    for mod, path in candidate_modules.items():
        if mod.endswith("__init__"):
            continue
        if mod in MANUAL_KEEP_MODULES:
            continue
        if mod in entrypoints:
            continue
        if mod not in incoming:
            orphans.append((mod, path))

    orphans.sort()
    return orphans


def build_report(orphans: list[tuple[str, pathlib.Path]]) -> str:
    out: list[str] = []
    out.append("# Dead Code Candidate Report\n")
    out.append("This is a **static** import graph report.\n")
    out.append("Django/DRF/Celery load modules dynamically, so review before deleting.\n")
    out.append("Script/test imports count as inbound references, but only app/server/core ")
    out.append("modules are candidates.\n\n")

    out.append("## High-confidence deletions already done\n")
    out.append("- Removed empty/duplicate placeholders (server/apps.py, server/views.py, ")
    out.append("server/accounts/views.py, server/admin.py, server/models.py).\n\n")

    out.append("## Candidate list (no inbound static imports)\n")
    if not orphans:
        out.append("- None\n")
    else:
        for mod, path in orphans:
            out.append(f"- `{mod}` -> `{path}`\n")
    return "".join(out)


def write_report(report_text: str) -> pathlib.Path:
    report_dir = ROOT / ".cache" / "root-scratch"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / "dead_code_candidates.md"
    report_path.write_text(report_text, encoding="utf-8")
    return report_path


def main() -> None:
    report_path = write_report(build_report(collect_dead_code_candidates()))
    print(f"Wrote {report_path}")


if __name__ == "__main__":
    main()
