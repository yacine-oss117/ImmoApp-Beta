from __future__ import annotations

import ast
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_API_DIR = _REPO_ROOT / "server" / "api"
_VIEW_FILES = sorted(_API_DIR.glob("views_*.py"))


def _is_error_call(node: ast.Call) -> bool:
    func = node.func
    return isinstance(func, ast.Name) and func.id == "error"


def _contains_exception_value(node: ast.AST) -> bool:
    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Name) and node.func.id in {
            "safe_error_message",
            "safe_forbidden_message",
            "safe_not_found_message",
        }:
            return False
        if isinstance(node.func, ast.Name) and node.func.id == "str":
            return True
    if isinstance(node, ast.Name) and node.id in {"exc", "e", "err", "exception"}:
        return True
    if isinstance(node, ast.JoinedStr):
        for value in node.values:
            if isinstance(value, ast.FormattedValue):
                formatted = value.value
                if isinstance(formatted, ast.Name) and formatted.id in {
                    "exc",
                    "e",
                    "err",
                    "exception",
                }:
                    return True
    for child in ast.iter_child_nodes(node):
        if _contains_exception_value(child):
            return True
    return False


def _check_file(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    violations: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not _is_error_call(node):
            continue
        if not node.args:
            continue
        first_arg = node.args[0]
        if _contains_exception_value(first_arg):
            violations.append(
                f"{path}:{node.lineno}: do not return raw exception text via error(...)."
            )
    return violations


def main() -> None:
    violations: list[str] = []
    for view_file in _VIEW_FILES:
        violations.extend(_check_file(view_file))
    if violations:
        raise SystemExit("verify_no_exception_leakage: violations found\n" + "\n".join(violations))
    print("verify_no_exception_leakage: OK")


if __name__ == "__main__":
    main()
