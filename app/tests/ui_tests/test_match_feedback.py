from __future__ import annotations

from collections.abc import Callable

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QWidget

from app.views import match_actions as actions_module
from app.views.match_tab_actions import MatchTabActionsMixin
from app.views.match_ui import build_match_ui
from app.widgets.user_feedback import UserFacingMessage

pytestmark = pytest.mark.ui


def _capture_messages() -> tuple[
    list[tuple[UserFacingMessage, int | None]],
    Callable[[UserFacingMessage, int | None], None],
]:
    messages: list[tuple[UserFacingMessage, int | None]] = []

    def _collector(message: UserFacingMessage, auto_dismiss_ms: int | None = None) -> None:
        messages.append((message, auto_dismiss_ms))

    return messages, _collector


def test_build_match_ui_exposes_banner_and_flexible_workspace_widths(qapp) -> None:
    host = QWidget()
    ui = build_match_ui(
        parent=host,
        on_client_search=lambda _text: None,
        on_filter_changed=lambda: None,
        on_run_match=lambda: None,
        on_save_settings=lambda: None,
    )

    assert ui.notice_banner.parent() is host
    assert host.layout().indexOf(ui.notice_banner) == 0
    assert ui.controls_card.minimumWidth() == 300
    assert ui.controls_card.maximumWidth() > 1000
    assert ui.scroll_area.minimumHeight() == 240


def test_match_run_without_client_uses_inline_feedback() -> None:
    messages, collector = _capture_messages()

    class _Dropdown:
        @staticmethod
        def get_selected_client_id() -> int | None:
            return None

    class _DummyTab:
        _dropdown_controller = _Dropdown()

        def _show_feedback(
            self, message: UserFacingMessage, auto_dismiss_ms: int | None = None
        ) -> None:
            collector(message, auto_dismiss_ms)

        def _emit_feedback(
            self, message: UserFacingMessage, auto_dismiss_ms: int | None = None
        ) -> None:
            collector(message, auto_dismiss_ms)

    MatchTabActionsMixin._on_run_match_clicked(_DummyTab())

    assert messages
    assert messages[0][0].severity == "info"
    assert "choose a client first" in messages[0][0].message.lower()
    assert messages[0][1] == 5000


def test_schedule_visit_uses_feedback_callback_instead_of_popup(
    monkeypatch: pytest.MonkeyPatch, qapp
) -> None:
    messages, collector = _capture_messages()
    created: list[dict[str, object]] = []
    refreshed: list[str] = []

    class _Dialog:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def exec(self) -> int:
            return 1

        @staticmethod
        def get_visit_data() -> dict[str, object]:
            return {
                "client_id": 1,
                "listing_id": 2,
                "scheduled_date": "2026-03-16",
                "scheduled_time": "10:00",
                "notes": "",
                "status": "scheduled",
            }

    monkeypatch.setattr(actions_module, "VisitDialog", _Dialog)
    monkeypatch.setattr(
        actions_module, "create_visit", lambda payload: created.append(dict(payload))
    )
    monkeypatch.setattr(
        actions_module.QMessageBox,
        "information",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("unexpected popup")),
    )
    monkeypatch.setattr(
        actions_module.QMessageBox,
        "warning",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("unexpected popup")),
    )

    actions_module.schedule_visit(
        parent=QWidget(),
        client_id=1,
        listing_id=2,
        location="Hydra",
        refresh_crm_cb=lambda: refreshed.append("ok"),
        feedback_cb=collector,
    )

    assert created and created[0]["client_id"] == 1
    assert refreshed == ["ok"]
    assert messages
    assert messages[-1][0].severity == "success"
    assert "added to follow-up" in messages[-1][0].message.lower()
    assert messages[-1][1] == 5000


def test_schedule_visit_invalid_selection_uses_friendly_warning(qapp) -> None:
    messages, collector = _capture_messages()

    actions_module.schedule_visit(
        parent=QWidget(),
        client_id="bad",
        listing_id=2,
        location="Hydra",
        refresh_crm_cb=None,
        feedback_cb=collector,
    )

    assert messages
    assert messages[0][0].severity == "warning"
    assert "no longer valid" in messages[0][0].message.lower()
