from __future__ import annotations

from dataclasses import dataclass

import pytest
from PySide6.QtCore import QModelIndex

from app.models import Client, Demande, Listing
from app.views import client_sql_model as client_model_module
from app.views import listing_sql_model as listing_model_module
from app.views.sql_v2_model import SQLV2Model

pytestmark = pytest.mark.ui


@dataclass
class _RootNode:
    id: int


@dataclass
class _ChildNode:
    id: int
    client_id: int


def test_sql_v2_model_fetches_children_only_when_fetch_more_called(qapp) -> None:
    roots = [_RootNode(id=1)]
    calls: list[int] = []

    def fetch_roots(limit: int, offset: int) -> list[_RootNode]:
        return roots[offset : offset + limit]

    def fetch_children(parent_id: int) -> list[_ChildNode]:
        calls.append(parent_id)
        return [_ChildNode(id=101, client_id=parent_id)]

    model = SQLV2Model[_RootNode, _ChildNode](
        columns=["Name"],
        count_fn=lambda: len(roots),
        fetch_fn=fetch_roots,
        child_fetch_fn=fetch_children,
    )
    model.refresh_data()

    parent_index = model.index(0, 0, QModelIndex())
    assert parent_index.isValid()
    assert model.hasChildren(parent_index) is True
    assert model.rowCount(parent_index) == 0
    assert calls == []

    assert model.canFetchMore(parent_index) is True
    model.fetchMore(parent_index)
    assert calls == [1]
    assert model.rowCount(parent_index) == 1


def test_sql_v2_model_index_survives_root_fetch_failure_and_throttles(qapp) -> None:
    calls = 0

    def fetch_roots(limit: int, offset: int) -> list[_RootNode]:
        nonlocal calls
        calls += 1
        raise RuntimeError("simulated upstream failure")

    model = SQLV2Model[_RootNode, _ChildNode](
        columns=["Name"],
        count_fn=lambda: 1,
        fetch_fn=fetch_roots,
    )
    model.refresh_data()

    first = model.index(0, 0, QModelIndex())
    assert not first.isValid()
    second = model.index(0, 0, QModelIndex())
    assert not second.isValid()
    assert calls == 1


def test_sql_v2_model_child_fetch_failure_surfaces_inline_status_and_stops_retrying(qapp) -> None:
    roots = [_RootNode(id=1)]
    calls: list[int] = []

    def fetch_roots(limit: int, offset: int) -> list[_RootNode]:
        return roots[offset : offset + limit]

    def fetch_children(parent_id: int) -> list[_ChildNode]:
        calls.append(parent_id)
        raise RuntimeError("server offline")

    model = SQLV2Model[_RootNode, _ChildNode](
        columns=["Name"],
        count_fn=lambda: len(roots),
        fetch_fn=fetch_roots,
        child_fetch_fn=fetch_children,
    )
    model.refresh_data()

    parent_index = model.index(0, 0, QModelIndex())
    assert parent_index.isValid()
    assert model.canFetchMore(parent_index) is True

    model.fetchMore(parent_index)

    assert calls == [1]
    assert model.rowCount(parent_index) == 1
    status_index = model.index(0, 0, parent_index)
    assert status_index.isValid()
    assert "server offline" in str(model.data(status_index) or "").lower()
    assert model.canFetchMore(parent_index) is False


def test_sql_v2_model_child_fetch_status_can_retry_after_backoff(qapp) -> None:
    roots = [_RootNode(id=1)]
    calls: list[int] = []
    online = {"ready": False}

    def fetch_roots(limit: int, offset: int) -> list[_RootNode]:
        return roots[offset : offset + limit]

    def fetch_children(parent_id: int) -> list[_ChildNode]:
        calls.append(parent_id)
        if not online["ready"]:
            raise RuntimeError("server offline")
        return [_ChildNode(id=101, client_id=parent_id)]

    model = SQLV2Model[_RootNode, _ChildNode](
        columns=["Name"],
        count_fn=lambda: len(roots),
        fetch_fn=fetch_roots,
        child_fetch_fn=fetch_children,
    )
    model.refresh_data()

    parent_index = model.index(0, 0, QModelIndex())
    assert parent_index.isValid()

    model.fetchMore(parent_index)
    assert calls == [1]
    assert model.rowCount(parent_index) == 1
    assert model.canFetchMore(parent_index) is False

    model._child_fetch_backoff_until[1] = 0.0
    online["ready"] = True

    assert model.canFetchMore(parent_index) is True
    model.fetchMore(parent_index)

    assert calls == [1, 1]
    assert model.rowCount(parent_index) == 1
    child_index = model.index(0, 0, parent_index)
    assert child_index.isValid()
    assert isinstance(child_index.internalPointer(), _ChildNode)


