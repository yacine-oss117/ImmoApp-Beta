"""Background worker for simulation API calls."""

from __future__ import annotations

import logging
from collections.abc import Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

logger = logging.getLogger(__name__)


class SimulationSignals(QObject):
    """Signals for simulation background tasks."""

    finished = Signal(object)
    error = Signal(str)


class SimulationWorker(QRunnable):
    """Run a simulation API call in a background thread."""

    def __init__(self, operation: Callable[[], object]) -> None:
        super().__init__()
        self.signals = SimulationSignals()
        self._operation = operation

    @Slot()
    def run(self) -> None:
        try:
            result = self._operation()
        except (OSError, RuntimeError, ValueError) as exc:
            logger.error("Simulation task failed", exc_info=True)
            self.signals.error.emit(str(exc))
            return
        self.signals.finished.emit(result)


def run_simulation_async(
    operation: Callable[[], object],
    *,
    on_finished: Callable[[object], None] | None = None,
    on_error: Callable[[str], None] | None = None,
) -> SimulationWorker:
    """Run a simulation operation on the global thread pool."""
    worker = SimulationWorker(operation)
    if on_finished:
        worker.signals.finished.connect(on_finished)
    if on_error:
        worker.signals.error.connect(on_error)
    QThreadPool.globalInstance().start(worker)
    return worker
