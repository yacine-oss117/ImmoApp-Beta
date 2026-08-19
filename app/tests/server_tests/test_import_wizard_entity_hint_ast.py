from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _assert_hint(path: Path, expected_hint: str) -> None:
    module = _parse(path)
    for node in ast.walk(module):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "open_import_wizard"
        ):
            for kw in node.keywords:
                if kw.arg == "entity_type_hint" and isinstance(kw.value, ast.Constant):
                    assert kw.value.value == expected_hint
                    return
    raise AssertionError(
        f"open_import_wizard call with entity_type_hint={expected_hint} not found in {path}"
    )


def test_clients_tab_import_hint_is_client() -> None:
    _assert_hint(ROOT / "app" / "views" / "clients_v2.py", "client")


def test_listings_tab_import_hint_is_listing() -> None:
    _assert_hint(ROOT / "app" / "views" / "listings_v2.py", "listing")
