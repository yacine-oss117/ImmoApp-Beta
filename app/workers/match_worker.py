"""
Background Match Worker

Computes match counts in a background thread to keep UI responsive.
Uses Qt signals to communicate progress back to the main thread.

ARCHITECTURE:
- This is a UI worker (PySide6 allowed)
- Imports ONLY from app.services (not app.data or app.matcher directly)
- Services own all transactions

Features:
    - Non-blocking computation
    - Progress signals for UI updates
    - Cancellation support
    - Thread-safe communication
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QMutex, QMutexLocker, QObject, QThread, Signal

# UI workers import ONLY from services
from app.services.client_repository import fetch_clients, get_total_client_count
from app.services.match_models import ClientMatchResult
from app.services.match_service import (
    count_matches_for_clients,
    count_matches_for_single_client,
    count_matches_for_wilaya_clients,
    get_matches_for_client,
)

logger = logging.getLogger(__name__)


class MatchCountWorker(QThread):
    """
    Background worker that computes match counts for multiple clients.

    Signals:
        count_ready(int, int): Emitted when a single client's count is computed
        progress(int, int): Emitted with (completed, total) for progress tracking
        all_finished(): Emitted when all work is done
        error(str): Emitted on error with message
    """

    count_ready = Signal(int, int)  # client_id (int), count
    progress = Signal(int, int)  # completed, total
    all_finished = Signal()
    error = Signal(str)

    def __init__(self, client_ids: list[int] | None = None, parent: QObject | None = None) -> None:
        """
        Initialize the worker.

        Args:
            client_ids: Specific client IDs (int) to compute. If None, computes all.
            parent: Parent QObject
        """
        super().__init__(parent)
        self._client_ids = client_ids
        self._cancelled = False
        self._mutex = QMutex()

    def cancel(self) -> None:
        """Request cancellation of the worker (thread-safe)."""
        with QMutexLocker(self._mutex):
            self._cancelled = True
            logger.debug("MatchCountWorker cancellation requested")

    def _is_cancelled(self) -> bool:
        """Check if cancellation was requested (thread-safe)."""
        if self.isInterruptionRequested():
            return True
        with QMutexLocker(self._mutex):
            return self._cancelled

    def run(self) -> None:
        """Main worker thread - computes match counts."""
        try:
            if self.isInterruptionRequested():
                return

            if self._client_ids:
                client_ids = list(self._client_ids)
                total = len(client_ids)
                logger.debug(f"MatchCountWorker starting for {total} specific clients")

                batch_size = 200
                for i in range(0, total, batch_size):
                    if self._is_cancelled():
                        logger.debug("MatchCountWorker cancelled")
                        break
                    chunk = client_ids[i : i + batch_size]
                    try:
                        counts = count_matches_for_clients(chunk)
                    except RuntimeError as exc:
                        msg = f"Batch count failed for {len(chunk)} clients"
                        logger.error(msg, exc_info=True)
                        raise RuntimeError(msg) from exc

                    for cid in chunk:
                        self.count_ready.emit(cid, counts.get(cid, 0))

                    processed = min(total, i + len(chunk))
                    self.progress.emit(processed, total)
            else:
                total = get_total_client_count(status="active")
                logger.debug(f"MatchCountWorker starting for {total} clients (paginated)")

                page_size = 300
                processed = 0
                offset = 0

                while True:
                    if self._is_cancelled():
                        logger.debug("MatchCountWorker cancelled")
                        break

                    clients = fetch_clients(limit=page_size, offset=offset, status="active")
                    if not clients:
                        break

                    client_ids = [c.id for c in clients]
                    try:
                        counts = count_matches_for_clients(client_ids)
                    except RuntimeError as exc:
                        msg = f"Batch count failed for {len(client_ids)} clients"
                        logger.error(msg, exc_info=True)
                        raise RuntimeError(msg) from exc

                    for cid in client_ids:
                        self.count_ready.emit(cid, counts.get(cid, 0))

                    processed += len(client_ids)
                    self.progress.emit(processed, total)
                    offset += len(client_ids)

            self.all_finished.emit()
            logger.debug("MatchCountWorker completed")

        except RuntimeError as exc:
            logger.error("MatchCountWorker error", exc_info=True)
            self.error.emit(str(exc))


class SingleClientWorker(QThread):
    """Worker to compute count for a SINGLE client."""

    count_ready = Signal(int, int)  # client_id (int), count
    error = Signal(str)

    def __init__(self, client_id: int, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._client_id = client_id

    def run(self) -> None:
        """Compute count for single client."""
        if self.isInterruptionRequested():
            return
        try:
            count = count_matches_for_single_client(self._client_id)
            self.count_ready.emit(self._client_id, count)
            logger.debug(f"SingleClientWorker: {self._client_id} = {count}")
        except RuntimeError:
            msg = f"SingleClientWorker error for {self._client_id}"
            logger.error(msg, exc_info=True)
            self.error.emit(msg)


class WilayaClientsWorker(QThread):
    """Worker to recompute counts for all clients in a specific wilaya."""

    count_ready = Signal(int, int)  # client_id (int), count
    all_finished = Signal()
    error = Signal(str)

    def __init__(self, wilaya: str, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._wilaya = wilaya

    def run(self) -> None:
        """Compute counts for clients in this wilaya."""
        if self.isInterruptionRequested():
            return
        try:
            from app.utils.common import norm_text

            wilaya_norm = norm_text(self._wilaya)
            counts = count_matches_for_wilaya_clients(wilaya_norm)
            logger.debug(f"WilayaClientsWorker: {len(counts)} clients in {self._wilaya}")

            for client_id, count in counts.items():
                self.count_ready.emit(client_id, count)

            self.all_finished.emit()

        except RuntimeError:
            msg = "WilayaClientsWorker error"
            logger.error(msg, exc_info=True)
            self.error.emit(msg)
            self.all_finished.emit()


class MatchResultWorker(QThread):
    """Worker to compute matches for a single client."""

    result_ready = Signal(object)  # ClientMatchResult
    error = Signal(str)

    def __init__(
        self,
        client_id: int,
        *,
        limit_per_demande: int,
        score_threshold: float,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._client_id = client_id
        self._limit_per_demande = limit_per_demande
        self._score_threshold = score_threshold

    def run(self) -> None:
        """Compute match results for the client."""
        if self.isInterruptionRequested():
            return
        try:
            result: ClientMatchResult = get_matches_for_client(
                self._client_id,
                limit_per_demande=self._limit_per_demande,
                score_threshold=self._score_threshold,
            )
            self.result_ready.emit(result)
        except RuntimeError as exc:
            msg = f"MatchResultWorker error for {self._client_id}"
            logger.error(msg, exc_info=True)
            self.error.emit(str(exc))
