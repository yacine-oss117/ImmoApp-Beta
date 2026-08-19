from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QDialog

from app.services import onboarding_analytics
from app.widgets import quick_start_dialog as module

pytestmark = pytest.mark.ui


def test_quick_start_dialog_is_resizable_with_dialog_minimums(qapp) -> None:
    dialog = module.QuickStartDialog()

    assert dialog.minimumWidth() == 500
    assert dialog.minimumHeight() == 360
    assert dialog.maximumWidth() > dialog.minimumWidth()
    assert dialog.maximumHeight() > dialog.minimumHeight()


def test_run_quick_start_flow_marks_seen_and_dispatches_choice(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    qapp,
) -> None:
    monkeypatch.setenv("IMMOAPP_APPDATA_ROOT", str(tmp_path))
    seen: list[str] = []

    class _FakeDialog:
        def __init__(self, _parent=None) -> None:
            self.choice = module.CHOICE_JOIN

        def exec(self) -> int:
            return int(QDialog.DialogCode.Accepted)

    monkeypatch.setattr(module, "QuickStartDialog", _FakeDialog)
    monkeypatch.setattr(module, "_run_choice_flow", lambda choice, parent=None: seen.append(choice))

    result = module.run_quick_start_flow()

    assert result == module.CHOICE_JOIN
    assert seen == [module.CHOICE_JOIN]
    assert onboarding_analytics.has_seen_quick_start() is True


def test_run_quick_start_flow_skips_when_already_seen(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    qapp,
) -> None:
    monkeypatch.setenv("IMMOAPP_APPDATA_ROOT", str(tmp_path))
    onboarding_analytics.mark_quick_start_seen(seen=True)

    class _ShouldNotCreate:
        def __init__(self, _parent=None) -> None:  # pragma: no cover
            raise AssertionError("QuickStartDialog should not be created after first run")

    monkeypatch.setattr(module, "QuickStartDialog", _ShouldNotCreate)
    result = module.run_quick_start_flow()

    assert result == module.CHOICE_SIGN_IN
