"""
Smart Dashboard - The agent's daily cockpit.

Shows:
- Today's Visits (scheduled for today)
- Expiring Contracts (ending within 7 days)
- Hot Leads (clients with 5+ matches)
- Quick Stats (totals for clients, listings, visits, contracts)
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from functools import partial

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from app.services.onboarding_analytics import (
    dismiss_next_steps_card,
    record_onboarding_event,
    should_show_next_steps_card,
)
from app.utils.i18n import tr_factory
from app.views.dashboard_cards import (
    create_contract_card_from_dict,
    create_lead_card_from_dict,
    create_pending_contract_card_from_dict,
    create_visit_card_from_dict,
)
from app.views.dashboard_ui import DashboardUi, build_dashboard_ui

logger = logging.getLogger(__name__)
_TR = tr_factory("DashboardTab")


class DashboardTab(QWidget):
    """Dashboard tab showing summary cards and fast-refresh notices."""

    def __init__(
        self,
        parent: QWidget | None = None,
        on_lead_click_cb: Callable[[int], None] | None = None,
        on_open_clients_cb: Callable[[], None] | None = None,
        on_open_properties_cb: Callable[[], None] | None = None,
        on_open_matches_cb: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.on_lead_click_cb = on_lead_click_cb
        self.on_open_clients_cb = on_open_clients_cb
        self.on_open_properties_cb = on_open_properties_cb
        self.on_open_matches_cb = on_open_matches_cb
        self._notice_text = ""
        self._ui: DashboardUi = build_dashboard_ui(
            self,
            self.refresh_stats,
            on_open_clients=self._open_clients,
            on_open_properties=self._open_properties,
            on_open_matches=self._open_matches,
            on_hide_next_steps=self._hide_next_steps,
        )
        self.refresh_stats()
        self.destroyed.connect(self._cleanup)

    def _open_clients(self) -> None:
        if self.on_open_clients_cb:
            self.on_open_clients_cb()

    def _open_properties(self) -> None:
        if self.on_open_properties_cb:
            self.on_open_properties_cb()

    def _open_matches(self) -> None:
        if self.on_open_matches_cb:
            self.on_open_matches_cb()

    def _hide_next_steps(self) -> None:
        dismiss_next_steps_card(dismissed=True)
        self._ui.next_steps_card.setVisible(False)
        record_onboarding_event("next_steps_hidden", step="dashboard", outcome="dismissed")

    def _on_lead_clicked(self, lead: dict[str, object]) -> None:
        """Handle click on hot lead card."""
        if self.on_lead_click_cb:
            client_id_obj = lead.get("client_id")
            client_id = client_id_obj if isinstance(client_id_obj, int) else 0
            if client_id:
                self.on_lead_click_cb(client_id)

    @staticmethod
    def _clear_layout(layout: QVBoxLayout) -> None:
        """Clear all widgets from a layout."""
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

    def refresh_stats(self) -> None:
        """Refresh all dashboard data using batched cache."""
        from app.services.dashboard_cache import (
            get_dashboard_stats,
            is_cache_stale,
            refresh_dashboard_stats,
        )

        stats = get_dashboard_stats()

        if is_cache_stale():
            try:
                stats = refresh_dashboard_stats()
            except RuntimeError:
                logger.error("Dashboard refresh failed", exc_info=True)
                self.set_notice(_TR("Couldn't refresh right now. Showing saved data."))
        if getattr(stats, "last_error", None):
            self.set_notice(str(stats.last_error))

        self._ui.stat_clients.setText(f"{stats.client_count:,}")
        self._ui.stat_listings.setText(f"{stats.listing_count:,}")
        self._ui.stat_visits.setText(f"{len(stats.today_visits)}")
        self._ui.stat_contracts.setText(
            f"{len(stats.pending_contracts) + len(stats.expiring_contracts)}"
        )

        self._sync_next_steps_card(stats.client_count, stats.listing_count)

        self._clear_layout(self._ui.pending_container)
        if stats.pending_contracts:
            for c in stats.pending_contracts[:5]:
                self._ui.pending_container.addWidget(
                    create_pending_contract_card_from_dict(self, c)
                )
        else:
            lbl = QLabel(_TR("No pending contracts"), self)
            lbl.setProperty("immoEmptyState", True)
            self._ui.pending_container.addWidget(lbl)

        self._clear_layout(self._ui.visits_container)
        if stats.today_visits:
            for v in stats.today_visits[:5]:
                self._ui.visits_container.addWidget(create_visit_card_from_dict(self, v))
        else:
            no_visits = QLabel(_TR("No visits scheduled for today"), self)
            no_visits.setProperty("immoEmptyState", True)
            self._ui.visits_container.addWidget(no_visits)

        self._clear_layout(self._ui.contracts_container)
        if stats.expiring_contracts:
            for c in stats.expiring_contracts[:5]:
                self._ui.contracts_container.addWidget(create_contract_card_from_dict(self, c))
        else:
            no_contracts = QLabel(_TR("No contracts ending soon"), self)
            no_contracts.setProperty("immoEmptyState", True)
            self._ui.contracts_container.addWidget(no_contracts)

        self._clear_layout(self._ui.leads_container)
        if stats.hot_leads:
            for lead in stats.hot_leads[:5]:
                self._ui.leads_container.addWidget(
                    create_lead_card_from_dict(self, lead, partial(self._on_lead_clicked, lead))
                )
        else:
            no_leads = QLabel(_TR("No new opportunities yet"), self)
            no_leads.setProperty("immoEmptyState", True)
            self._ui.leads_container.addWidget(no_leads)

        self._ui.notice_banner.setText(self._notice_text)
        self._ui.notice_banner.setVisible(bool(self._notice_text))

    def _sync_next_steps_card(self, client_count: int, listing_count: int) -> None:
        if not should_show_next_steps_card():
            self._ui.next_steps_card.setVisible(False)
            return

        recommended = "clients"
        hint = _TR("Start by adding a client, then add a property, then run matching.")
        can_open_matches = False
        can_open_properties = False
        if client_count > 0 and listing_count <= 0:
            hint = _TR("Great start. Add a property now so matching can begin.")
            recommended = "properties"
            can_open_properties = True
        elif client_count > 0 and listing_count > 0:
            hint = _TR("Nice progress. You can now run matching.")
            recommended = "matches"
            can_open_properties = True
            can_open_matches = True

        self._ui.next_steps_hint.setText(hint)
        self._apply_next_step_button_state(
            self._ui.next_steps_clients_btn,
            enabled=True,
            recommended=recommended == "clients",
        )
        self._apply_next_step_button_state(
            self._ui.next_steps_properties_btn,
            enabled=can_open_properties,
            recommended=recommended == "properties",
        )
        self._apply_next_step_button_state(
            self._ui.next_steps_matches_btn,
            enabled=can_open_matches,
            recommended=recommended == "matches",
        )
        self._ui.next_steps_matches_btn.setToolTip(
            ""
            if can_open_matches
            else _TR("Add at least one client and one property to run matching.")
        )
        for btn in (
            self._ui.next_steps_clients_btn,
            self._ui.next_steps_properties_btn,
            self._ui.next_steps_matches_btn,
        ):
            style = btn.style()
            if style is not None:
                style.unpolish(btn)
                style.polish(btn)
        self._ui.next_steps_card.setVisible(True)

    @staticmethod
    def _apply_next_step_button_state(
        button: QWidget,
        *,
        enabled: bool,
        recommended: bool,
    ) -> None:
        button.setEnabled(enabled)
        if not enabled:
            button.setProperty("immoVariant", "ghost")
            return
        button.setProperty("immoVariant", "primary" if recommended else "secondary")

    def set_notice(self, text: str) -> None:
        """Show or clear a small notice banner on the dashboard."""
        self._notice_text = (text or "").strip()
        self._ui.notice_banner.setText(self._notice_text)
        self._ui.notice_banner.setVisible(bool(self._notice_text))

    def _cleanup(self) -> None:
        """Clear heavy dashboard layouts on shutdown."""
        self._clear_layout(self._ui.pending_container)
        self._clear_layout(self._ui.visits_container)
        self._clear_layout(self._ui.contracts_container)
        self._clear_layout(self._ui.leads_container)
