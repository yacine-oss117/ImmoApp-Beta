from __future__ import annotations

import pytest

from app.views.dialogs import notifications_dialog as module

pytestmark = pytest.mark.ui


def _fixture_items() -> list[dict[str, object]]:
    return [
        {
            "id": 1,
            "type": "import.completed",
            "title": "Import done",
            "body": "Your import is finished.",
            "is_read": False,
            "created_at": "2026-03-02T10:00:00Z",
        },
        {
            "id": 2,
            "type": "security.alert",
            "title": "Sign-in warning",
            "body": "We saw unusual sign-in attempts.",
            "is_read": False,
            "created_at": "2026-03-02T09:00:00Z",
        },
        {
            "id": 3,
            "type": "sync.failed",
            "title": "Sync failed",
            "body": "Please try again.",
            "is_read": True,
            "created_at": "2026-03-02T08:00:00Z",
        },
        {
            "id": 4,
            "type": "digest.info",
            "title": "Daily update",
            "body": "Everything looks good.",
            "is_read": True,
            "created_at": "2026-03-02T07:00:00Z",
        },
    ]


def test_notifications_dialog_renders_card_list_and_filters(monkeypatch, qapp) -> None:
    monkeypatch.setattr(
        module,
        "fetch_notifications_page",
        lambda limit=200, cursor=None: (_fixture_items(), 4, None),
    )
    monkeypatch.setattr(
        module, "fetch_notifications", lambda limit=500, offset=0: (_fixture_items(), 4)
    )
    monkeypatch.setattr(module, "fetch_unread_count", lambda: 2)

    dialog = module.NotificationsDialog()
    qapp.processEvents()

    assert dialog._list.count() == 4  # noqa: SLF001 - UI contract assertion
    first_widget = dialog._list.itemWidget(dialog._list.item(0))  # noqa: SLF001
    assert first_widget is not None
    assert first_widget.objectName() in {"NotificationCard", "NotificationCard_unread"}

    dialog._filter_buttons["warning"].click()  # noqa: SLF001
    qapp.processEvents()
    assert dialog._list.count() == 1  # noqa: SLF001

    dialog._filter_buttons["error"].click()  # noqa: SLF001
    qapp.processEvents()
    assert dialog._list.count() == 1  # noqa: SLF001

    dialog._filter_buttons["unread"].click()  # noqa: SLF001
    qapp.processEvents()
    assert dialog._list.count() == 2  # noqa: SLF001

    dialog.close()


def test_notifications_dialog_empty_state(monkeypatch, qapp) -> None:
    monkeypatch.setattr(
        module, "fetch_notifications_page", lambda limit=200, cursor=None: ([], 0, None)
    )
    monkeypatch.setattr(module, "fetch_notifications", lambda limit=500, offset=0: ([], 0))
    monkeypatch.setattr(module, "fetch_unread_count", lambda: 0)

    dialog = module.NotificationsDialog()
    qapp.processEvents()

    assert dialog._list.isHidden() is True  # noqa: SLF001
    assert dialog._empty_state.isHidden() is False  # noqa: SLF001
    assert "No notifications yet." in dialog._empty_text.text()  # noqa: SLF001

    dialog.close()
