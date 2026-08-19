from __future__ import annotations

import pytest

from app.tests.ui_tests._ui_contract_helpers import load_ui_copy_contract_module, read_file

pytestmark = pytest.mark.ui


def test_ui_contract_files_avoid_raw_iso_formatting() -> None:
    contract = load_ui_copy_contract_module()
    violations: list[str] = []
    for rel in contract.CONTRACT_UI_FILES:
        content = read_file(rel)
        if 'strftime("%Y-%m-%d' in content or "isoformat(" in content:
            violations.append(rel)
    assert not violations, f"Raw ISO formatting found in: {', '.join(violations)}"
