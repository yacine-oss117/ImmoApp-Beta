from __future__ import annotations

import ast
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

# If a write endpoint intentionally diverges, add:
# "views_x.py:function_name": "reason"
_ALLOWLIST: dict[str, str] = {}


def _iter_view_functions(tree: ast.Module) -> list[ast.FunctionDef]:
    return [node for node in tree.body if isinstance(node, ast.FunctionDef)]


def _decorated_methods(func: ast.FunctionDef) -> set[str]:
    for dec in func.decorator_list:
        if not isinstance(dec, ast.Call):
            continue
        if not isinstance(dec.func, ast.Name) or dec.func.id != "secured_api_view":
            continue
        if not dec.args:
            continue
        methods_arg = dec.args[0]
        if not isinstance(methods_arg, (ast.List, ast.Tuple)):
            continue
        methods: set[str] = set()
        for elt in methods_arg.elts:
            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                methods.add(elt.value.upper())
        return methods
    return set()


def _call_names(func: ast.FunctionDef) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(func):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name):
            names.add(node.func.id)
        elif isinstance(node.func, ast.Attribute):
            names.add(node.func.attr)
    return names


def _has_require_row_version(func: ast.FunctionDef) -> bool:
    for node in ast.walk(func):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Name) or node.func.id != "validate_payload":
            continue
        for kw in node.keywords:
            if (
                kw.arg == "require_row_version"
                and isinstance(kw.value, ast.Constant)
                and kw.value.value is True
            ):
                return True
    return False


def main() -> None:
    violations: list[str] = []
    views_dir = _REPO_ROOT / "server" / "api"

    for view_file in sorted(views_dir.glob("views_*.py")):
        tree = ast.parse(view_file.read_text(encoding="utf-8"))
        for func in _iter_view_functions(tree):
            methods = _decorated_methods(func)
            if not methods or not (methods & _WRITE_METHODS):
                continue

            key = f"{view_file.name}:{func.name}"
            if key in _ALLOWLIST:
                continue

            call_names = _call_names(func)
            has_idem_guard = "check_idempotency" in call_names and "store_idempotency" in call_names
            has_cas_guard = _has_require_row_version(func)

            if methods & {"POST", "DELETE"} and not has_idem_guard:
                violations.append(
                    f"{key} -> mutating endpoint must use idempotency guard/check+store"
                )

            if methods & {"PUT", "PATCH"} and not has_cas_guard:
                violations.append(
                    f"{key} -> update endpoint must enforce CAS "
                    "via validate_payload(..., require_row_version=True)"
                )

    if violations:
        text = "\n".join(f" - {entry}" for entry in violations)
        raise SystemExit("verify_write_policies failed:\n" + text)

    print("verify_write_policies: OK")


if __name__ == "__main__":
    main()
