from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QMessageBox

from app.services.offline_account_scope import OfflineAccountScope
from app.services.offline_types import OfflineConflict, OfflineOperation
from app.views.dialogs import sync_issues_dialog as module

pytestmark = pytest.mark.ui


def _scope(suffix: str = "scope") -> OfflineAccountScope:
    return OfflineAccountScope(
        account_key=f"http://test|1|2|{suffix}",
        api_base="http://test",
        agency_id=1,
        user_id=2,
        account_dir=f"acct_{suffix}",
    )


def test_sync_issues_dialog_lists_conflicts_and_retries(
    monkeypatch: pytest.MonkeyPatch, qapp
) -> None:
    scope = _scope("retry")
    calls: list[tuple[str, object]] = []
    monkeypatch.setattr(module, "get_active_account_scope", lambda: scope)
    monkeypatch.setattr(
        module,
        "list_conflicts",
        lambda *, scope=None: [
            OfflineConflict(
                op_id="op-1",
                entity_type="client",
                local_id=-1,
                reason_code="sync_review_required",
                message="Needs review",
                created_at="2026-03-09T10:00:00+00:00",
            )
        ],
    )
    monkeypatch.setattr(
        module,
        "get_operation",
        lambda op_id, *, scope=None: OfflineOperation(
            op_id=op_id,
            account_key="acct",
            entity_type="client",
            op_type="create",
            local_id=-1,
            payload={},
        ),
    )
    monkeypatch.setattr(
        module,
        "update_operation_status",
        lambda op_id, status, *, scope=None: calls.append(("status", (op_id, status, scope))),
    )
    monkeypatch.setattr(
        module,
        "mark_projection_status",
        lambda entity_type, local_id, **kwargs: calls.append(
            ("projection", (entity_type, local_id, kwargs))
        ),
    )
    monkeypatch.setattr(
        module,
        "remove_conflict",
        lambda op_id, *, scope=None: calls.append(("remove", (op_id, scope))),
    )

    dialog = module.SyncIssuesDialog()
    dialog._table.selectRow(0)
    dialog._retry_selected()

    assert dialog._table.rowCount() == 1
    assert ("remove", ("op-1", scope)) in calls
    assert ("status", ("op-1", "pending", scope)) in calls
    assert any(call[0] == "projection" for call in calls)


def test_sync_issues_dialog_discard_calls_discard_operation(
    monkeypatch: pytest.MonkeyPatch, qapp
) -> None:
    scope = _scope("discard")
    calls: list[tuple[str, object]] = []
    monkeypatch.setattr(module, "get_active_account_scope", lambda: scope)
    monkeypatch.setattr(
        module,
        "list_conflicts",
        lambda *, scope=None: [
            OfflineConflict(
                op_id="op-2",
                entity_type="client",
                local_id=-2,
                reason_code="sync_review_required",
                message="Needs review",
                created_at="2026-03-09T10:00:00+00:00",
            )
        ],
    )
    monkeypatch.setattr(
        module,
        "remove_conflict",
        lambda op_id, *, scope=None: calls.append(("remove", (op_id, scope))),
    )
    monkeypatch.setattr(
        module,
        "discard_operation",
        lambda op_id, *, scope=None: calls.append(("discard", (op_id, scope))),
    )
    monkeypatch.setattr(
        module.QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )

    dialog = module.SyncIssuesDialog()
    dialog._table.selectRow(0)
    dialog._discard_selected()

    assert ("remove", ("op-2", scope)) in calls
    assert ("discard", ("op-2", scope)) in calls


def test_sync_issues_dialog_without_active_scope_shows_sign_in_message(
    monkeypatch: pytest.MonkeyPatch, qapp
) -> None:
    monkeypatch.setattr(module, "get_active_account_scope", lambda: None)

    dialog = module.SyncIssuesDialog()

    assert dialog._table.rowCount() == 0
    assert "Sign in" in dialog._summary.text()
    assert dialog._retry_btn.isEnabled() is False
    assert dialog._discard_btn.isEnabled() is False


def test_sync_issues_dialog_retries_media_conflict(monkeypatch: pytest.MonkeyPatch, qapp) -> None:
    scope = _scope("media-retry")
    calls: list[tuple[str, object]] = []
    monkeypatch.setattr(module, "get_active_account_scope", lambda: scope)
    monkeypatch.setattr(
        module,
        "list_conflicts",
        lambda *, scope=None: [
            OfflineConflict(
                op_id="media:q-1",
                entity_type="offer_photo",
                local_id=44,
                reason_code="media_review_required",
                message="Needs review",
                created_at="2026-03-09T10:00:00+00:00",
            )
        ],
    )
    monkeypatch.setattr(
        module,
        "retry_media_upload",
        lambda queue_id, *, scope=None: calls.append(("retry", (queue_id, scope))),
    )
    monkeypatch.setattr(
        module,
        "remove_conflict",
        lambda op_id, *, scope=None: calls.append(("remove", (op_id, scope))),
    )

    dialog = module.SyncIssuesDialog()
    dialog._table.selectRow(0)
    dialog._retry_selected()

    assert ("retry", ("q-1", scope)) in calls
    assert ("remove", ("media:q-1", scope)) in calls


def test_sync_issues_dialog_discards_media_conflict(monkeypatch: pytest.MonkeyPatch, qapp) -> None:
    scope = _scope("media-discard")
    calls: list[tuple[str, object]] = []
    monkeypatch.setattr(module, "get_active_account_scope", lambda: scope)
    monkeypatch.setattr(
        module,
        "list_conflicts",
        lambda *, scope=None: [
            OfflineConflict(
                op_id="media:q-2",
                entity_type="offer_photo",
                local_id=45,
                reason_code="media_review_required",
                message="Needs review",
                created_at="2026-03-09T10:00:00+00:00",
            )
        ],
    )
    monkeypatch.setattr(
        module,
        "remove_conflict",
        lambda op_id, *, scope=None: calls.append(("remove", (op_id, scope))),
    )
    monkeypatch.setattr(
        module,
        "discard_media_upload",
        lambda queue_id, *, scope=None: calls.append(("discard", (queue_id, scope))),
    )
    monkeypatch.setattr(
        module.QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )

    dialog = module.SyncIssuesDialog()
    dialog._table.selectRow(0)
    dialog._discard_selected()

    assert ("remove", ("media:q-2", scope)) in calls
    assert ("discard", ("q-2", scope)) in calls
