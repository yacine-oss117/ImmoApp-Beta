from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QObject, QPoint, QPropertyAnimation, Qt, QTimer, Signal
from PySide6.QtGui import QCloseEvent, QGuiApplication
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class NotificationToast(QFrame):
    """Small popup toast for notifications."""

    closed = Signal()

    def __init__(
        self,
        title: str,
        body: str,
        *,
        severity: str = "info",
        duration_ms: int = 5000,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        flags = Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self._severity = severity if severity in {"info", "success", "warning", "error"} else "info"
        self.setObjectName(f"NotificationToast_{self._severity}")
        self._duration_ms = max(0, int(duration_ms))
        self._remaining_ms = self._duration_ms
        self._slide_animation: QPropertyAnimation | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 8)
        layout.setSpacing(6)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)

        title_label = QLabel(title, self)
        title_label.setObjectName("notificationToastTitle")
        title_label.setWordWrap(True)
        header.addWidget(title_label, 1)

        close_btn = QPushButton("\u00d7", self)
        close_btn.setObjectName("notificationToastClose")
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.clicked.connect(self.close)
        header.addWidget(close_btn, 0, Qt.AlignmentFlag.AlignTop)

        body_label = QLabel(body, self)
        body_label.setObjectName("notificationToastBody")
        body_label.setWordWrap(True)

        progress = QProgressBar(self)
        progress.setObjectName("notificationToastProgress")
        progress.setTextVisible(False)
        progress.setRange(0, max(1, self._duration_ms))
        progress.setValue(max(0, self._remaining_ms))
        self._progress = progress

        layout.addLayout(header)
        layout.addWidget(body_label)
        layout.addWidget(progress)

        self._progress_timer = QTimer(self)
        self._progress_timer.setInterval(50)
        self._progress_timer.timeout.connect(self._on_progress_tick)
        if self._duration_ms > 0:
            self._progress_timer.start()
        else:
            self._progress.hide()

    def _on_progress_tick(self) -> None:
        self._remaining_ms -= self._progress_timer.interval()
        self._progress.setValue(max(0, self._remaining_ms))
        if self._remaining_ms <= 0:
            self.close()

    def place(self, target: QPoint, *, animate: bool) -> None:
        if animate:
            self.move(QPoint(target.x() + 42, target.y()))
            animation = QPropertyAnimation(self, b"pos", self)
            animation.setDuration(300)
            animation.setEasingCurve(QEasingCurve.Type.OutCubic)
            animation.setStartValue(self.pos())
            animation.setEndValue(target)
            animation.start()
            self._slide_animation = animation
            return
        self.move(target)

    def closeEvent(self, event: QCloseEvent) -> None:
        self._progress_timer.stop()
        super().closeEvent(event)
        self.closed.emit()


class ToastManager(QObject):
    """Manage stacking and positioning of toast notifications."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._toasts: list[NotificationToast] = []
        self._margin = 16
        self._spacing = 10
        self._max_width = 360
        self._max_visible = 4

    def show_toast(
        self,
        title: str,
        body: str,
        *,
        severity: str = "info",
        duration_ms: int = 5000,
    ) -> None:
        if len(self._toasts) >= self._max_visible:
            oldest = self._toasts[0]
            oldest.close()

        toast = NotificationToast(title, body, severity=severity, duration_ms=duration_ms)
        toast.setFixedWidth(self._max_width)
        toast.closed.connect(lambda: self._remove_toast(toast))
        self._toasts.append(toast)
        toast.adjustSize()
        toast.show()
        toast.raise_()
        self._reposition_toasts(animated_toast=toast)

    def _remove_toast(self, toast: NotificationToast) -> None:
        if toast in self._toasts:
            self._toasts.remove(toast)
            self._reposition_toasts(animated_toast=None)

    def _reposition_toasts(self, *, animated_toast: NotificationToast | None) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        geo = screen.availableGeometry()
        y = geo.bottom() - self._margin

        for toast in reversed(self._toasts):
            toast.adjustSize()
            x = geo.right() - self._margin - toast.width()
            y = y - toast.height()
            toast.place(QPoint(x, y), animate=toast is animated_toast)
            y -= self._spacing


__all__ = ["NotificationToast", "ToastManager"]
