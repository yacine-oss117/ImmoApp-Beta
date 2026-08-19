"""
Qt helpers for running blocking work off the UI thread.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any, TypeVar

from PySide6.QtCore import (
    QCoreApplication,
    QEventLoop,
    QObject,
    QRunnable,
    QThreadPool,
    QTimer,
    Signal,
)
from PySide6.QtWidgets import QApplication

_qt_is_valid_impl: Callable[[object], bool] | None
try:  # pragma: no cover - availability depends on Qt bindings at runtime
    import shiboken6
except Exception:  # pragma: no cover
    _qt_is_valid_impl = None
else:
    _qt_is_valid_impl = shiboken6.isValid


def _qt_is_valid(obj: object) -> bool:
    if _qt_is_valid_impl is None:
        return True
    try:
        return bool(_qt_is_valid_impl(obj))
    except RuntimeError:
        return False


def is_qt_object_alive(obj: object | None) -> bool:
    """Return whether a Qt wrapper still has a live underlying C++ object."""
    if obj is None:
        return False
    return _qt_is_valid(obj)


T = TypeVar("T")
_ACTIVE_WORKERS: list[_Worker] = []
_ACTIVE_WORKERS_LOCK = threading.Lock()
_APP_QUITTING = False
_APP_QUIT_HOOK_INSTALLED = False


def _track_worker(worker: _Worker) -> None:
    with _ACTIVE_WORKERS_LOCK:
        _ACTIVE_WORKERS.append(worker)


def _untrack_worker(worker: _Worker) -> None:
    with _ACTIVE_WORKERS_LOCK:
        try:
            _ACTIVE_WORKERS.remove(worker)
        except ValueError:
            return


def _mark_app_quitting() -> None:
    global _APP_QUITTING
    _APP_QUITTING = True


def _install_app_quit_hook() -> None:
    global _APP_QUIT_HOOK_INSTALLED
    if _APP_QUIT_HOOK_INSTALLED:
        return
    app = QApplication.instance()
    if app is None:
        return
    try:
        app.aboutToQuit.connect(_mark_app_quitting)
    except Exception:  # pragma: no cover - defensive for odd Qt teardown states
        return
    _APP_QUIT_HOOK_INSTALLED = True


def _qt_runtime_active() -> bool:
    if _APP_QUITTING:
        return False
    app = QApplication.instance()
    if app is None:
        return False
    try:
        if app.closingDown():
            return False
    except Exception:
        return False
    return True


def _is_ui_thread(_app: QCoreApplication) -> bool:
    return threading.current_thread() is threading.main_thread()


def _safe_loop_quit(loop: QEventLoop) -> None:
    """
    Quit an event loop only when the wrapped Qt object is still valid.

    Late worker completions after a timeout can race with loop teardown.
    """
    if not _qt_is_valid(loop):
        return
    try:
        loop.quit()
    except RuntimeError:
        return


class _WorkerSignals(QObject):
    finished = Signal(object, object)  # result, error


class _Worker(QRunnable):
    def __init__(
        self, func: Callable[..., T], args: tuple[Any, ...], kwargs: dict[str, Any]
    ) -> None:
        super().__init__()
        self.setAutoDelete(False)
        self.signals = _WorkerSignals()
        self._func = func
        self._args = args
        self._kwargs = kwargs

    def run(self) -> None:
        try:
            result = self._func(*self._args, **self._kwargs)
        except Exception as exc:  # pragma: no cover - passthrough
            if _qt_runtime_active() and _qt_is_valid(self.signals):
                self.signals.finished.emit(None, exc)
                _untrack_worker(self)
                return
            _untrack_worker(self)
            return
        if _qt_runtime_active() and _qt_is_valid(self.signals):
            self.signals.finished.emit(result, None)
            _untrack_worker(self)
            return
        _untrack_worker(self)


class _FireAndForget(QRunnable):
    def __init__(
        self, func: Callable[..., Any], args: tuple[Any, ...], kwargs: dict[str, Any]
    ) -> None:
        super().__init__()
        self._func = func
        self._args = args
        self._kwargs = kwargs

    def run(self) -> None:
        try:
            self._func(*self._args, **self._kwargs)
        except Exception:  # pragma: no cover - best-effort background
            return


def run_blocking(
    func: Callable[..., T],
    *args: Any,
    timeout_ms: int | None = None,
    **kwargs: Any,
) -> T:
    """
    Run a blocking function off the UI thread and wait with an event loop.

    If called outside the UI thread, it executes directly.
    """
    app = QApplication.instance()
    if app is None or not _is_ui_thread(app):
        return func(*args, **kwargs)
    _install_app_quit_hook()

    loop = QEventLoop()
    result_holder: dict[str, Any] = {}
    timed_out = {"value": False}
    timed_out_cleanup_connected = {"value": False}
    timeout_deadline: float | None = None
    if timeout_ms:
        timeout_deadline = time.monotonic() + (float(timeout_ms) / 1000.0)

    worker = _Worker(func, args, kwargs)
    _track_worker(worker)

    def _done(result: object, error: object) -> None:
        if "result" in result_holder or "error" in result_holder:
            return
        result_holder["completed_at"] = time.monotonic()
        result_holder["result"] = result
        result_holder["error"] = error
        _safe_loop_quit(loop)
        _untrack_worker(worker)

    def _cleanup_only(_result: object, _error: object) -> None:
        _untrack_worker(worker)

    worker.signals.finished.connect(_done)
    QThreadPool.globalInstance().start(worker)

    if timeout_ms:

        def _timeout() -> None:
            timed_out["value"] = True
            _safe_loop_quit(loop)

        QTimer.singleShot(timeout_ms, _timeout)

    loop.exec()

    completed_at = result_holder.get("completed_at")
    deadline_missed = timeout_deadline is not None and (
        completed_at is None or float(completed_at) > timeout_deadline
    )

    if (
        (timed_out["value"] or deadline_missed)
        and "result" not in result_holder
        and "error" not in result_holder
    ):
        try:
            worker.signals.finished.disconnect(_done)
        except Exception:
            pass
        try:
            worker.signals.finished.connect(_cleanup_only)
            timed_out_cleanup_connected["value"] = True
        except Exception:
            timed_out_cleanup_connected["value"] = False
        if not timed_out_cleanup_connected["value"]:
            # Defensive fallback when Qt signal wiring is unavailable during teardown.
            _untrack_worker(worker)
        raise TimeoutError("Background operation timed out before completion.")
    if timed_out["value"] or deadline_missed:
        raise TimeoutError("Background operation timed out before completion.")

    error = result_holder.get("error")
    if error is not None:
        raise error
    return result_holder.get("result")  # type: ignore[return-value]


def run_background(func: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
    """Run a callable on the Qt thread pool (fire-and-forget)."""
    worker = _FireAndForget(func, args, kwargs)
    QThreadPool.globalInstance().start(worker)


def run_background_result(
    func: Callable[..., T],
    on_success: Callable[[T], None],
    on_error: Callable[[Exception], None] | None = None,
    *args: Any,
    **kwargs: Any,
) -> None:
    """Run callable on thread pool and deliver success/error callbacks."""
    _install_app_quit_hook()
    worker = _Worker(func, args, kwargs)
    _track_worker(worker)

    def _dispatch_success(result: T) -> None:
        on_success(result)

    def _dispatch_error(error: Exception) -> None:
        if on_error is None:
            return
        on_error(error)

    def _done(result: object, error: object) -> None:
        _untrack_worker(worker)

        def _deliver() -> None:
            if error is None:
                _dispatch_success(result)  # type: ignore[arg-type]
                return
            if isinstance(error, Exception):
                _dispatch_error(error)
                return
            _dispatch_error(RuntimeError(str(error)))

        app = QApplication.instance()
        if app is not None and not _is_ui_thread(app):
            QTimer.singleShot(0, _deliver)
            return
        _deliver()

    worker.signals.finished.connect(_done)
    QThreadPool.globalInstance().start(worker)


__all__ = [
    "is_qt_object_alive",
    "run_background",
    "run_background_result",
    "run_blocking",
]
