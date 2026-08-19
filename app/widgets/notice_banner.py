from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from app.utils.i18n import tr_factory

_TR = tr_factory("NoticeBanner")


class NoticeBanner(QFrame):
    dismissed = Signal()
    detailsRequested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("noticeBanner")
        self.setProperty("immoCard", True)
        self.setVisible(False)
        self._auto_dismiss_timer = QTimer(self)
        self._auto_dismiss_timer.setSingleShot(True)
        self._auto_dismiss_timer.timeout.connect(self._dismiss)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        text_layout = QVBoxLayout()
        text_layout.setSpacing(4)
        self.title_label = QLabel("")
        self.title_label.setObjectName("noticeBannerTitle")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.body_label = QLabel("")
        self.body_label.setObjectName("noticeBannerBody")
        self.body_label.setWordWrap(True)
        text_layout.addWidget(self.title_label)
        text_layout.addWidget(self.body_label)
        layout.addLayout(text_layout, 1)

        self.details_btn = QPushButton(_TR("View details"))
        self.details_btn.setObjectName("noticeBannerDetailsButton")
        self.details_btn.setProperty("immoVariant", "ghost")
        self.details_btn.clicked.connect(self.detailsRequested.emit)
        self.details_btn.setVisible(False)
        layout.addWidget(self.details_btn)

        self.dismiss_btn = QPushButton(_TR("Dismiss"))
        self.dismiss_btn.setObjectName("noticeBannerDismissButton")
        self.dismiss_btn.setProperty("immoVariant", "ghost")
        self.dismiss_btn.clicked.connect(self._dismiss)
        layout.addWidget(self.dismiss_btn)

    def show_notice(
        self,
        *,
        state: str,
        title: str,
        body: str,
        show_details: bool = False,
        auto_dismiss_ms: int | None = None,
    ) -> None:
        self.setProperty("immoState", state)
        style = self.style()
        if style is not None:
            style.unpolish(self)
            style.polish(self)
        self.title_label.setText(title)
        self.body_label.setText(body)
        self.details_btn.setVisible(bool(show_details))
        self.setVisible(True)
        self._auto_dismiss_timer.stop()
        if isinstance(auto_dismiss_ms, int) and auto_dismiss_ms > 0:
            self._auto_dismiss_timer.start(auto_dismiss_ms)

    def clear_notice(self) -> None:
        self._auto_dismiss_timer.stop()
        self.title_label.clear()
        self.body_label.clear()
        self.details_btn.setVisible(False)
        self.setVisible(False)

    def _dismiss(self) -> None:
        self.clear_notice()
        self.dismissed.emit()
