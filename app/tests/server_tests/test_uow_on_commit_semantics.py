from __future__ import annotations

from contextlib import contextmanager

import pytest

from server.pg import uow as uow_mod


class _DummyCursor:
    rowcount = 0

    def fetchone(self):
        return None

    def fetchall(self):
        return []

    def fetchmany(self, _size: int = 1000):
        return []


class _FakeConn:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    def execute(self, _sql: str, _params=()):
        return _DummyCursor()

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


class _FakePool:
    def __init__(self, conn: _FakeConn) -> None:
        self._conn = conn

    @contextmanager
    def connection(self):
        yield self._conn


@pytest.fixture
def _patched_uow(monkeypatch):
    conn = _FakeConn()
    monkeypatch.setattr(uow_mod, "_get_pool", lambda: _FakePool(conn))
    monkeypatch.setattr(uow_mod, "_apply_search_path", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(uow_mod, "_set_session_context", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(uow_mod, "_reset_connection", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        uow_mod,
        "_require_tenant_context_for_transaction",
        lambda **_kwargs: None,
    )
    return conn


def test_on_commit_runs_after_successful_commit(_patched_uow) -> None:
    events: list[str] = []
    with uow_mod.get_uow().transaction() as session:
        session.on_commit(lambda: events.append("after"))
        events.append("inside")

    assert events == ["inside", "after"]
    assert _patched_uow.commits == 1


def test_on_commit_callbacks_cleared_on_rollback(_patched_uow) -> None:
    events: list[str] = []
    with pytest.raises(RuntimeError):
        with uow_mod.get_uow().transaction() as session:
            session.on_commit(lambda: events.append("after"))
            raise RuntimeError("boom")

    assert events == []
    assert _patched_uow.commits == 0
    assert _patched_uow.rollbacks == 1


def test_on_commit_requires_transaction_context() -> None:
    session = uow_mod.PgSession(_FakeConn(), on_commit_enabled=False)
    with pytest.raises(RuntimeError):
        session.on_commit(lambda: None)
