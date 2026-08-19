"""
Targeted tests for MatchTab behavior that do not require a live UI.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

pytest.importorskip("PySide6")

from app.views.match_tab import MatchTab  # noqa: E402

pytestmark = pytest.mark.ui


@dataclass
class DummyMatchResult:
    client_id: int


class DummyResultsController:
    def __init__(self) -> None:
        self.full_count: int | None = None

    def update_full_count(self, count: int) -> None:
        self.full_count = count


class DummyDropdownController:
    def __init__(self) -> None:
        self.synced: list[tuple[int, int]] = []

    def sync_match_count(self, client_id: int, count: int) -> None:
        self.synced.append((client_id, count))


def test_maybe_refresh_dirty_counts_marks_clean_and_recomputes() -> None:
    class DummyTab:
        def __init__(self) -> None:
            self._match_counts_dirty_flag = True
            self.called = False

        def mark_all_dirty(self) -> None:
            self.called = True

    dummy = DummyTab()

    MatchTab._maybe_refresh_dirty_counts(dummy)

    assert dummy._match_counts_dirty_flag is False
    assert dummy.called is True


def test_on_full_count_ready_updates_only_for_current_client() -> None:
    class DummyTab:
        def __init__(self) -> None:
            self._last_match_result = DummyMatchResult(client_id=12)
            self._results_controller = DummyResultsController()
            self._dropdown_controller = DummyDropdownController()

    dummy = DummyTab()

    MatchTab._on_full_count_ready(dummy, 12, 7)
    assert dummy._results_controller.full_count == 7
    assert dummy._dropdown_controller.synced == [(12, 7)]

    dummy._results_controller.full_count = None
    dummy._dropdown_controller.synced.clear()

    MatchTab._on_full_count_ready(dummy, 99, 10)
    assert dummy._results_controller.full_count is None
    assert dummy._dropdown_controller.synced == []
