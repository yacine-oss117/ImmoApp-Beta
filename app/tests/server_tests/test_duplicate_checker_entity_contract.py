from __future__ import annotations

import pytest

from server.services.duplicate_checker import DatabaseDuplicateChecker


def test_duplicate_checker_rejects_unknown_entity_type() -> None:
    checker = DatabaseDuplicateChecker()
    with pytest.raises(ValueError):
        checker._lookup_phones(["0555123456"], "unknown", session=object())
