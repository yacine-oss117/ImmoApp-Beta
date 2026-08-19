from __future__ import annotations

from collections.abc import Callable

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QPushButton

from app.models import Contract
from app.views import crm_contracts as contracts_module
from app.views import crm_visits as visits_module
from app.views.dialogs.contract_edit_dialog import ContractEditDialog
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


def test_visits_refresh_failure_uses_inline_feedback(monkeypatch: pytest.MonkeyPatch, qapp) -> None:
    messages, collector = _capture_messages()

    def _raise(*, status=None):
        raise RuntimeError("backend down")

    monkeypatch.setattr(visits_module, "fetch_visits", _raise)
    monkeypatch.setattr(
        visits_module.QMessageBox,
        "warning",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("unexpected popup")),
    )

    visits_module.VisitsWidget(feedback_cb=collector)

    assert messages
    assert "couldn't load visits" in messages[0][0].title.lower()
    assert messages[0][0].severity == "error"


def test_visits_complete_success_uses_inline_feedback(
    monkeypatch: pytest.MonkeyPatch, qapp
) -> None:
    messages, collector = _capture_messages()
    updates: list[tuple[object, dict[str, object]]] = []

    monkeypatch.setattr(visits_module, "fetch_visits", lambda status=None: [])
    monkeypatch.setattr(
        visits_module,
        "update_visit",
        lambda visit_id, payload: updates.append((visit_id, dict(payload))),
    )
    monkeypatch.setattr(
        visits_module.QMessageBox,
        "information",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("unexpected popup")),
    )

    widget = visits_module.VisitsWidget(feedback_cb=collector)
    button = QPushButton()
    button.setProperty("visit_id", 7)
    button.setProperty("row_version", 3)
    button.clicked.connect(widget._complete_visit)

    button.click()

    assert updates == [(7, {"status": "completed", "row_version": 3})]
    assert messages
    assert messages[-1][0].severity == "success"
    assert "visit marked as completed" in messages[-1][0].message.lower()
    assert messages[-1][1] == 5000


def test_contracts_refresh_failure_uses_inline_feedback(
    monkeypatch: pytest.MonkeyPatch, qapp
) -> None:
    messages, collector = _capture_messages()

    def _raise(*, status=None, contract_type=None):
        raise RuntimeError("backend down")

    monkeypatch.setattr(contracts_module, "fetch_contracts", _raise)
    monkeypatch.setattr(
        contracts_module.QMessageBox,
        "warning",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("unexpected popup")),
    )

    contracts_module.ContractsWidget(feedback_cb=collector)

    assert messages
    assert "couldn't load contracts" in messages[0][0].title.lower()
    assert messages[0][0].severity == "error"


def test_contracts_print_success_uses_inline_feedback(
    monkeypatch: pytest.MonkeyPatch, qapp
) -> None:
    messages, collector = _capture_messages()
    printed: list[object] = []

    monkeypatch.setattr(
        contracts_module, "fetch_contracts", lambda status=None, contract_type=None: []
    )
    monkeypatch.setattr(
        "app.services.crm_repository.print_contract",
        lambda contract_id: printed.append(contract_id),
    )
    monkeypatch.setattr(
        contracts_module.QMessageBox,
        "information",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("unexpected popup")),
    )

    widget = contracts_module.ContractsWidget(feedback_cb=collector)
    button = QPushButton()
    button.setProperty("contract_id", 12)
    button.clicked.connect(widget._print_contract)

    button.click()

    assert printed == [12]
    assert messages
    assert messages[-1][0].severity == "success"
    assert "pending signature" in messages[-1][0].message.lower()
    assert messages[-1][1] == 5000


def test_contract_edit_dialog_hydrates_and_round_trips_row_version(qapp) -> None:
    contract = Contract(
        id=12,
        client_id=3,
        listing_id=4,
        contract_type="rent",
        status="draft",
        start_date="2026-06-01",
        end_date="2027-06-01",
        amount=175_000,
        deposit=50_000,
        terms="existing terms",
        notes="existing notes",
        row_version=7,
    )

    dialog = ContractEditDialog(contract)

    assert dialog.objectName() == "contractEditDialog"
    assert dialog.amount.value() == 175_000
    assert dialog.deposit.value() == 50_000
    assert dialog.start_date.date().toString("yyyy-MM-dd") == "2026-06-01"
    assert dialog.end_date.date().toString("yyyy-MM-dd") == "2027-06-01"
    assert dialog.terms.toPlainText() == "existing terms"
    assert dialog.notes.toPlainText() == "existing notes"

    dialog.amount.setValue(185_000)
    dialog.deposit.setValue(60_000)
    dialog.terms.setPlainText("edited terms")
    dialog.notes.setPlainText("edited notes")
    dialog.accept_contract()

    assert dialog.get_contract_data() == {
        "row_version": 7,
        "amount": 185_000,
        "deposit": 60_000,
        "start_date": "2026-06-01",
        "end_date": "2027-06-01",
        "terms": "edited terms",
        "notes": "edited notes",
    }


def test_contract_edit_dialog_does_not_invent_buy_end_date(qapp) -> None:
    contract = Contract(
        id=13,
        client_id=3,
        listing_id=4,
        contract_type="buy",
        status="draft",
        start_date="2026-06-01",
        end_date="",
        amount=22_000_000,
        deposit=0,
        terms="buy terms",
        notes="buy notes",
        row_version=8,
    )

    dialog = ContractEditDialog(contract)
    dialog.notes.setPlainText("edited buy notes")
    dialog.accept_contract()

    payload = dialog.get_contract_data()
    assert payload is not None
    assert payload["row_version"] == 8
    assert payload["end_date"] is None
    assert payload["notes"] == "edited buy notes"


def test_contracts_edit_action_uses_row_version_update_payload(
    monkeypatch: pytest.MonkeyPatch, qapp
) -> None:
    messages, collector = _capture_messages()
    contract = Contract(
        id=44,
        client_id=3,
        listing_id=4,
        contract_type="rent",
        status="draft",
        amount=175_000,
        deposit=50_000,
        terms="existing terms",
        notes="existing notes",
        row_version=5,
    )
    updates: list[tuple[int, dict[str, object]]] = []

    class FakeContractEditDialog:
        def __init__(self, incoming: Contract, parent=None) -> None:
            assert incoming is contract

        def exec(self) -> bool:
            return True

        def get_contract_data(self) -> dict[str, object]:
            return {"row_version": 5, "amount": 185_000, "notes": "edited"}

    monkeypatch.setattr(
        contracts_module,
        "fetch_contracts",
        lambda status=None, contract_type=None: [contract],
    )
    monkeypatch.setattr(contracts_module, "ContractEditDialog", FakeContractEditDialog)
    monkeypatch.setattr(
        contracts_module,
        "update_contract",
        lambda contract_id, payload: updates.append((int(contract_id), dict(payload))),
    )

    widget = contracts_module.ContractsWidget(feedback_cb=collector)
    button = QPushButton()
    button.setProperty("contract_id", 44)
    button.clicked.connect(widget._edit_contract)
    button.click()

    assert updates == [(44, {"row_version": 5, "amount": 185_000, "notes": "edited"})]
    assert messages
    assert messages[-1][0].severity == "success"
