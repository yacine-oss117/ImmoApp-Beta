from __future__ import annotations

import pytest

from app.tests.ui_tests._ui_contract_helpers import load_ui_copy_contract_module, read_file

pytestmark = pytest.mark.ui


def test_ui_contract_files_use_translation_helper() -> None:
    contract = load_ui_copy_contract_module()
    violations: list[str] = []
    for rel in contract.CONTRACT_UI_FILES:
        content = read_file(rel)
        if "_TR(" not in content:
            violations.append(rel)
    assert not violations, f"Missing _TR usage in: {', '.join(violations)}"
