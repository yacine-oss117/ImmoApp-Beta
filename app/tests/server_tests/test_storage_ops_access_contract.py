from __future__ import annotations

from contextlib import nullcontext

import pytest

from app.tests.server_tests._integration_auth_helpers import ensure_django

ensure_django()

from server.services import storage_ops_access  # noqa: E402
from server.services.storage_errors import StorageError  # noqa: E402


class _DummyUow:
    def session(self):
        return nullcontext(object())


class _FakeBody:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload
        self.read_sizes: list[int] = []
        self.closed = False

    def read(self, size: int = -1) -> bytes:
        self.read_sizes.append(int(size))
        if size < 0:
            return self._payload
        return self._payload[:size]

    def close(self) -> None:
        self.closed = True


def test_fetch_small_bytes_rejects_oversize_metadata_before_object_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(storage_ops_access, "get_uow", lambda: _DummyUow())
    monkeypatch.setattr(
        storage_ops_access.storage_data,
        "get_storage_object",
        lambda _session, _storage_id: {
            "status": "ready",
            "size_bytes": 99,
            "bucket": "immoapp",
            "object_key": "tests/oversize.bin",
        },
    )
    monkeypatch.setattr(
        storage_ops_access,
        "get_storage_client",
        lambda: (_ for _ in ()).throw(AssertionError("get_object should not be called")),
    )

    with pytest.raises(StorageError, match="inline byte limit"):
        storage_ops_access.fetch_small_bytes("obj-1", max_bytes=16)


def test_fetch_small_bytes_rejects_oversize_content_length_before_full_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = _FakeBody(b"abc")
    monkeypatch.setattr(storage_ops_access, "get_uow", lambda: _DummyUow())
    monkeypatch.setattr(
        storage_ops_access.storage_data,
        "get_storage_object",
        lambda _session, _storage_id: {
            "status": "ready",
            "size_bytes": 3,
            "bucket": "immoapp",
            "object_key": "tests/content-length.bin",
        },
    )
    monkeypatch.setattr(
        storage_ops_access,
        "get_storage_client",
        lambda: type(
            "_Client",
            (),
            {
                "get_object": staticmethod(
                    lambda **_kwargs: {
                        "Body": body,
                        "ContentLength": 32,
                        "ContentType": "application/octet-stream",
                    }
                )
            },
        )(),
    )

    with pytest.raises(StorageError, match="inline byte limit"):
        storage_ops_access.fetch_small_bytes("obj-2", max_bytes=16)

    assert body.closed is True
    assert body.read_sizes == []


def test_fetch_small_bytes_uses_bounded_read_and_rejects_oversize_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = _FakeBody(b"abcdef")
    monkeypatch.setattr(storage_ops_access, "get_uow", lambda: _DummyUow())
    monkeypatch.setattr(
        storage_ops_access.storage_data,
        "get_storage_object",
        lambda _session, _storage_id: {
            "status": "ready",
            "size_bytes": 0,
            "bucket": "immoapp",
            "object_key": "tests/body.bin",
        },
    )
    monkeypatch.setattr(
        storage_ops_access,
        "get_storage_client",
        lambda: type(
            "_Client",
            (),
            {
                "get_object": staticmethod(
                    lambda **_kwargs: {
                        "Body": body,
                        "ContentLength": 0,
                        "ContentType": "application/octet-stream",
                    }
                )
            },
        )(),
    )

    with pytest.raises(StorageError, match="inline byte limit"):
        storage_ops_access.fetch_small_bytes("obj-3", max_bytes=5)

    assert body.read_sizes == [6]
    assert body.closed is True


def test_fetch_small_bytes_returns_small_ready_object(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = _FakeBody(b"hello")
    monkeypatch.setattr(storage_ops_access, "get_uow", lambda: _DummyUow())
    monkeypatch.setattr(
        storage_ops_access.storage_data,
        "get_storage_object",
        lambda _session, _storage_id: {
            "status": "ready",
            "size_bytes": 5,
            "bucket": "immoapp",
            "object_key": "tests/ok.txt",
        },
    )
    monkeypatch.setattr(
        storage_ops_access,
        "get_storage_client",
        lambda: type(
            "_Client",
            (),
            {
                "get_object": staticmethod(
                    lambda **_kwargs: {
                        "Body": body,
                        "ContentLength": 5,
                        "ContentType": "text/plain",
                    }
                )
            },
        )(),
    )

    object_key, payload, content_type = storage_ops_access.fetch_small_bytes(
        "obj-4",
        max_bytes=5,
    )

    assert object_key == "tests/ok.txt"
    assert payload == b"hello"
    assert content_type == "text/plain"
    assert body.read_sizes == [6]
