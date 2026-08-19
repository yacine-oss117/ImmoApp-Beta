from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.views.clients_v2 import ClientsTabV2
from app.views.imports.import_experience import build_final_summary
from app.views.listings_v2 import ListingsTabV2

pytestmark = pytest.mark.ui


def test_clients_tab_shows_empty_state_and_import_banner(
    qapp,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.views.client_sql_model.get_total_client_count", lambda *args, **kwargs: 0
    )
    monkeypatch.setattr("app.views.client_sql_model.fetch_clients", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        "app.views.client_sql_model.get_demandes_for_client", lambda *args, **kwargs: []
    )

    final_state = SimpleNamespace(
        status="completed",
        created_count=50,
        updated_count=0,
        experience_summary=build_final_summary(
            status="completed",
            created_count=50,
            updated_count=0,
            error_count=0,
            skipped_count=0,
            result_entity_counts={"client": 10, "demande": 40},
            result_auto_fix_summary={},
            result_attention_summary={"needs_attention": 0},
        ),
    )
    captured: dict[str, object] = {}

    def _fake_open_import_wizard(*args, **kwargs):
        captured["entity_type_hint"] = kwargs.get("entity_type_hint")
        return final_state

    monkeypatch.setattr("app.views.clients_v2.open_import_wizard", _fake_open_import_wizard)

    related_refresh_calls = 0

    def _tracked_related_refresh() -> None:
        nonlocal related_refresh_calls
        related_refresh_calls += 1

    tab = ClientsTabV2(refresh_clients_cb=_tracked_related_refresh)
    refresh_calls = 0
    scroll_calls = 0

    def _tracked_refresh() -> None:
        nonlocal refresh_calls
        refresh_calls += 1
        tab._model.__class__.refresh_data(tab._model)

    def _tracked_scroll() -> None:
        nonlocal scroll_calls
        scroll_calls += 1

    assert not tab._empty_state.isHidden()
    assert not tab.tree.isHidden()
    assert tab._empty_add_btn.isHidden()
    assert tab._empty_import_btn.isHidden()
    tab.search_bar.setText("old filter")
    monkeypatch.setattr(tab._model, "refresh_data", _tracked_refresh)
    monkeypatch.setattr(tab.tree, "scrollToTop", _tracked_scroll)

    tab._open_import_wizard()

    assert captured["entity_type_hint"] == "client"
    assert refresh_calls == 1
    assert scroll_calls == 1
    assert related_refresh_calls == 1
    assert tab.search_bar.text() == ""
    assert not tab._notice_banner.isHidden()
    assert "Import complete" in tab._notice_banner.title_label.text()
    assert "10 clients and 40 requests" in tab._notice_banner.body_label.text()


def test_listings_tab_shows_empty_state_and_import_banner(
    qapp,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.views.listing_sql_model.get_total_listing_count", lambda *args, **kwargs: 0
    )
    monkeypatch.setattr("app.views.listing_sql_model.fetch_listings", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        "app.views.listing_sql_model.get_offers_for_listing", lambda *args, **kwargs: []
    )

    final_state = SimpleNamespace(
        status="completed",
        created_count=50,
        updated_count=0,
        experience_summary=build_final_summary(
            status="completed",
            created_count=50,
            updated_count=0,
            error_count=0,
            skipped_count=0,
            result_entity_counts={"listing": 10, "offer": 40},
            result_auto_fix_summary={},
            result_attention_summary={"needs_attention": 0},
        ),
    )
    captured: dict[str, object] = {}

    def _fake_open_import_wizard(*args, **kwargs):
        captured["entity_type_hint"] = kwargs.get("entity_type_hint")
        return final_state

    monkeypatch.setattr("app.views.listings_v2.open_import_wizard", _fake_open_import_wizard)

    tab = ListingsTabV2()
    tab._run_initial_refresh()
    refresh_calls = 0
    scroll_calls = 0

    def _tracked_refresh() -> None:
        nonlocal refresh_calls
        refresh_calls += 1
        tab._model.__class__.refresh_data(tab._model)

    def _tracked_scroll() -> None:
        nonlocal scroll_calls
        scroll_calls += 1

    assert not tab._empty_state.isHidden()
    assert not tab._results_splitter.isHidden()
    assert tab._empty_add_btn.isHidden()
    assert tab._empty_import_btn.isHidden()
    tab.search_bar.setText("old filter")
    monkeypatch.setattr(tab._model, "refresh_data", _tracked_refresh)
    monkeypatch.setattr(tab.tree, "scrollToTop", _tracked_scroll)

    tab._open_import_wizard()

    assert captured["entity_type_hint"] == "listing"
    assert refresh_calls == 1
    assert scroll_calls == 1
    assert tab.search_bar.text() == ""
    assert not tab._notice_banner.isHidden()
    assert "Import complete" in tab._notice_banner.title_label.text()
    assert "10 properties and 40 offers" in tab._notice_banner.body_label.text()


def test_clients_tab_zero_change_import_preserves_search_and_shows_filtered_empty_state(
    qapp,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.views.client_sql_model.get_total_client_count", lambda *args, **kwargs: 0
    )
    monkeypatch.setattr("app.views.client_sql_model.fetch_clients", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        "app.views.client_sql_model.get_demandes_for_client", lambda *args, **kwargs: []
    )

    final_state = SimpleNamespace(
        status="completed",
        created_count=0,
        updated_count=0,
        experience_summary=build_final_summary(
            status="completed",
            created_count=0,
            updated_count=0,
            error_count=0,
            skipped_count=5,
            result_entity_counts={},
            result_auto_fix_summary={},
            result_attention_summary={"needs_attention": 0},
            row_count=5,
            result_zero_change=True,
            result_zero_change_reasons=["all_rows_skipped"],
            terminal_reason="zero_change",
        ),
    )
    monkeypatch.setattr(
        "app.views.clients_v2.open_import_wizard",
        lambda *args, **kwargs: final_state,
    )

    tab = ClientsTabV2()
    scroll_calls = 0

    def _tracked_scroll() -> None:
        nonlocal scroll_calls
        scroll_calls += 1

    monkeypatch.setattr(tab.tree, "scrollToTop", _tracked_scroll)
    tab.search_bar.setText("hidden")

    tab._open_import_wizard()

    assert tab.search_bar.text() == "hidden"
    assert scroll_calls == 0
    assert not tab._empty_state.isHidden()
    assert not tab._empty_clear_btn.isHidden()
    assert "no results match" in tab._empty_title.text().lower()
    assert "Import finished" in tab._notice_banner.title_label.text()


def test_listings_tab_filtered_empty_state_shows_clear_search_action(
    qapp,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.views.listing_sql_model.get_total_listing_count", lambda *args, **kwargs: 0
    )
    monkeypatch.setattr("app.views.listing_sql_model.fetch_listings", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        "app.views.listing_sql_model.get_offers_for_listing", lambda *args, **kwargs: []
    )

    tab = ListingsTabV2()
    tab._run_initial_refresh()
    tab.search_bar.setText("hydra")
    tab._update_empty_state()

    assert not tab._empty_state.isHidden()
    assert not tab._empty_clear_btn.isHidden()
    assert "no results match" in tab._empty_title.text().lower()
