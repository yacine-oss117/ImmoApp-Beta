from __future__ import annotations

from dataclasses import dataclass


@dataclass
class _Row:
    id: int


class _Session:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _Uow:
    def session(self):
        return _Session()


def test_fetch_clients_cursor_delegates_to_read(monkeypatch) -> None:
    from server.services import clients

    captured: dict[str, object] = {}

    def _fetch_cursor(
        session,
        *,
        limit: int,
        cursor: int | None,
        search: str,
        status: str | None,
        include_deleted: bool,
    ):
        captured["session"] = session
        captured["limit"] = limit
        captured["cursor"] = cursor
        captured["search"] = search
        captured["status"] = status
        captured["include_deleted"] = include_deleted
        return [_Row(11)]

    monkeypatch.setattr(clients, "get_uow", lambda: _Uow())
    monkeypatch.setattr(clients.read, "fetch_clients_cursor", _fetch_cursor)

    items = clients.fetch_clients_cursor(
        limit=25,
        cursor=10,
        search="alice",
        status="active",
        include_deleted=True,
    )

    assert [item.id for item in items] == [11]
    assert captured["limit"] == 25
    assert captured["cursor"] == 10
    assert captured["search"] == "alice"
    assert captured["status"] == "active"
    assert captured["include_deleted"] is True


def test_fetch_clients_with_count_uses_cursor_offset_path_and_skips_count_on_short_page(
    monkeypatch,
) -> None:
    from server.services import clients

    calls: list[tuple[int, int | None]] = []

    def _fetch_cursor(
        _session,
        *,
        limit: int,
        cursor: int | None,
        search: str,
        status: str | None,
        include_deleted: bool,
    ):
        calls.append((limit, cursor))
        assert search == ""
        assert status == "active"
        assert include_deleted is False
        if cursor is None:
            return [_Row(1), _Row(2)]
        if cursor == 2:
            return [_Row(3)]
        return []

    def _unexpected_count(*_args, **_kwargs):
        raise AssertionError("count query should be skipped when the short page proves the total")

    monkeypatch.setattr(clients, "get_uow", lambda: _Uow())
    monkeypatch.setattr(clients.read, "fetch_clients_cursor", _fetch_cursor)
    monkeypatch.setattr(clients.read, "get_total_client_count", _unexpected_count)

    items, total = clients.fetch_clients_with_count(limit=2, offset=2)

    assert [item.id for item in items] == [3]
    assert total == 3
    assert calls == [(2, None), (2, 2)]


def test_fetch_listings_with_count_uses_cursor_offset_path_and_skips_count_on_short_page(
    monkeypatch,
) -> None:
    from server.services import listings

    calls: list[tuple[int, int | None]] = []

    def _fetch_cursor(
        _session,
        *,
        limit: int,
        cursor: int | None,
        search: str,
        status: str | None,
        include_deleted: bool,
    ):
        calls.append((limit, cursor))
        assert search == ""
        assert status == "available"
        assert include_deleted is False
        if cursor is None:
            return [_Row(10), _Row(20)]
        if cursor == 20:
            return [_Row(30)]
        return []

    def _unexpected_count(*_args, **_kwargs):
        raise AssertionError("count query should be skipped when the short page proves the total")

    monkeypatch.setattr(listings, "get_uow", lambda: _Uow())
    monkeypatch.setattr(listings.read, "fetch_listings_cursor", _fetch_cursor)
    monkeypatch.setattr(listings.read, "get_total_listing_count", _unexpected_count)

    items, total = listings.fetch_listings_with_count(limit=2, offset=2)

    assert [item.id for item in items] == [30]
    assert total == 3
    assert calls == [(2, None), (2, 20)]
