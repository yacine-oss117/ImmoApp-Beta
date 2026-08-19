"""
Match-count helpers for ListingSQLModel.
"""

from __future__ import annotations

import threading
from typing import Protocol, cast

from PySide6.QtCore import QModelIndex, QObject, Qt, SignalInstance

from app.models import Listing, Offer
from app.services.match_service import count_matches_for_listings, count_matches_for_offers
from app.views.sql_match_counts import AsyncCountQueue


class _HasIndex(Protocol):
    def index(self, row: int, column: int, parent: QModelIndex = ...) -> QModelIndex: ...


class ListingMatchCountMixin:
    """Mixin that manages match-count caching for listings and offers."""

    destroyed: SignalInstance
    dataChanged: SignalInstance
    _root_cache: dict[int, Listing]
    _child_cache: dict[int, list[Offer]]

    def _init_match_counts(self) -> None:
        self._listing_match_counts: dict[int, int] = {}
        self._offer_match_counts: dict[int, int] = {}
        self._listing_count_queue = AsyncCountQueue(
            owner=cast(QObject, self),
            count_fn=count_matches_for_listings,
            apply_fn=self._apply_listing_counts,
            label="listing",
        )
        self._offer_count_queue = AsyncCountQueue(
            owner=cast(QObject, self),
            count_fn=count_matches_for_offers,
            apply_fn=self._apply_offer_counts,
            label="offer",
        )
        self._disposed = threading.Event()
        self.destroyed.connect(self._on_destroyed)

    def _on_destroyed(self, _obj: QObject | None = None) -> None:
        self._disposed.set()
        self._listing_count_queue.dispose()
        self._offer_count_queue.dispose()

    def _queue_listing_counts(self, listing_ids: list[int]) -> None:
        if self._disposed.is_set():
            return
        missing_ids = [lid for lid in listing_ids if lid not in self._listing_match_counts]
        if not missing_ids:
            return
        self._listing_count_queue.queue(missing_ids)

    def _apply_listing_counts(self, counts: dict[int, int], batch_ids: list[int]) -> None:
        if self._disposed.is_set():
            return
        self._listing_match_counts.update(counts)
        for listing_id in batch_ids:
            self._listing_match_counts.setdefault(listing_id, 0)

        rows = [
            row
            for row, listing in self._root_cache.items()
            if isinstance(listing, Listing) and listing.id in batch_ids
        ]
        if not rows:
            return
        indexer = cast(_HasIndex, self)
        for row in rows:
            top_left = indexer.index(row, 0, QModelIndex())
            bottom_right = indexer.index(row, 0, QModelIndex())
            self.dataChanged.emit(top_left, bottom_right, [int(Qt.ItemDataRole.DisplayRole)])

    def _queue_offer_counts(self, offer_ids: list[int]) -> None:
        if self._disposed.is_set():
            return
        missing_ids = [oid for oid in offer_ids if oid not in self._offer_match_counts]
        if not missing_ids:
            return
        self._offer_count_queue.queue(missing_ids)

    def _apply_offer_counts(self, counts: dict[int, int], batch_ids: list[int]) -> None:
        if self._disposed.is_set():
            return
        self._offer_match_counts.update(counts)
        for offer_id in batch_ids:
            self._offer_match_counts.setdefault(offer_id, 0)

        for parent_id, offers in self._child_cache.items():
            parent_row = None
            for row, listing in self._root_cache.items():
                if isinstance(listing, Listing) and listing.id == parent_id:
                    parent_row = row
                    break
            if parent_row is None:
                continue
            indexer = cast(_HasIndex, self)
            parent_index = indexer.index(parent_row, 0, QModelIndex())
            for row_idx, offer in enumerate(offers):
                if isinstance(offer, Offer) and offer.id in batch_ids:
                    top_left = indexer.index(row_idx, 2, parent_index)
                    bottom_right = indexer.index(row_idx, 2, parent_index)
                    self.dataChanged.emit(
                        top_left, bottom_right, [int(Qt.ItemDataRole.DisplayRole)]
                    )
