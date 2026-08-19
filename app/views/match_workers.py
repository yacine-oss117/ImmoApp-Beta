"""
Worker controller helpers for the Match tab.
"""

from __future__ import annotations

import logging
import weakref
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial

from PySide6.QtCore import QObject, SignalInstance

from app.services.match_models import ClientMatchResult
from app.utils.i18n import tr_factory
from app.workers.match_worker import (
    MatchCountWorker,
    MatchResultWorker,
    SingleClientWorker,
    WilayaClientsWorker,
)

logger = logging.getLogger(__name__)
_TR = tr_factory("MatchWorkers")

ProgressCallback = Callable[[int, int], None]
CountReadyCallback = Callable[[int, int], None]
AllFinishedCallback = Callable[[], None]
TextCallback = Callable[[str], None]
MatchWorker = MatchCountWorker | MatchResultWorker | SingleClientWorker | WilayaClientsWorker

_STOP_TIMEOUT_MS = 1500


@dataclass(frozen=True)
class _SignalConnection:
    """Track a worker signal/slot pairing for cleanup."""

    signal: SignalInstance
    slot: Callable[..., None]


class MatchWorkerController:
    """Manage MatchCountWorker lifecycle and callbacks."""

    def __init__(
        self,
        *,
        parent: QObject | None,
        on_count_ready: CountReadyCallback,
        on_all_finished: AllFinishedCallback,
        on_refresh: AllFinishedCallback,
        progress_text: TextCallback,
        progress_show: Callable[[], None],
        progress_hide: Callable[[], None],
        progress_style: TextCallback,
        error_style: str,
    ) -> None:
        self._parent = parent
        self._active_workers: list[MatchWorker] = []
        self._on_count_ready = on_count_ready
        self._on_all_finished = on_all_finished
        self._on_refresh = on_refresh
        self._progress_text = progress_text
        self._progress_show = progress_show
        self._progress_hide = progress_hide
        self._progress_style = progress_style
        self._error_style = error_style
        self._connections: weakref.WeakKeyDictionary[MatchWorker, list[_SignalConnection]] = (
            weakref.WeakKeyDictionary()
        )

    def cleanup_all(self) -> None:
        """Stop background workers if possible; log if any cannot stop."""
        if not self.stop_all():
            logger.warning("Some match workers could not be stopped cleanly")

    def start_background_count(self, client_ids: list[int] | None = None) -> None:
        """Start background worker to compute match counts for specific clients."""
        self.cleanup_all()

        self._progress_text(_TR("Computing match counts..."))
        self._progress_show()

        worker = MatchCountWorker(client_ids=client_ids, parent=self._parent)
        self._track_connection(worker, worker.count_ready, self._on_count_ready)
        self._track_connection(worker, worker.progress, self._on_progress)
        self._track_connection(
            worker, worker.all_finished, partial(self._on_worker_finished, worker)
        )
        self._track_connection(worker, worker.error, self._on_error)

        self._register_worker(worker)
        worker.start()

    def _on_worker_finished(self, worker: MatchCountWorker) -> None:
        """Finalize progress UI and cleanup after a worker finishes."""
        self._progress_hide()
        self._on_refresh()
        self._on_worker_done(worker)
        self._on_all_finished()

    def _on_progress(self, completed: int, total: int) -> None:
        """Update progress label as counts are computed."""
        if total > 0:
            pct = int(100 * completed / total)
            self._progress_text(
                _TR("Computing: {completed}/{total} ({pct}%)").format(
                    completed=completed, total=total, pct=pct
                )
            )

    def _on_error(self, error: str) -> None:
        """Display an error state for background matching."""
        self._progress_text(_TR("Error: {error}").format(error=error))
        self._progress_style(self._error_style)

    def _register_worker(self, worker: MatchWorker) -> None:
        """Track a worker and clean up when it finishes."""
        self._active_workers.append(worker)
        self._track_connection(worker, worker.finished, partial(self._on_worker_done, worker))

    def _remove_worker(self, worker: MatchWorker) -> None:
        """Remove a worker from active list if present."""
        if worker in self._active_workers:
            self._active_workers.remove(worker)

    def _on_worker_done(self, worker: MatchWorker) -> None:
        """Remove worker after thread finishes."""
        self._disconnect_worker(worker)
        self._remove_worker(worker)

    def _track_connection(
        self, worker: MatchWorker, signal: SignalInstance, slot: Callable[..., None]
    ) -> None:
        signal.connect(slot)
        connections = self._connections.setdefault(worker, [])
        connections.append(_SignalConnection(signal=signal, slot=slot))

    def _disconnect_worker(self, worker: MatchWorker) -> None:
        connections = self._connections.pop(worker, [])
        for conn in connections:
            try:
                conn.signal.disconnect(conn.slot)
            except (RuntimeError, TypeError):
                logger.debug("Failed to disconnect worker signal", exc_info=True)
        try:
            worker.deleteLater()
        except RuntimeError:
            logger.debug("Worker deleteLater failed", exc_info=True)

    def _request_worker_stop(self, worker: MatchWorker) -> None:
        """Request a worker to stop without forcing termination."""
        if isinstance(worker, MatchCountWorker):
            worker.cancel()
        worker.requestInterruption()

    def stop_all(self, timeout_ms: int = _STOP_TIMEOUT_MS) -> bool:
        """Request all workers to stop and wait up to timeout per worker."""
        still_running: list[MatchWorker] = []
        for worker in self._active_workers[:]:
            try:
                self._request_worker_stop(worker)
            except RuntimeError as exc:
                logger.debug("Worker stop request failed: %s", exc)

        for worker in self._active_workers[:]:
            try:
                if worker.isRunning():
                    worker.wait(timeout_ms)
                if worker.isRunning():
                    still_running.append(worker)
                else:
                    self._disconnect_worker(worker)
                    self._remove_worker(worker)
            except RuntimeError as exc:
                logger.debug("Worker wait failed: %s", exc)

        if still_running:
            logger.warning(
                "Workers still running after stop request: %s",
                [type(worker).__name__ for worker in still_running],
            )
        return not still_running

    def _on_single_client_refresh(
        self,
        _client_id: int,
        _count: int,
        *,
        on_refresh: AllFinishedCallback,
    ) -> None:
        """Refresh UI after a single client recompute signal."""
        on_refresh()

    def show_error(self, error: str) -> None:
        """Update progress label with an error message."""
        self._on_error(error)

    def recompute_single_client(
        self,
        client_id: int,
        *,
        on_count_ready: CountReadyCallback,
        on_refresh: AllFinishedCallback,
    ) -> None:
        """Recompute count for a single client."""
        worker = SingleClientWorker(client_id, self._parent)
        self._track_connection(worker, worker.count_ready, on_count_ready)
        self._track_connection(worker, worker.error, self._on_error)
        self._track_connection(
            worker,
            worker.count_ready,
            partial(self._on_single_client_refresh, on_refresh=on_refresh),
        )
        self._register_worker(worker)
        worker.start()

    def recompute_wilaya_clients(
        self,
        wilaya: str,
        *,
        on_count_ready: CountReadyCallback,
        on_refresh: AllFinishedCallback,
    ) -> None:
        """Recompute counts for all clients in a wilaya."""
        worker = WilayaClientsWorker(wilaya, self._parent)
        self._track_connection(worker, worker.count_ready, on_count_ready)
        self._track_connection(worker, worker.error, self._on_error)
        self._track_connection(worker, worker.all_finished, on_refresh)
        self._register_worker(worker)
        worker.start()

    def compute_full_count(self, client_id: int, on_ready: CountReadyCallback) -> None:
        """Compute a single client's full match count in the background."""
        worker = SingleClientWorker(client_id, self._parent)
        self._track_connection(worker, worker.count_ready, on_ready)
        self._track_connection(worker, worker.error, self._on_error)
        self._register_worker(worker)
        worker.start()

    def run_match(
        self,
        client_id: int,
        *,
        limit_per_demande: int,
        score_threshold: float,
        on_ready: Callable[[ClientMatchResult], None],
        on_error: Callable[[str], None],
    ) -> None:
        """Compute match results for a client in the background."""
        worker = MatchResultWorker(
            client_id,
            limit_per_demande=limit_per_demande,
            score_threshold=score_threshold,
            parent=self._parent,
        )
        self._track_connection(worker, worker.result_ready, on_ready)
        self._track_connection(worker, worker.error, on_error)
        self._register_worker(worker)
        worker.start()
