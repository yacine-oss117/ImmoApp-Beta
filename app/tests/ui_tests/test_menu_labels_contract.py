from __future__ import annotations

import pytest

from app.tests.ui_tests._ui_contract_helpers import load_ui_copy_contract_module, read_file

pytestmark = pytest.mark.ui


def test_required_menu_labels_are_present() -> None:
    contract = load_ui_copy_contract_module()
    content = read_file("app/main_window_menus.py")
    missing = [label for label in contract.REQUIRED_MENU_LABELS if f'_TR("{label}")' not in content]
    assert not missing, f"Missing menu labels: {', '.join(missing)}"
