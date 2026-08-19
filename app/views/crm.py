"""Follow-up tab container for visits and contracts."""

from __future__ import annotations

import logging

from PySide6.QtWidgets import QTabWidget, QVBoxLayout, QWidget

from app.utils.i18n import tr_factory
from app.views.crm_contracts import ContractsWidget
from app.views.crm_visits import VisitsWidget
from app.widgets.notice_banner import NoticeBanner
from app.widgets.user_feedback import ActionFeedbackState, UserFacingMessage, show_user_message

logger = logging.getLogger(__name__)
_TR = tr_factory("CRMTab")


class CRMTab(QWidget):
    """Follow-up tab for managing visits and contracts."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._feedback_state = ActionFeedbackState()

        self.tabs = QTabWidget()
        self.tabs.setObjectName("crmFollowupTabs")
        self._notice_banner = NoticeBanner(self)
        self.visits_widget = VisitsWidget(feedback_cb=self._show_feedback)
        self.visits_widget.setObjectName("crmVisitsWidget")
        self.contracts_widget = ContractsWidget(feedback_cb=self._show_feedback)
        self.contracts_widget.setObjectName("crmContractsWidget")

        self.tabs.addTab(self.visits_widget, _TR("📅 Visits"))
        self.tabs.addTab(self.contracts_widget, _TR("🧾 Contracts"))

        layout = QVBoxLayout()
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        layout.addWidget(self._notice_banner)
        layout.addWidget(self.tabs)
        self.setLayout(layout)
        self.tabs.setAccessibleName(_TR("Follow-up tabs"))
        self.destroyed.connect(self._cleanup)

    def refresh(self) -> None:
        """Refresh both sub-tabs."""
        try:
            self.visits_widget.refresh()
        except Exception:
            logger.warning("CRM visits refresh failed", exc_info=True)
        try:
            self.contracts_widget.refresh()
        except Exception:
            logger.warning("CRM contracts refresh failed", exc_info=True)

    def _cleanup(self) -> None:
        """Release tab widgets on shutdown."""
        try:
            self.tabs.clear()
        except RuntimeError:
            pass

    def _show_feedback(
        self, message: UserFacingMessage, auto_dismiss_ms: int | None = None
    ) -> None:
        self._feedback_state.current = message
        self._feedback_state.auto_dismiss_ms = auto_dismiss_ms
        show_user_message(self._notice_banner, message, auto_dismiss_ms=auto_dismiss_ms)
