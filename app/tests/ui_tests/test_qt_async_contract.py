from __future__ import annotations

import time

import pytest

pytest.importorskip("PySide6")

from app.utils import qt_async

pytestmark = pytest.mark.ui


def _wait_until(predicate, qapp, *, timeout_sec: float = 1.5) -> bool:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        if predicate():
            return True
        qapp.processEvents()
        time.sleep(0.01)
    return predicate()


def test_run_blocking_timeout_releases_worker_after_completion(qapp) -> None:
    def _slow_work() -> str:
        time.sleep(0.1)
        return "done"

    with pytest.raises(TimeoutError):
        qt_async.run_blocking(_slow_work, timeout_ms=10)

    assert _wait_until(lambda: len(qt_async._ACTIVE_WORKERS) == 0, qapp)


def test_run_background_result_tracks_then_releases_worker(qapp) -> None:
    got = {"value": None}

    def _work() -> int:
        return 7

    def _on_success(value: int) -> None:
        got["value"] = value

    qt_async.run_background_result(_work, _on_success)

    assert _wait_until(lambda: got["value"] == 7, qapp)
    assert _wait_until(lambda: len(qt_async._ACTIVE_WORKERS) == 0, qapp)
