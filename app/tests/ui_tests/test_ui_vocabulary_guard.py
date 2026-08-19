from __future__ import annotations

import pytest

from app.tests.ui_tests._ui_contract_helpers import (
    contains_term,
    load_ui_copy_contract_module,
    read_file,
    tr_strings,
)

pytestmark = pytest.mark.ui


def test_ui_forbidden_terms_absent_from_user_strings() -> None:
    contract = load_ui_copy_contract_module()
    forbidden = tuple(str(term).lower() for term in contract.FORBIDDEN_UI_TERMS)
    violations: list[str] = []
    for rel in contract.CONTRACT_UI_FILES:
        content = read_file(rel)
        for label in tr_strings(content):
            lowered = label.lower()
            for term in forbidden:
                if contains_term(lowered, term):
                    violations.append(f"{rel}: {label!r}")
                    break
    assert not violations, "\n".join(violations)
