"""
Guardrails: enqueue_rebuild_* must not be called inside DB transactions.

Calling enqueue inside a transaction risks queuing work for changes that
may roll back. This AST check enforces enqueue-after-commit discipline.
"""

from __future__ import annotations

import ast
from pathlib import Path

_REPO_ROOT = Path(__file__).parents[3]
_SERVICES_DIR = _REPO_ROOT / "server" / "services"

_ENQUEUE_NAMES = {
    "enqueue_rebuild_demande_pairs",
    "enqueue_rebuild_client_pairs",
    "enqueue_rebuild_offer_pairs",
    "enqueue_rebuild_wilaya_pairs",
}


def _is_transaction_context(expr: ast.AST) -> bool:
    if not isinstance(expr, ast.Call):
        return False
    func = expr.func
    if isinstance(func, ast.Attribute) and func.attr == "transaction":
        return True
    return False


class _EnqueueVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.violations: list[tuple[int, str]] = []
        self._txn_depth = 0
        self._on_commit_depth = 0

    def visit_With(self, node: ast.With) -> None:
        enters_txn = any(_is_transaction_context(item.context_expr) for item in node.items)
        if enters_txn:
            self._txn_depth += 1
        self.generic_visit(node)
        if enters_txn:
            self._txn_depth -= 1

    def visit_Call(self, node: ast.Call) -> None:
        name = _call_name(node)
        if self._txn_depth > 0 and self._on_commit_depth == 0:
            if name in _ENQUEUE_NAMES:
                self.violations.append((node.lineno, name))

        if name == "on_commit":
            # Calls wrapped in uow.on_commit(...) are allowed because they only run post-commit.
            self.visit(node.func)
            self._on_commit_depth += 1
            for arg in node.args:
                self.visit(arg)
            for keyword in node.keywords:
                self.visit(keyword.value)
            self._on_commit_depth -= 1
            return

        self.generic_visit(node)


def _call_name(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _iter_py_files() -> list[Path]:
    return [path for path in _SERVICES_DIR.rglob("*.py") if path.is_file()]


def test_enqueue_calls_outside_transaction() -> None:
    violations: list[str] = []
    for path in _iter_py_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        visitor = _EnqueueVisitor()
        visitor.visit(tree)
        for lineno, name in visitor.violations:
            violations.append(f"{path}:{lineno} {name}")
    assert not violations, "enqueue_* called inside transaction:\n" + "\n".join(violations)
