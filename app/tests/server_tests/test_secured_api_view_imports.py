from __future__ import annotations

import ast
from pathlib import Path

_REPO_ROOT = Path(__file__).parents[3]


def _load_tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def test_api_views_use_secured_decorator() -> None:
    for py_file in (_REPO_ROOT / "server" / "api").glob("views_*.py"):
        tree = _load_tree(py_file)
        for node in tree.body:
            if isinstance(node, ast.ImportFrom) and node.module == "rest_framework.decorators":
                names = {alias.name for alias in node.names}
                if py_file.name == "views_health.py":
                    # Allow the firewall verification view to use bare DRF api_view.
                    continue
                assert "api_view" not in names, (
                    f"{py_file} imports rest_framework.decorators.api_view directly; "
                    "use server.api.secured_view.secured_api_view instead."
                )
