from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
import re

import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

_contract_path = REPO_ROOT / "app" / "ui" / "ui_copy_contract.py"
_spec = importlib.util.spec_from_file_location("ui_copy_contract_contract", _contract_path)
if _spec is None or _spec.loader is None:
    raise RuntimeError(f"Unable to load contract file: {_contract_path}")
_contract = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_contract)

CONTRACT_UI_FILES = _contract.CONTRACT_UI_FILES
FORBIDDEN_UI_TERMS = _contract.FORBIDDEN_UI_TERMS
NEW_UI_MODULES_WITH_ALL = _contract.NEW_UI_MODULES_WITH_ALL
REQUIRED_MENU_LABELS = _contract.REQUIRED_MENU_LABELS
REQUIRED_TAB_LABELS = _contract.REQUIRED_TAB_LABELS
TECHNICAL_ID_PATTERNS = _contract.TECHNICAL_ID_PATTERNS


def _read(rel_path: str) -> str:
    return (REPO_ROOT / rel_path).read_text(encoding="utf-8")


def _translated_strings(content: str) -> list[str]:
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return []
    values: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if not isinstance(fn, ast.Name) or fn.id != "_TR":
            continue
        if not node.args:
            continue
        first = node.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            values.append(first.value)
    return values


def _has_all_export(content: str) -> bool:
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return False
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name) or target.id != "__all__":
            continue
        return isinstance(node.value, (ast.List, ast.Tuple))
    return False


def _verify_forbidden_terms(violations: list[str]) -> None:
    forbidden = tuple(term.lower() for term in FORBIDDEN_UI_TERMS)
    technical = tuple(term.lower() for term in TECHNICAL_ID_PATTERNS)

    for rel in CONTRACT_UI_FILES:
        path = REPO_ROOT / rel
        if not path.exists():
            continue
        content = _read(rel)
        strings = _translated_strings(content)
        for label in strings:
            low = label.lower()
            for term in forbidden:
                if _contains_term(low, term):
                    violations.append(f"{rel}: forbidden UI term in _TR string -> {label!r}")
            for term in technical:
                if _contains_term(low, term):
                    violations.append(f"{rel}: technical ID text in _TR string -> {label!r}")

        if 'strftime("%Y-%m-%d' in content or "isoformat(" in content:
            violations.append(f"{rel}: raw ISO datetime formatting found")


def _verify_required_labels(violations: list[str]) -> None:
    menu_content = _read("app/main_window_menus.py")
    for label in REQUIRED_MENU_LABELS:
        needle = f'_TR("{label}")'
        if needle not in menu_content:
            violations.append(f"app/main_window_menus.py: missing required label {label!r}")

    tab_content = _read("app/main_window_tabs.py")
    for label in REQUIRED_TAB_LABELS:
        needle = f'_TR("{label}")'
        if needle not in tab_content:
            violations.append(f"app/main_window_tabs.py: missing required label {label!r}")


def _verify_module_exports(violations: list[str]) -> None:
    for rel in NEW_UI_MODULES_WITH_ALL:
        path = REPO_ROOT / rel
        if not path.exists():
            violations.append(f"{rel}: missing required module")
            continue
        content = _read(rel)
        if not _has_all_export(content):
            violations.append(f"{rel}: missing __all__ export list")


def _contains_term(text: str, term: str) -> bool:
    escaped = re.escape(term)
    if re.fullmatch(r"[a-z0-9 _-]+", term):
        pattern = re.compile(rf"\b{escaped}\b")
        return bool(pattern.search(text))
    return term in text


def main() -> int:
    violations: list[str] = []
    _verify_forbidden_terms(violations)
    _verify_required_labels(violations)
    _verify_module_exports(violations)

    if violations:
        print("[verify_ui_copy_contract] FAIL")
        for issue in violations:
            print(" -", issue)
        return 1
    print("[verify_ui_copy_contract] OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
