from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import pytest

from server.pg import uow


def test_session_cleanup_logs_rollback_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeConn:
        def rollback(self) -> None:
            raise RuntimeError("rollback failed")

    class _FakePool:
        @contextmanager
        def connection(self) -> Iterator[_FakeConn]:
            yield _FakeConn()

    monkeypatch.setattr(uow, "_get_pool", lambda: _FakePool())
    monkeypatch.setattr(uow, "_apply_search_path", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(uow, "_set_session_context", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(uow, "_reset_connection", lambda *_args, **_kwargs: None)
    messages: list[str] = []

    def _fake_warning(message, *args, **kwargs):
        messages.append(str(message))

    monkeypatch.setattr(uow.logger, "warning", _fake_warning)
    with uow.get_uow().session():
        pass
    assert any("session cleanup rollback failed" in message.lower() for message in messages)
