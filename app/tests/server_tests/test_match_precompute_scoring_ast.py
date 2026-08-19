"""
Anti-regression checks for precomputed pair scoring path.
"""

from __future__ import annotations

import ast
from pathlib import Path

_TASKS_FILE = Path(__file__).parents[3] / "server" / "api" / "match_pairs_compute.py"


def _tree() -> ast.Module:
    return ast.parse(_TASKS_FILE.read_text(encoding="utf-8"))


def test_precompute_uses_domain_calculate_score() -> None:
    tree = _tree()
    source = _TASKS_FILE.read_text(encoding="utf-8")
    assert "compute_match_artifacts_for_demandes" in source
    assert "rebuild_match_artifacts_for_demandes" in source
    assert "calculate_score" not in source
    assert "heapq" not in source

    calls: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                calls.add(func.id)
            elif isinstance(func, ast.Attribute):
                calls.add(func.attr)
    assert "compute_match_artifacts_for_demandes" in calls
    assert "rebuild_match_artifacts_for_demandes" in calls