def test_client_model_does_not_eager_prefetch_demandes_for_loaded_page(
    monkeypatch: pytest.MonkeyPatch,
    qapp,
) -> None:
    client = Client(id=123, family_name="Client 123")
    child_calls: list[int] = []

    monkeypatch.setattr(client_model_module, "get_total_client_count", lambda *args, **kwargs: 1)
    monkeypatch.setattr(
        client_model_module,
        "fetch_clients",
        lambda *args, **kwargs: [client],
    )

    def _fake_fetch_demandes(client_id: int, *args, **kwargs) -> list[Demande]:
        child_calls.append(client_id)
        return [Demande(id=777, client_id=client_id, type="apt", action="rent")]

    monkeypatch.setattr(client_model_module, "get_demandes_for_client", _fake_fetch_demandes)

    model = client_model_module.ClientSQLModel()
    model._queue_client_counts = lambda _ids: None
    model._queue_demande_counts = lambda _ids: None
    model.refresh_data()

    root_index = model.index(0, 0, QModelIndex())
    assert root_index.isValid()
    assert child_calls == []

    assert model.canFetchMore(root_index) is True
    model.fetchMore(root_index)
    assert child_calls == [123]
    assert model.rowCount(root_index) == 1


def test_client_model_refresh_primes_first_root_row_without_fetching_children(
    monkeypatch: pytest.MonkeyPatch,
    qapp,
) -> None:
    client = Client(id=124, family_name="Prime Client")
    child_calls: list[int] = []

    monkeypatch.setattr(client_model_module, "get_total_client_count", lambda *args, **kwargs: 1)
    monkeypatch.setattr(client_model_module, "fetch_clients", lambda *args, **kwargs: [client])
    monkeypatch.setattr(
        client_model_module,
        "get_demandes_for_client",
        lambda client_id, *args, **kwargs: child_calls.append(client_id) or [],
    )

    model = client_model_module.ClientSQLModel()
    model._queue_client_counts = lambda _ids: None
    model._queue_demande_counts = lambda _ids: None
    model.refresh_data()

    assert model.loaded_root_rows() == [0]
    assert child_calls == []


def test_client_model_shows_inline_status_when_child_fetch_runtime_fails(
    monkeypatch: pytest.MonkeyPatch,
    qapp,
) -> None:
    client = Client(id=321, family_name="Client 321")

    monkeypatch.setattr(client_model_module, "get_total_client_count", lambda *args, **kwargs: 1)
    monkeypatch.setattr(
        client_model_module,
        "fetch_clients",
        lambda *args, **kwargs: [client],
    )
    monkeypatch.setattr(
        client_model_module,
        "get_demandes_for_client",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("API temporarily unavailable (circuit open)")
        ),
    )

    model = client_model_module.ClientSQLModel()
    model._queue_client_counts = lambda _ids: None
    model._queue_demande_counts = lambda _ids: None
    model.refresh_data()

    root_index = model.index(0, 0, QModelIndex())
    assert root_index.isValid()

    model.fetchMore(root_index)

    assert model.rowCount(root_index) == 1
    status_index = model.index(0, 0, root_index)
    assert status_index.isValid()
    assert "requests right now" in str(model.data(status_index) or "").lower()
    assert model.canFetchMore(root_index) is False


def test_client_model_refresh_resets_cursor_anchors(
    monkeypatch: pytest.MonkeyPatch,
    qapp,
) -> None:
    client = Client(id=500, family_name="Reset Client")
    reset_calls = {"count": 0}

    monkeypatch.setattr(client_model_module, "get_total_client_count", lambda *args, **kwargs: 1)
    monkeypatch.setattr(client_model_module, "fetch_clients", lambda *args, **kwargs: [client])
    monkeypatch.setattr(
        client_model_module, "get_demandes_for_client", lambda *_args, **_kwargs: []
    )
    monkeypatch.setattr(
        client_model_module,
        "reset_client_cursor_anchors",
        lambda: reset_calls.__setitem__("count", reset_calls["count"] + 1),
    )

    model = client_model_module.ClientSQLModel()
    model.refresh_data()

    assert reset_calls["count"] >= 1


def test_listing_model_refresh_resets_cursor_anchors(
    monkeypatch: pytest.MonkeyPatch,
    qapp,
) -> None:
    reset_calls = {"count": 0}

    monkeypatch.setattr(listing_model_module, "get_total_listing_count", lambda *args, **kwargs: 0)
    monkeypatch.setattr(listing_model_module, "fetch_listings", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        listing_model_module, "get_offers_for_listing", lambda *_args, **_kwargs: []
    )
    monkeypatch.setattr(
        listing_model_module,
        "reset_listing_cursor_anchors",
        lambda: reset_calls.__setitem__("count", reset_calls["count"] + 1),
    )

    model = listing_model_module.ListingSQLModel()
    model.refresh_data()

    assert reset_calls["count"] >= 1


def test_listing_model_refresh_primes_first_root_row(
    monkeypatch: pytest.MonkeyPatch,
    qapp,
) -> None:
    listing = Listing(id=700, family_name="Prime Listing")

    monkeypatch.setattr(listing_model_module, "get_total_listing_count", lambda *args, **kwargs: 1)
    monkeypatch.setattr(listing_model_module, "fetch_listings", lambda *args, **kwargs: [listing])
    monkeypatch.setattr(
        listing_model_module, "get_offers_for_listing", lambda *_args, **_kwargs: []
    )

    model = listing_model_module.ListingSQLModel()
    model._queue_listing_counts = lambda _ids: None
    model._queue_offer_counts = lambda _ids: None
    model.refresh_data()

    assert model.loaded_root_rows() == [0]
