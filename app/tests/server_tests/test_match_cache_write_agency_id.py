from __future__ import annotations

from core.data.match_cache_write import store_count


class _FakeSession:
    def __init__(self, client_row: dict[str, object] | None) -> None:
        self._client_row = client_row
        self._last_sql = ""
        self.executed: list[tuple[str, tuple[object, ...]]] = []

    def execute(self, sql: str, params: list[object] | tuple[object, ...] = ()) -> _FakeSession:
        self._last_sql = sql
        self.executed.append((sql, tuple(params)))
        return self

    def executemany(
        self, sql: str, params_seq: list[tuple[object, ...]] | tuple[tuple[object, ...], ...]
    ) -> _FakeSession:
        for params in params_seq:
            self.execute(sql, params)
        return self

    def fetchone(self) -> dict[str, object] | None:
        if "FROM clients" in self._last_sql and "WHERE id = %s" in self._last_sql:
            return self._client_row
        return None


def test_store_count_writes_agency_id_from_client_row() -> None:
    session = _FakeSession(
        {
            "visibility": "agency",
            "owner_user_id": 7,
            "agency_id": 42,
            "status": "active",
            "deleted_at": None,
        }
    )

    store_count(session, client_id=123, count=9)

    insert_calls = [
        call for call in session.executed if "INSERT INTO match_counts_cache" in call[0]
    ]
    assert len(insert_calls) == 1
    insert_params = insert_calls[0][1]
    assert insert_params[0] == 123
    assert insert_params[1] == 42
    assert insert_params[2] == 9


def test_store_count_skips_insert_when_agency_id_missing() -> None:
    session = _FakeSession(
        {
            "visibility": "agency",
            "owner_user_id": 7,
            "agency_id": None,
            "status": "active",
            "deleted_at": None,
        }
    )

    store_count(session, client_id=123, count=9)

    sql_text = " ".join(sql for sql, _ in session.executed)
    assert "INSERT INTO match_counts_cache" not in sql_text
    assert "DELETE FROM match_counts_cache WHERE client_id = %s" in sql_text
