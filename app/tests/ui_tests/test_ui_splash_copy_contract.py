from __future__ import annotations

import pytest

from app.tests.ui_tests._ui_contract_helpers import (
    contains_term,
    load_ui_copy_contract_module,
    read_file,
    tr_strings,
)

pytestmark = pytest.mark.ui


def test_splash_messages_avoid_technical_terms() -> None:
    contract = load_ui_copy_contract_module()
    forbidden = tuple(str(term).lower() for term in contract.FORBIDDEN_UI_TERMS)
    content = read_file("app/widgets/splash_startup.py")
    violations: list[str] = []
    for label in tr_strings(content):
        lowered = label.lower()
        for term in forbidden:
            if contains_term(lowered, term):
                violations.append(label)
                break
    assert not violations, f"Splash copy includes forbidden terms: {violations}"
