from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# Only these files may touch opentelemetry metrics directly.
ALLOWLIST = {
    "core/observability/metrics.py",
    "server/immoapp_server/observability.py",
}

BANNED_IMPORT_MODULES = {
    "opentelemetry.metrics",
    "opentelemetry.sdk.metrics",
}

BANNED_ATTR_CALLS = {
    ("metrics", "get_meter"),
    ("otel_metrics", "get_meter"),
}


def _is_repo_py_file(p: Path) -> bool:
    if p.suffix != ".py":
        return False
    rel = p.relative_to(REPO_ROOT).as_posix()
    if rel.startswith(
        (
            ".venv/",
            "venv/",
            ".git/",
            ".cache/",
            ".mypy_cache/",
            "appdata/",
            "dist/",
            "build/",
        )
    ):
        return False
    if "/migrations/" in rel:
        return False
    return True


def _scan_file(path: Path) -> list[str]:
    rel = path.relative_to(REPO_ROOT).as_posix()
    if rel in ALLOWLIST:
        return []

    text = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError as exc:
        return [f"{rel}: syntax error: {exc}"]

    violations: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in BANNED_IMPORT_MODULES or alias.name.startswith(
                    "opentelemetry.metrics"
                ):
                    violations.append(
                        f"{rel}:{node.lineno} direct import '{alias.name}' is forbidden. "
                        "Use core.observability.metrics.get_meter()."
                    )

        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if (
                mod in BANNED_IMPORT_MODULES
                or mod.startswith("opentelemetry.metrics")
                or mod.startswith("opentelemetry.sdk.metrics")
            ):
                violations.append(
                    f"{rel}:{node.lineno} direct from-import '{mod}' is forbidden. "
                    "Use core.observability.metrics.get_meter()."
                )
            if mod == "opentelemetry":
                for alias in node.names:
                    if alias.name == "metrics":
                        violations.append(
                            f"{rel}:{node.lineno} direct from-import 'opentelemetry.metrics' via "
                            "'from opentelemetry import metrics' is forbidden. "
                            "Use core.observability.metrics.get_meter()."
                        )

        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
        ):
            base = node.func.value.id
            attr = node.func.attr
            if (base, attr) in BANNED_ATTR_CALLS:
                violations.append(
                    f"{rel}:{node.lineno} direct call '{base}.{attr}(...)' is forbidden. "
                    "Use core.observability.metrics.get_meter()."
                )

    return violations


def main() -> int:
    violations: list[str] = []
    for path in REPO_ROOT.rglob("*.py"):
        if _is_repo_py_file(path):
            violations.extend(_scan_file(path))

    if violations:
        print("[verify_no_direct_otel_metrics] FAIL: found forbidden OpenTelemetry metrics usage:")
        for violation in violations:
            print("  -", violation)
        return 1

    print("[verify_no_direct_otel_metrics] OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
