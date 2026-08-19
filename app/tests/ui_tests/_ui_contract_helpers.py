from __future__ import annotations

import ast
import importlib.util
import re
from pathlib import Path


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def load_ui_copy_contract_module():
    root = repo_root()
    path = root / "app" / "ui" / "ui_copy_contract.py"
    spec = importlib.util.spec_from_file_location("ui_copy_contract_test", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load UI copy contract module: {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def read_file(rel_path: str) -> str:
    return (repo_root() / rel_path).read_text(encoding="utf-8")


def tr_strings(content: str) -> list[str]:
    tree = ast.parse(content)
    values: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Name) or node.func.id != "_TR":
            continue
        if not node.args:
            continue
        first = node.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            values.append(first.value)
    return values


def contains_term(text: str, term: str) -> bool:
    escaped = re.escape(term)
    if re.fullmatch(r"[A-Za-z0-9 _-]+", term):
        return bool(re.search(rf"\b{escaped}\b", text))
    return term in text
