from __future__ import annotations


class _EmptyResult:
    def fetchall(self) -> list[object]:
        return []


class _RecordingSession:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[object]]] = []

    def execute(self, sql: str, params: list[object]) -> _EmptyResult:
        self.calls.append((sql, list(params)))
        return _EmptyResult()


def test_client_cursor_query_uses_newest_first_desc_order() -> None:
    from core.data.client_repo_read import fetch_clients_cursor

    session = _RecordingSession()

    fetch_clients_cursor(
        session,
        limit=25,
        cursor=100,
        search="",
        status="active",
        include_deleted=False,
    )

    sql, params = session.calls[-1]
    assert "c.id < %s" in sql
    assert "ORDER BY c.id DESC LIMIT %s" in sql
    assert params == ["active", 100, 25]


def test_client_offset_query_uses_newest_first_desc_order() -> None:
    from core.data.client_repo_read import fetch_clients

    session = _RecordingSession()

    fetch_clients(
        session,
        limit=25,
        offset=50,
        search="",
        status="active",
        include_deleted=False,
    )

    sql, params = session.calls[-1]
    assert "ORDER BY c.id DESC" in sql
    assert params[-2:] == [25, 50]


def test_listing_cursor_query_uses_newest_first_desc_order() -> None:
    from core.data.listing_repo_read import fetch_listings_cursor

    session = _RecordingSession()

    fetch_listings_cursor(
        session,
        limit=25,
        cursor=100,
        search="",
        status="available",
        include_deleted=False,
    )

    sql, params = session.calls[-1]
    assert "l.id < %s" in sql
    assert "ORDER BY l.id DESC LIMIT %s" in sql
    assert params == ["available", 100, 25]


def test_listing_offset_query_uses_newest_first_desc_order() -> None:
    from core.data.listing_repo_read import fetch_listings

    session = _RecordingSession()

    fetch_listings(
        session,
        limit=25,
        offset=50,
        search="",
        status="available",
        include_deleted=False,
    )

    sql, params = session.calls[-1]
    assert "ORDER BY l.id DESC" in sql
    assert params[-2:] == [25, 50]
