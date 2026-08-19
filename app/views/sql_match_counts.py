"""
Shared async match-count queue utilities for SQL-backed models.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from functools import partial
from typing import Protocol, cast

from PySide6.QtCore import QObject, QTimer

from app.utils.qt_async import run_background

logger = logging.getLogger(__name__)


class _HasDestroyed(Protocol):
    destroyed: object


class AsyncCountQueue:
    """Queue async match-count fetches with coalescing and UI-safe apply."""

    def __init__(
        self,
        *,
        owner: QObject,
        count_fn: Callable[[list[int]], dict[int, int]],
        apply_fn: Callable[[dict[int, int], list[int]], None],
        label: str,
    ) -> None:
        self._owner = owner
        self._count_fn = count_fn
        self._apply_fn = apply_fn
        self._label = label
        self._lock = threading.Lock()
        self._pending_ids: set[int] = set()
        self._inflight = False
        self._disposed = threading.Event()

    def dispose(self) -> None:
        self._disposed.set()
        with self._lock:
            self._pending_ids.clear()
            self._inflight = False

    def queue(self, ids: list[int]) -> None:
        if self._disposed.is_set():
            return
        if not ids:
            return
        with self._lock:
            self._pending_ids.update(ids)
            if self._inflight:
                return
            self._inflight = True
        run_background(self._worker)

    def _worker(self) -> None:
        while True:
            if self._disposed.is_set():
                return
            with self._lock:
                if not self._pending_ids:
                    self._inflight = False
                    return
                batch_ids = list(self._pending_ids)
                self._pending_ids.clear()

            try:
                counts = self._count_fn(batch_ids)
            except (RuntimeError, ValueError):
                logger.error("Failed to compute %s counts", self._label, exc_info=True)
                counts = {}

            if self._disposed.is_set():
                return
            QTimer.singleShot(
                0,
                cast(QObject, self._owner),
                partial(self._apply_fn, counts, batch_ids),
            )


__all__ = ["AsyncCountQueue"]
