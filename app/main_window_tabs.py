"""Main window mixin for tab management and lazy loading."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, cast

from PySide6.QtWidgets import QTabWidget, QVBoxLayout, QWidget

from app.main_window_tab_helpers import (
    ensure_tab_loaded,
    navigate_to_match,
    preload_all_tabs,
    prepare_for_db_swap,
    refresh_all_tabs,
    schedule_post_startup_prewarm,
    tab_id_for_index,
    track_first_paint,
)
from app.main_window_tabs_types import TabHostProtocol
from app.utils.i18n import tr_factory
from app.views.dashboard import DashboardTab
from app.widgets.splash_shared import WARM_TABS

if TYPE_CHECKING:
    from app.views.clients_v2 import ClientsTabV2
    from app.views.crm import CRMTab
    from app.views.listings_v2 import ListingsTabV2
    from app.views.match import MatchTab

logger = logging.getLogger(__name__)
_TR = tr_factory("MainWindowTabs")

_TAB_IDS = ("Dashboard", "Match", "Clients", "Listings", "CRM")


class MainWindowTabMixin:
    """Handles tab creation, lazy loading, and refresh logic."""

    WARM_TABS = WARM_TABS
    tabs: QTabWidget
    _loaded_tabs: dict[str, QWidget]
    _tab_factories: dict[str, Callable[[], QWidget]]
    _post_startup_prewarm_scheduled: bool
    _tab_load_in_progress: set[str]
    _prewarm_running: bool
    _tab_containers: dict[str, QWidget]
    dashboard_tab: DashboardTab
    match_tab: MatchTab | None
    clients_tab: ClientsTabV2 | None
    listings_tab: ListingsTabV2 | None
    crm_tab: CRMTab | None

    def _init_tabs(self: TabHostProtocol) -> None:
        parent_widget = cast(QWidget, getattr(self, "_host", self))
        self.tabs = QTabWidget(parent_widget)
        self.tabs.setObjectName("immoMainTabs")
        self.tabs.setAccessibleName(_TR("Main tabs"))
        self.tabs.setAccessibleDescription(_TR("Primary navigation tabs for the application."))
        self._loaded_tabs = {}
        self._tab_factories = {}
        self.match_tab = None
        self.clients_tab = None
        self.listings_tab = None
        self.crm_tab = None
        self._post_startup_prewarm_scheduled = False
        self._tab_load_in_progress = set()
        self._prewarm_running = False
        self._tab_containers = {}

        # Load only the dashboard immediately; other tabs are loaded on first click to speed startup
        self.dashboard_tab = DashboardTab(
            on_lead_click_cb=self._navigate_to_match,
            on_open_clients_cb=self._open_clients_tab,
            on_open_properties_cb=self._open_properties_tab,
            on_open_matches_cb=self._open_matches_tab,
        )
        dash_index = self.tabs.addTab(self.dashboard_tab, self._tab_label("Dashboard"))
        self.tabs.tabBar().setTabData(dash_index, "Dashboard")
        self._loaded_tabs["Dashboard"] = self.dashboard_tab

        self._tab_factories = {
            "Match": self._create_match_tab,
            "Clients": self._create_clients_tab,
            "Listings": self._create_listings_tab,
            "CRM": self._create_crm_tab,
        }
        for tab_id in ("Match", "Clients", "Listings", "CRM"):
            logger.debug("Initializing tab: %s", tab_id)
            factory = self._tab_factories[tab_id]
            widget = factory()
            container = QWidget(self.tabs)
            container.setObjectName(f"immoMainTabContainer_{tab_id}")
            container_layout = QVBoxLayout(container)
            container_layout.setContentsMargins(0, 0, 0, 0)
            container_layout.addWidget(widget)
            self._tab_containers[tab_id] = container
            index = self.tabs.addTab(container, self._tab_label(tab_id))
            self.tabs.tabBar().setTabData(index, tab_id)
            self._loaded_tabs[tab_id] = widget

        self.tabs.currentChanged.connect(self._on_tab_changed)
        self.setCentralWidget(self.tabs)

    def _tab_label(self, tab_id: str) -> str:
        labels = {
            "Dashboard": _TR("Dashboard"),
            "Match": _TR("Matches"),
            "Clients": _TR("Clients"),
            "Listings": _TR("Properties"),
            "CRM": _TR("Follow-up"),
        }
        return labels.get(tab_id, tab_id)

    def schedule_post_startup_prewarm(self: TabHostProtocol) -> None:
        schedule_post_startup_prewarm(self, WARM_TABS)

    def _tab_id_for_index(self: TabHostProtocol, index: int) -> str:
        return tab_id_for_index(self, index)

    def _add_placeholder_tab(self: TabHostProtocol, tab_id: str) -> None:
        """No-op placeholder hook (tabs are created eagerly)."""
        return

    def _create_match_tab(self: TabHostProtocol) -> QWidget:
        from app.views.match import MatchTab

        match_tab = MatchTab(refresh_crm_cb=self._refresh_crm, parent=self.tabs)
        self.match_tab = match_tab
        return match_tab

    def _create_clients_tab(self: TabHostProtocol) -> QWidget:
        # Use V2 with QTreeView for 60fps performance
        from app.views.clients_v2 import ClientsTabV2

        clients_tab = ClientsTabV2(refresh_clients_cb=self._refresh_match_clients, parent=self.tabs)
        self.clients_tab = clients_tab
        return clients_tab

    def _create_listings_tab(self: TabHostProtocol) -> QWidget:
        # Use V2 with QTreeView for 60fps performance (matches ClientsTabV2)
        from app.views.listings_v2 import ListingsTabV2

        listings_tab = ListingsTabV2(
            refresh_match_counts_cb=self._on_listing_change, parent=self.tabs
        )
        self.listings_tab = listings_tab
        return listings_tab

    def _create_crm_tab(self: TabHostProtocol) -> QWidget:
        from app.views.crm import CRMTab

        crm_tab = CRMTab(parent=self.tabs)
        self.crm_tab = crm_tab
        return crm_tab

    def _ensure_tab_loaded(self: TabHostProtocol, index: int) -> None:
        ensure_tab_loaded(self, index)

    def preload_all_tabs(
        self: TabHostProtocol, progress_callback: Callable[[int, int, str], None] | None = None
    ) -> None:
        preload_all_tabs(self, _TAB_IDS, progress_callback)

    def _refresh_all_tabs(self: TabHostProtocol) -> None:
        refresh_all_tabs(self)

    def _prepare_for_db_swap(self: TabHostProtocol) -> bool:
        return prepare_for_db_swap(self)

    def _navigate_to_match(self: TabHostProtocol, client_id: int) -> None:
        navigate_to_match(self, client_id)

    def _on_listing_change(self: TabHostProtocol) -> None:
        if self.match_tab is not None:
            self.match_tab._match_counts_dirty = True
        self.dashboard_tab.refresh_stats()

    def _on_tab_changed(self: TabHostProtocol, index: int) -> None:
        if self._prewarm_running:
            return
        self._ensure_tab_loaded(index)
        tab_id = self._tab_id_for_index(index)
        track_first_paint(self, index)

        if tab_id == "Dashboard" and hasattr(self, "dashboard_tab"):
            self.dashboard_tab.refresh_stats()
            return

        if tab_id == "Match" and self.match_tab is not None:
            self.match_tab.refresh_clients()
            return
        if tab_id == "Clients" and self.clients_tab is not None:
            return
        if tab_id == "Listings" and self.listings_tab is not None:
            return

    def _refresh_match_clients(self: TabHostProtocol) -> None:
        if self.match_tab is not None:
            self.match_tab.refresh_clients()

    def _set_current_tab_by_id(self: TabHostProtocol, tab_id: str) -> None:
        for index in range(self.tabs.count()):
            candidate = self._tab_id_for_index(index)
            if candidate == tab_id:
                self.tabs.setCurrentIndex(index)
                return

    def _open_clients_tab(self: TabHostProtocol) -> None:
        self._set_current_tab_by_id("Clients")

    def _open_properties_tab(self: TabHostProtocol) -> None:
        self._set_current_tab_by_id("Listings")

    def _open_matches_tab(self: TabHostProtocol) -> None:
        self._set_current_tab_by_id("Match")

    def _refresh_crm(self: TabHostProtocol) -> None:
        """Refresh CRM tab after visit/contract creation."""
        if self.crm_tab is not None:
            self.crm_tab.refresh()
