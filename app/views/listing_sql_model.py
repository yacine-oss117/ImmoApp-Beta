"""
ListingSQLModel - A lazy-loading tree model for Listings.
"""

import logging
import time
from typing import cast

from PySide6.QtCore import QModelIndex, QObject, QPersistentModelIndex, Qt, Signal

from app.models import Listing, Offer
from app.services.api_client import ApiError
from app.services.listing_repository import (
    fetch_listings,
    get_total_listing_count,
    reset_listing_cursor_anchors,
)
from app.services.offer_repository import get_offers_for_listing
from app.utils.i18n import tr_factory
from app.views.listing_sql_model_counts import ListingMatchCountMixin
from app.views.listing_sql_model_render import listing_cell_value, offer_cell_value
from app.views.sql_v2_model import ChildFetchUnavailableError, SQLV2Model

logger = logging.getLogger(__name__)
_PROFILE_THRESHOLD_MS = 100.0
_TR = tr_factory("ListingSQLModel")


class ListingSQLModel(ListingMatchCountMixin, SQLV2Model[Listing, Offer]):
    """Tree model for the Listings tab with lazy-loading rows."""

    # Signals for action buttons
    editListingRequested = Signal(int)
    deleteListingRequested = Signal(int)
    editOfferRequested = Signal(int, int)
    deleteOfferRequested = Signal(int, int)

    COLUMNS = [
        _TR("Owner"),
        _TR("Phone"),
        _TR("Type"),
        _TR("Action"),
        _TR("Location"),
        _TR("Beds"),
        _TR("Surface"),
        _TR("Budget"),
        _TR("Furnished"),
        _TR("Floor"),
        _TR("Created"),
        _TR("Updated"),
        _TR("Actions"),
    ]

    # Roles
    ROLE_NODE_TYPE = int(Qt.ItemDataRole.UserRole) + 2
    ROLE_LISTING_ID = int(Qt.ItemDataRole.UserRole) + 3
    ROLE_OFFER_ID = int(Qt.ItemDataRole.UserRole) + 4

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(
            columns=self.COLUMNS,
            count_fn=lambda: get_total_listing_count(status="available"),
            fetch_fn=lambda limit, offset: fetch_listings(limit, offset, status="available"),
            child_fetch_fn=self._fetch_offers,
            parent=parent,
        )
        self._search_text = ""
        self._init_match_counts()

    def set_filters(self, search: str = "") -> None:
        """Update filters and reload data."""
        self._search_text = search

        self._count_fn = lambda: get_total_listing_count(self._search_text, "available")
        self._fetch_fn = lambda limit, offset: fetch_listings(
            limit, offset, self._search_text, "available"
        )

        self.refresh_data()

    def refresh_data(self) -> None:
        """Reset cache and reload counts/data."""
        self._listing_match_counts.clear()
        self._offer_match_counts.clear()
        reset_listing_cursor_anchors()
        super().refresh_data()
        self._prime_first_page()

    def _prime_first_page(self) -> None:
        """Warm the first visible listing page so the tree is interactive immediately."""
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

        if isinstance(obj, Listing):
            return self._listing_data(obj, col, role)
        elif isinstance(obj, Offer):
            return self._offer_data(obj, col, role)

        return None

    def _listing_data(self, listing: Listing, col: int, role: int) -> object | None:
        cell_value = listing_cell_value(
            listing,
            col,
            role,
            match_counts=self._listing_match_counts,
            tr=_TR,
        )
        if cell_value is not None:
            return cell_value

        if role == self.ROLE_NODE_TYPE:
            return "listing"
        elif role == self.ROLE_LISTING_ID:
            return cast(object, listing.id)

        return None

    def _offer_data(self, offer: Offer, col: int, role: int) -> object | None:
        cell_value = offer_cell_value(
            offer,
            col,
            role,
            match_counts=self._offer_match_counts,
            tr=_TR,
        )
        if cell_value is not None:
            return cell_value

        if role == self.ROLE_NODE_TYPE:
            return "offer"
        elif role == self.ROLE_OFFER_ID:
            return cast(object, offer.id)
        elif role == self.ROLE_LISTING_ID:
            return cast(object, offer.listing_id)

        return None

    def _fetch_offers(self, listing_id: int) -> list[Offer]:
        try:
            offers = get_offers_for_listing(listing_id)
        except (ApiError, RuntimeError) as exc:
            raise ChildFetchUnavailableError(
                _TR(
                    "We couldn't load this property's offers right now. Refresh after reconnecting."
                )
            ) from exc
        missing_ids = [o.id for o in offers if o.id not in self._offer_match_counts]
        if missing_ids:
            self._queue_offer_counts(missing_ids)
        return offers

    def _get_root_obj(self, row: int) -> Listing | None:
        """Override base class to include match counting for the batch."""
        if row in self._root_cache:
            return self._root_cache[row]

        page_start = (row // self._page_size) * self._page_size
        if self._is_page_fetch_throttled(page_start):
            return None
        start = time.perf_counter()
        try:
            new_objs = self._fetch_fn(self._page_size, page_start)
        except Exception:
            self._mark_page_fetch_failed(page_start)
            logger.warning(
                "Failed to fetch listing page starting at %s; throttling retries",
                page_start,
                exc_info=True,
            )
            return None
        fetch_ms = (time.perf_counter() - start) * 1000.0

        listing_ids = [listing.id for listing in new_objs]
        count_start = time.perf_counter()
        self._queue_listing_counts(listing_ids)
        count_ms = (time.perf_counter() - count_start) * 1000.0
        total_ms = (time.perf_counter() - start) * 1000.0
        if total_ms >= _PROFILE_THRESHOLD_MS:
            logger.info(
                "ListingSQLModel page %s size %s: fetch %.1fms count-queue %.1fms total %.1fms",
                page_start,
                len(new_objs),
                fetch_ms,
                count_ms,
                total_ms,
            )

        for i, listing in enumerate(new_objs):
            self._root_cache[page_start + i] = listing

        cached = self._root_cache.get(row)
        return cached if cached else None

    def get_listing_at(self, index: QModelIndex) -> Listing | None:
        if not index.isValid():
            return None
        obj = index.internalPointer()
        if isinstance(obj, Listing):
            return obj
        if isinstance(obj, Offer):
            for listing in self._root_cache.values():
                if listing.id == obj.listing_id:
                    return listing
        return None
