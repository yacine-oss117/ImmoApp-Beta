"""Recently deleted dialog for recoverable records."""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QLabel, QPushButton, QTabWidget, QVBoxLayout, QWidget

from app.models import Client, Contract, Demande, Listing, Offer, Visit
from app.services.client_repository import fetch_deleted_clients, purge_client, restore_client
from app.services.crm_repository import (
    fetch_deleted_contracts,
    fetch_deleted_visits,
    purge_contract,
    purge_visit,
    restore_contract,
    restore_visit,
)
from app.services.demande_repository import fetch_deleted_demandes, purge_demande, restore_demande
from app.services.listing_repository import fetch_deleted_listings, purge_listing, restore_listing
from app.services.offer_repository import fetch_deleted_offers, purge_offer, restore_offer
from app.utils.i18n import tr_factory
from app.utils.time_humanize import humanize_relative
from app.views.dialogs.trash_table import TrashTable
from app.widgets.workspace_dialog import WorkspaceDialogSpec, apply_workspace_dialog

logger = logging.getLogger(__name__)
_TR = tr_factory("TrashDialog")


class TrashDialog(QDialog):
    """Dialog for managing recently deleted records."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(_TR("Recently Deleted"))
        apply_workspace_dialog(
            self,
            WorkspaceDialogSpec(
                settings_key="dialogs/trash_geometry",
                default_width=1120,
                default_height=760,
                min_width=900,
                min_height=560,
                allow_maximize=True,
            ),
        )

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        header = QLabel(
            _TR("Items deleted in the last 30 days appear here. You can restore them anytime."),
            self,
        )
        header.setWordWrap(True)
        layout.addWidget(header)

        tabs = QTabWidget(self)
        tabs.setAccessibleName(_TR("Recently deleted tabs"))
        tabs.setAccessibleDescription(_TR("Tabs for each record type in recently deleted."))
        self._tabs = tabs
        self._clients_table = self._clients_tab()
        self._listings_table = self._listings_tab()
        self._demandes_table = self._demandes_tab()
        self._offers_table = self._offers_tab()
        self._visits_table = self._visits_tab()
        self._contracts_table = self._contracts_tab()
        tabs.addTab(self._clients_table, _TR("Clients"))
        tabs.addTab(self._listings_table, _TR("Properties"))
        tabs.addTab(self._demandes_table, _TR("Demandes"))
        tabs.addTab(self._offers_table, _TR("Offers"))
        tabs.addTab(self._visits_table, _TR("Visits"))
        tabs.addTab(self._contracts_table, _TR("Contracts"))
        layout.addWidget(tabs, 1)

        close_btn = QPushButton(_TR("Close"), self)
        close_btn.setToolTip(_TR("Close recently deleted"))
        close_btn.setAccessibleName(_TR("Close recently deleted dialog"))
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn, alignment=Qt.AlignmentFlag.AlignRight)

        self.setTabOrder(tabs, close_btn)

    def _clients_tab(self) -> TrashTable[Client]:
        return TrashTable(
            headers=[_TR("ID"), _TR("Name"), _TR("Phone"), _TR("Deleted")],
            fetch_items=self._fetch_deleted_clients,
            render_row=self._render_client,
            restore_item=restore_client,
            purge_item=purge_client,
            parent=self,
        )

    def _listings_tab(self) -> TrashTable[Listing]:
        return TrashTable(
            headers=[_TR("ID"), _TR("Owner"), _TR("Phone"), _TR("Deleted")],
            fetch_items=self._fetch_deleted_listings,
            render_row=self._render_listing,
            restore_item=restore_listing,
            purge_item=purge_listing,
            parent=self,
        )

    def _demandes_tab(self) -> TrashTable[Demande]:
        return TrashTable(
            headers=[
                _TR("ID"),
                _TR("Client ID"),
                _TR("Type"),
                _TR("Action"),
                _TR("Locations"),
                _TR("Deleted"),
            ],
            fetch_items=self._fetch_deleted_demandes,
            render_row=self._render_demande,
            restore_item=restore_demande,
            purge_item=purge_demande,
            parent=self,
        )

    def _offers_tab(self) -> TrashTable[Offer]:
        return TrashTable(
            headers=[
                _TR("ID"),
                _TR("Listing ID"),
                _TR("Type"),
                _TR("Action"),
                _TR("Location"),
                _TR("Deleted"),
            ],
            fetch_items=self._fetch_deleted_offers,
            render_row=self._render_offer,
            restore_item=restore_offer,
            purge_item=purge_offer,
            parent=self,
        )

    def _visits_tab(self) -> TrashTable[Visit]:
        return TrashTable(
            headers=[
                _TR("ID"),
                _TR("Client ID"),
                _TR("Listing ID"),
                _TR("Date"),
                _TR("Status"),
                _TR("Deleted"),
            ],
            fetch_items=self._fetch_deleted_visits,
            render_row=self._render_visit,
            restore_item=restore_visit,
            purge_item=purge_visit,
            parent=self,
        )

    def _contracts_tab(self) -> TrashTable[Contract]:
        return TrashTable(
            headers=[
                _TR("ID"),
                _TR("Client ID"),
                _TR("Listing ID"),
                _TR("Status"),
                _TR("Deleted"),
            ],
            fetch_items=self._fetch_deleted_contracts,
            render_row=self._render_contract,
            restore_item=restore_contract,
            purge_item=purge_contract,
            parent=self,
        )

    @staticmethod
    def _render_client(item: Client) -> list[str]:
        return [
            str(item.id),
            item.family_name,
            item.phone,
            humanize_relative(item.deleted_at),
        ]

    @staticmethod
    def _render_listing(item: Listing) -> list[str]:
        return [
            str(item.id),
            item.family_name,
            item.phone,
            humanize_relative(item.deleted_at),
        ]

    @staticmethod
    def _render_demande(item: Demande) -> list[str]:
        return [
            str(item.id),
            str(item.client_id),
            item.type,
            item.action,
            item.locations,
            humanize_relative(item.deleted_at),
        ]

    @staticmethod
    def _render_offer(item: Offer) -> list[str]:
        return [
            str(item.id),
            str(item.listing_id),
            item.type,
            item.action,
            item.location,
            humanize_relative(item.deleted_at),
        ]

    @staticmethod
    def _render_visit(item: Visit) -> list[str]:
        return [
            str(item.id),
            str(item.client_id),
            str(item.listing_id),
            humanize_relative(item.scheduled_date),
            item.status,
            humanize_relative(item.deleted_at),
        ]

    @staticmethod
    def _render_contract(item: Contract) -> list[str]:
        return [
            str(item.id),
            str(item.client_id),
            str(item.listing_id),
            item.status,
            humanize_relative(item.deleted_at),
        ]

    @staticmethod
    def _fetch_deleted_clients(limit: int, offset: int) -> list[Client]:
        return fetch_deleted_clients(limit=limit, offset=offset)

    @staticmethod
    def _fetch_deleted_listings(limit: int, offset: int) -> list[Listing]:
        return fetch_deleted_listings(limit=limit, offset=offset)

    @staticmethod
    def _fetch_deleted_demandes(limit: int, offset: int) -> list[Demande]:
        return fetch_deleted_demandes(limit=limit, offset=offset)

    @staticmethod
    def _fetch_deleted_offers(limit: int, offset: int) -> list[Offer]:
        return fetch_deleted_offers(limit=limit, offset=offset)

    @staticmethod
    def _fetch_deleted_visits(limit: int, offset: int) -> list[Visit]:
        return fetch_deleted_visits(limit=limit, offset=offset)

    @staticmethod
    def _fetch_deleted_contracts(limit: int, offset: int) -> list[Contract]:
        return fetch_deleted_contracts(limit=limit, offset=offset)
