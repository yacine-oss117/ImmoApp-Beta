from __future__ import annotations

import pytest

from server.pg import schema


def test_release_schema_lock_logs_on_generic_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Session:
        def execute(self, _sql, _params):
            raise RuntimeError("unlock failed")

    messages: list[str] = []

    def _fake_warning(message, *args, **kwargs):
        messages.append(str(message))

    monkeypatch.setattr(schema.logger, "warning", _fake_warning)
    schema._release_schema_lock(_Session())
    assert any("Advisory unlock failed" in message for message in messages)


def test_release_schema_lock_logs_retry_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _InFailed(Exception):
        pass

    monkeypatch.setattr(schema.psycopg.errors, "InFailedSqlTransaction", _InFailed)

    class _Session:
        def __init__(self) -> None:
            self.calls = 0
            self.rollbacks = 0

        def execute(self, _sql, _params):
            self.calls += 1
            if self.calls == 1:
                raise _InFailed("tx aborted")
            raise RuntimeError("retry failed")

        def rollback(self):
            self.rollbacks += 1

    messages: list[str] = []

    def _fake_warning(message, *args, **kwargs):
        messages.append(str(message))

    monkeypatch.setattr(schema.logger, "warning", _fake_warning)
    session = _Session()
    schema._release_schema_lock(session)

    assert session.rollbacks == 1
    assert any("attempting rollback before retry" in message for message in messages)
    assert any("unlock retry failed after rollback" in message for message in messages)
