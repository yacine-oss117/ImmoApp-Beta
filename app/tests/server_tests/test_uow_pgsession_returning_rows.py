from __future__ import annotations

from typing import Any

from server.pg.uow import PgSession


class _FakeCursor:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows
        self._idx = 0
        self.rowcount = len(rows)

    def fetchone(self) -> dict[str, Any] | None:
        if self._idx >= len(self._rows):
            return None
        row = self._rows[self._idx]
        self._idx += 1
        return row

    def fetchall(self) -> list[dict[str, Any]]:
        if self._idx >= len(self._rows):
            return []
        rows = self._rows[self._idx :]
        self._idx = len(self._rows)
        return rows

    def fetchmany(self, size: int) -> list[dict[str, Any]]:
        if self._idx >= len(self._rows):
            return []
        end = min(self._idx + size, len(self._rows))
        rows = self._rows[self._idx : end]
        self._idx = end
        return rows


class _FakeConn:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def execute(self, _sql: str, _params: Any) -> _FakeCursor:
        return _FakeCursor(list(self._rows))

    def cursor(self) -> _FakeCursor:
        return _FakeCursor([])

    def commit(self) -> None:
        return None

    def rollback(self) -> None:
        return None


def test_pgsession_fetchall_keeps_first_returning_row() -> None:
    rows = [{"id": 1}, {"id": 2}, {"id": 3}]
    session = PgSession(_FakeConn(rows))
    session.execute("INSERT INTO t(x) VALUES (%s) RETURNING id", (1,))
    got = session.fetchall()
    assert [row["id"] for row in got] == [1, 2, 3]


def test_pgsession_fetchmany_keeps_first_returning_row() -> None:
    rows = [{"id": 10}, {"id": 11}, {"id": 12}]
    session = PgSession(_FakeConn(rows))
    session.execute("INSERT INTO t(x) VALUES (%s) RETURNING id", (1,))
    got = session.fetchmany(2)
    assert [row["id"] for row in got] == [10, 11]
    got2 = session.fetchmany(2)
    assert [row["id"] for row in got2] == [12]
