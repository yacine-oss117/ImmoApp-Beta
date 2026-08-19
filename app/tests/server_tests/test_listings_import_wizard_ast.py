from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _find_class(module: ast.Module, name: str) -> ast.ClassDef:
    for node in module.body:
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
    raise AssertionError(f"Class {name} not found")


def test_listings_ui_has_import_button_field_and_construction() -> None:
    ui_module = _parse(ROOT / "app" / "views" / "listings_v2_ui.py")
    ui_class = _find_class(ui_module, "ListingsTabUi")
    field_names = {n.target.id for n in ui_class.body if isinstance(n, ast.AnnAssign)}
    assert "import_btn" in field_names, "ListingsTabUi must expose import_btn"

    found_btn_creation = False
    for node in ast.walk(ui_module):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == "import_btn":
                    found_btn_creation = True
    assert found_btn_creation, "build_listings_tab_ui must create import_btn"


def test_listings_tab_connects_import_button_to_wizard() -> None:
    listings_path = ROOT / "app" / "views" / "listings_v2.py"
    source = listings_path.read_text(encoding="utf-8")
    module = ast.parse(source, filename=str(listings_path))
    cls = _find_class(module, "ListingsTabV2")

    has_connect = "self._ui.import_btn.clicked.connect(self._open_import_wizard)" in source
    has_open_call = False
    has_refresh_call = False

    for node in ast.walk(cls):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "open_import_wizard"
        ):
            has_open_call = True

        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "self"
            and node.func.attr == "refresh_table"
        ):
            has_refresh_call = True

    assert has_connect, "ListingsTabV2 must connect _ui.import_btn"
    assert has_open_call, "ListingsTabV2 import handler must open import wizard"
    assert has_refresh_call, "ListingsTabV2 import handler must refresh table after wizard"
