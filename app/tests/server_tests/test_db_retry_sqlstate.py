from __future__ import annotations

from types import SimpleNamespace

from core.utils import db_retry


class _TransientDbError(Exception):
    def __init__(self, sqlstate: str) -> None:
        super().__init__(sqlstate)
        self.sqlstate = sqlstate


def test_run_with_retry_retries_retryable_sqlstate(monkeypatch) -> None:
    monkeypatch.setattr(db_retry, "psycopg", SimpleNamespace(Error=Exception))
    monkeypatch.setattr(db_retry.time, "sleep", lambda _v: None)

    calls = {"n": 0}

    def _work() -> str:
        calls["n"] += 1
        if calls["n"] < 3:
            raise _TransientDbError("40P01")
        return "ok"

    assert db_retry.run_with_retry(_work, max_attempts=4) == "ok"
    assert calls["n"] == 3


def test_run_with_retry_does_not_retry_non_retryable(monkeypatch) -> None:
    monkeypatch.setattr(db_retry, "psycopg", SimpleNamespace(Error=Exception))
    monkeypatch.setattr(db_retry.time, "sleep", lambda _v: None)

    calls = {"n": 0}

    def _work() -> None:
        calls["n"] += 1
        raise _TransientDbError("23505")

    try:
        db_retry.run_with_retry(_work, max_attempts=4)
    except _TransientDbError:
        pass
    else:
        raise AssertionError("Expected non-retryable exception to be raised")
    assert calls["n"] == 1
