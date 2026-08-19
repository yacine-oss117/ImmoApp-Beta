"""
ClientSQLModel - A lazy-loading tree model for Clients.
"""

import logging
import time
from typing import cast

from PySide6.QtCore import QModelIndex, QObject, QPersistentModelIndex, Qt, Signal

from app.models import Client, Demande
from app.services.api_client import ApiError
from app.services.client_repository import (
    fetch_clients,
    get_total_client_count,
    reset_client_cursor_anchors,
)
from app.services.demande_repository import get_demandes_for_client
from app.utils.i18n import tr_factory
from app.views.client_sql_formatting import CLIENT_LIST_FIELDS
from app.views.client_sql_model_counts import ClientMatchCountMixin
from app.views.client_sql_model_render import client_cell_value, demande_cell_value
from app.views.sql_v2_model import ChildFetchUnavailableError, SQLV2Model

logger = logging.getLogger(__name__)
_PROFILE_THRESHOLD_MS = 100.0
_TR = tr_factory("ClientSQLModel")


class ClientSQLModel(ClientMatchCountMixin, SQLV2Model[Client, Demande]):
    """Tree model for the Clients tab with lazy-loading rows."""

    # Signals for action buttons (same as legacy model)
    editClientRequested = Signal(int)
    deleteClientRequested = Signal(int)
    editDemandeRequested = Signal(int, int)
    deleteDemandeRequested = Signal(int, int)

    COLUMNS = [
        _TR("Name"),
        _TR("Phone"),
        _TR("Type"),
        _TR("Action"),
        _TR("Locations"),
        _TR("Beds_min"),
        _TR("Surface_min"),
        _TR("Budget_max"),
        _TR("Furnished"),
        _TR("Created"),
        _TR("Updated"),
        _TR("Remarks"),
        _TR("Actions"),
    ]

    # Roles
    ROLE_NODE_TYPE = int(Qt.ItemDataRole.UserRole) + 2
    ROLE_CLIENT_ID = int(Qt.ItemDataRole.UserRole) + 3
    ROLE_DEMANDE_ID = int(Qt.ItemDataRole.UserRole) + 4

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(
            columns=self.COLUMNS,
            count_fn=lambda: get_total_client_count(status="active"),
            fetch_fn=lambda limit, offset: fetch_clients(
                limit,
                offset,
                status="active",
                fields=CLIENT_LIST_FIELDS,
            ),
            child_fetch_fn=self._fetch_demandes,
            parent=parent,
        )
        self._search_text = ""
        self._init_match_counts()

    def set_filters(self, search: str = "") -> None:
        """Update filters and reload data."""
        self._search_text = search

        # Update function wrappers to include filter params
        self._count_fn = lambda: get_total_client_count(self._search_text, "active")
        self._fetch_fn = lambda limit, offset: fetch_clients(
            limit,
            offset,
            self._search_text,
            "active",
            fields=CLIENT_LIST_FIELDS,
        )
        self.refresh_data()

    def refresh_data(self, match_counts: dict[int, int] | None = None) -> None:
        """Reset cache and reload counts/data."""
        if match_counts is not None:
            self._client_match_counts = match_counts
        else:
            self._client_match_counts.clear()

        # Demandes are counted lazily per client to avoid full-table scans.
        self._demande_match_counts = {}
        reset_client_cursor_anchors()

        super().refresh_data()
        self._prime_first_page()

    def _prime_first_page(self) -> None:
        """Warm the first visible client page so the tree is interactive immediately."""
        if self._total_count <= 0:
            return
        self._get_root_obj(0)

    def data(
        self,
        index: QModelIndex | QPersistentModelIndex,
        role: int = int(Qt.ItemDataRole.DisplayRole),
    ) -> object | None:
        if not index.isValid():
            return None

        obj = index.internalPointer()
        if not obj:
            return None

        status_cell = self.child_status_data(obj, column=index.column(), role=role)
        if status_cell is not None:
            if role == self.ROLE_NODE_TYPE:
                return "status"
            return status_cell

        col = index.column()

        if isinstance(obj, Client):
            return self._client_data(obj, col, role, index.row())
        elif isinstance(obj, Demande):
            return self._demande_data(obj, col, role)

        return None

    def _client_data(self, client: Client, col: int, role: int, row: int) -> object | None:
        cell_value = client_cell_value(
            client,
            col,
            role,
            match_counts=self._client_match_counts,
        )
        if cell_value is not None:
            return cell_value

        if role == self.ROLE_NODE_TYPE:
            return "client"
        elif role == self.ROLE_CLIENT_ID:
            return cast(object, client.id)

        return None

    def _demande_data(self, demande: Demande, col: int, role: int) -> object | None:
        cell_value = demande_cell_value(
            demande,
            col,
            role,
            match_counts=self._demande_match_counts,
        )
        if cell_value is not None:
            return cell_value

        if role == self.ROLE_NODE_TYPE:
            return "demande"
        elif role == self.ROLE_DEMANDE_ID:
            return cast(object, demande.id)
        elif role == self.ROLE_CLIENT_ID:
            return cast(object, demande.client_id)

        return None

    def _fetch_demandes(self, client_id: int) -> list[Demande]:
        demandes = self._child_cache.get(client_id)
        if demandes is None:
            try:
                demandes = get_demandes_for_client(client_id)
            except (ApiError, RuntimeError) as exc:
                raise ChildFetchUnavailableError(
                    _TR(
                        "We couldn't load this client's requests right now. Refresh after reconnecting."
                    )
                ) from exc
            self._child_cache[client_id] = list(demandes)
        missing_ids = [d.id for d in demandes if d.id not in self._demande_match_counts]
        if missing_ids:
            self._queue_demande_counts(missing_ids)
        return list(demandes)

    def _get_root_obj(self, row: int) -> Client | None:
        """Override base class to include match counting for the batch."""
        if row in self._root_cache:
            return self._root_cache[row]

        # Batch fetch around this row
        page_start = (row // self._page_size) * self._page_size
        if self._is_page_fetch_throttled(page_start):
            return None
        start = time.perf_counter()
        try:
            new_objs = self._fetch_fn(self._page_size, page_start)
        except Exception:
            self._mark_page_fetch_failed(page_start)
            logger.warning(
                "Failed to fetch client page starting at %s; throttling retries",
                page_start,
                exc_info=True,
            )
            return None
        fetch_ms = (time.perf_counter() - start) * 1000.0

        # Batch count matches for these specific clients (async)
        client_ids = [c.id for c in new_objs]
        count_start = time.perf_counter()
        self._queue_client_counts(client_ids)
        count_ms = (time.perf_counter() - count_start) * 1000.0
        total_ms = (time.perf_counter() - start) * 1000.0
        if total_ms >= _PROFILE_THRESHOLD_MS:
            logger.info(
                "ClientSQLModel page %s size %s: fetch %.1fms count %.1fms total %.1fms",
                page_start,
                len(new_objs),
                fetch_ms,
                count_ms,
                total_ms,
            )

        for i, client in enumerate(new_objs):
            self._root_cache[page_start + i] = client

        cached = self._root_cache.get(row)
        return cached if cached else None

    def get_client_at(self, index: QModelIndex) -> Client | None:
        if not index.isValid():
            return None
        obj = index.internalPointer()
        if isinstance(obj, Client):
            return obj
        if isinstance(obj, Demande):
            # This is slow if we have to search the cache, but usually it's fine for UI actions
            for c in self._root_cache.values():
                if c.id == obj.client_id:
                    return c
        return None
