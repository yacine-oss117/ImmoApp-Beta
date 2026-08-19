"""
Protocols for main window tab management.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Protocol

from PySide6.QtWidgets import QTabWidget, QWidget

from app.views.dashboard import DashboardTab

if TYPE_CHECKING:
    from app.views.clients_v2 import ClientsTabV2
    from app.views.crm import CRMTab
    from app.views.listings_v2 import ListingsTabV2
    from app.views.match import MatchTab


class TabHostProtocol(Protocol):
    """Common interface for tab host behavior."""

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

    def _navigate_to_match(self, client_id: int) -> None: ...
    def _tab_label(self, tab_id: str) -> str: ...
    def _tab_id_for_index(self, index: int) -> str: ...
    def _create_match_tab(self) -> QWidget: ...
    def _create_clients_tab(self) -> QWidget: ...
    def _create_listings_tab(self) -> QWidget: ...
    def _create_crm_tab(self) -> QWidget: ...
    def _on_tab_changed(self, index: int) -> None: ...
    def _refresh_match_clients(self) -> None: ...
    def _set_current_tab_by_id(self, tab_id: str) -> None: ...
    def _open_clients_tab(self) -> None: ...
    def _open_properties_tab(self) -> None: ...
    def _open_matches_tab(self) -> None: ...
    def _refresh_crm(self) -> None: ...
    def _on_listing_change(self) -> None: ...
    def _ensure_tab_loaded(self, index: int) -> None: ...

    def setCentralWidget(self, widget: QWidget) -> None: ...
    def statusBar(self) -> object: ...


class SwapTrackableProtocol(Protocol):
    """Protocol for widgets that track swap timing."""

    _swap_started_at: float
