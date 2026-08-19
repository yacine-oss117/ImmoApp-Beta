from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from app.views.dialogs import user_management_dialog as module  # noqa: E402

pytestmark = pytest.mark.ui


def test_user_management_refresh_runs_in_background(monkeypatch: pytest.MonkeyPatch, qapp) -> None:
    calls = {"worker": 0, "users": 0, "invites": 0}

    def _fake_list_users(*, include_inactive: bool = False, role: str | None = None):
        _ = include_inactive, role
        calls["users"] += 1
        return []

    def _fake_list_user_invites():
        calls["invites"] += 1
        return []

    def _fake_run_background_result(func, on_success, on_error=None, *args, **kwargs):
        _ = func, on_success, on_error, args, kwargs
        calls["worker"] += 1

    monkeypatch.setattr(module, "list_users", _fake_list_users)
    monkeypatch.setattr(module, "list_user_invites", _fake_list_user_invites)
    monkeypatch.setattr(module, "run_background_result", _fake_run_background_result)

    dialog = module.UserManagementDialog()
    try:
        assert calls["worker"] >= 1
        assert calls["users"] == 0
        assert calls["invites"] == 0
    finally:
        dialog.close()
