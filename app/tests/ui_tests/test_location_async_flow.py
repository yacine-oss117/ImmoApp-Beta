from __future__ import annotations

from collections.abc import Callable

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QLabel, QWidget

from app.widgets import location_form_helpers as helpers
from app.widgets.demande_form import DemandeForm
from app.widgets.location_multi_select import LocationMultiSelect
from app.widgets.offer_form import OfferForm

pytestmark = pytest.mark.ui


def _drain_events(qapp, rounds: int = 4) -> None:
    for _ in range(rounds):
        qapp.processEvents()


def _flush_deferred_deletes(qapp) -> None:
    qapp.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qapp.processEvents()


def _prime_locations(_parent: QWidget, on_locations, **_kwargs):
    locations = ["Hydra, Alger", "Cheraga, Alger"]
    on_locations(list(locations))
    return list(locations)


def test_add_location_async_emits_success(monkeypatch: pytest.MonkeyPatch, qapp) -> None:
    monkeypatch.setattr(helpers, "add_location", lambda _name: True)

    def _run_background_result(fn, on_result, on_error) -> None:
        try:
            on_result(fn())
        except Exception as exc:  # pragma: no cover - success-path fake
            on_error(exc)

    monkeypatch.setattr(helpers, "run_background_result", _run_background_result)

    parent = QWidget()
    success: list[str] = []
    errors: list[str] = []

    result = helpers.add_location_with_wilaya_async(
        parent,
        "Hydra",
        "Alger",
        on_success=lambda name: success.append(name),
        on_error=lambda message: errors.append(message),
    )
    _drain_events(qapp)

    assert result == "Hydra, Alger"
    assert success == ["Hydra, Alger"]
    assert not errors
    parent.deleteLater()


def test_add_location_async_emits_error(monkeypatch: pytest.MonkeyPatch, qapp) -> None:
    def _raise(_name: str) -> bool:
        raise RuntimeError("boom")

    monkeypatch.setattr(helpers, "add_location", _raise)

    def _run_background_result(fn, on_result, on_error) -> None:
        try:
            on_result(fn())
        except Exception as exc:
            on_error(exc)

    monkeypatch.setattr(helpers, "run_background_result", _run_background_result)

    parent = QWidget()
    success: list[str] = []
    errors: list[str] = []

    _ = helpers.add_location_with_wilaya_async(
        parent,
        "Hydra",
        "Alger",
        on_success=lambda name: success.append(name),
        on_error=lambda message: errors.append(message),
    )
    _drain_events(qapp)

    assert not success
    assert errors and "Failed to save location." in errors[0]
    parent.deleteLater()


def test_add_location_async_ignores_success_after_parent_deleted(
    monkeypatch: pytest.MonkeyPatch, qapp
) -> None:
    captured_success: list[Callable[[bool], None]] = []

    def _run_background_result(_fn, on_result, _on_error) -> None:
        captured_success.append(on_result)

    monkeypatch.setattr(helpers, "run_background_result", _run_background_result)

    parent = QWidget()
    success: list[str] = []
    errors: list[str] = []

    result = helpers.add_location_with_wilaya_async(
        parent,
        "Hydra",
        "Alger",
        on_success=lambda name: success.append(name),
        on_error=lambda message: errors.append(message),
    )
    parent.deleteLater()
    _flush_deferred_deletes(qapp)

    assert result == "Hydra, Alger"
    assert len(captured_success) == 1
    captured_success[0](True)

    assert not success
    assert not errors


def test_location_multi_select_ignores_late_async_status_after_child_deleted(qapp) -> None:
    widget = LocationMultiSelect()
    status_label = widget.findChild(QLabel, "locationStatusLabel")
    assert status_label is not None

    status_label.deleteLater()
    _flush_deferred_deletes(qapp)

    widget.set_async_state("success", "Location saved.")
    widget.clear_async_state()
    widget.deleteLater()


def test_demande_form_add_location_uses_async_retry(monkeypatch: pytest.MonkeyPatch, qapp) -> None:
    monkeypatch.setattr("app.widgets.demande_form.prime_locations_non_blocking", _prime_locations)

    attempts = {"count": 0}

    def _fake_async(_parent, name: str, wilaya: str, *, on_success=None, on_error=None) -> str:
        attempts["count"] += 1
        full_name = helpers.normalize_location_with_wilaya(name, wilaya)
        if attempts["count"] == 1:
            if on_error is not None:
                on_error("temporary failure")
        elif on_success is not None:
            on_success(full_name)
        return full_name

    monkeypatch.setattr("app.widgets.demande_form.add_location_with_wilaya_async", _fake_async)

    form = DemandeForm()
    form.wilaya.setValue("Alger")
    created = form._on_add_location("Hydra")
    _drain_events(qapp)

    status_label = form.location.findChild(QLabel, "locationStatusLabel")
    assert isinstance(created, str)
    assert created.startswith("Hydra")
    assert status_label is not None
    assert status_label.property("immoState") == "error"
    assert form.location._retry_callback is not None  # noqa: SLF001

    form.location._on_retry_clicked()  # noqa: SLF001
    _drain_events(qapp)

    assert attempts["count"] == 2
    assert status_label.property("immoState") in {"success", "muted"}
    assert any(location.startswith("Hydra") for location in form._all_locations)  # noqa: SLF001
    form.deleteLater()


def test_offer_form_add_location_uses_async_success(monkeypatch: pytest.MonkeyPatch, qapp) -> None:
    monkeypatch.setattr("app.widgets.offer_form.prime_locations_non_blocking", _prime_locations)

    captured: list[str] = []

    def _fake_async(_parent, name: str, wilaya: str, *, on_success=None, on_error=None) -> str:
        full_name = helpers.normalize_location_with_wilaya(name, wilaya)
        captured.append(full_name)
        if on_success is not None:
            on_success(full_name)
        return full_name

    monkeypatch.setattr("app.widgets.offer_form.add_location_with_wilaya_async", _fake_async)

    form = OfferForm()
    form.wilaya.setValue("Alger")
    created = form._on_add_location("Birkhadem")
    _drain_events(qapp)

    status_label = form.location.findChild(QLabel, "locationStatusLabel")
    assert isinstance(created, str)
    assert created.startswith("Birkhadem")
    assert captured == [created]
    assert status_label is not None
    assert status_label.property("immoState") in {"success", "muted"}
    assert any(location.startswith("Birkhadem") for location in form._all_locations)  # noqa: SLF001
    form.deleteLater()
