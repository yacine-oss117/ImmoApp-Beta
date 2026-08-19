"""
Match-count helpers for ClientSQLModel.
"""

from __future__ import annotations

import threading
from typing import Protocol, cast

from PySide6.QtCore import QModelIndex, QObject, Qt, SignalInstance

from app.models import Client, Demande
from app.services.match_service import count_matches_for_clients, count_matches_for_demandes
from app.views.sql_match_counts import AsyncCountQueue


class _HasIndex(Protocol):
    def index(self, row: int, column: int, parent: QModelIndex = ...) -> QModelIndex: ...


class ClientMatchCountMixin:
    """Mixin that manages match-count caching for clients and demandes."""

    destroyed: SignalInstance
    dataChanged: SignalInstance
    _root_cache: dict[int, Client]
    _child_cache: dict[int, list[Demande]]

    def _init_match_counts(self) -> None:
        self._client_match_counts: dict[int, int] = {}
        self._demande_match_counts: dict[int, int] = {}
        self._client_count_queue = AsyncCountQueue(
            owner=cast(QObject, self),
            count_fn=count_matches_for_clients,
            apply_fn=self._apply_client_counts,
            label="client",
        )
        self._demande_count_queue = AsyncCountQueue(
            owner=cast(QObject, self),
            count_fn=count_matches_for_demandes,
            apply_fn=self._apply_demande_counts,
            label="demande",
        )
        self._disposed = threading.Event()
        self.destroyed.connect(self._on_destroyed)

    def _on_destroyed(self, _obj: QObject | None = None) -> None:
        self._disposed.set()
        self._client_count_queue.dispose()
        self._demande_count_queue.dispose()

    def _queue_client_counts(self, client_ids: list[int]) -> None:
        if self._disposed.is_set():
            return
        missing_ids = [cid for cid in client_ids if cid not in self._client_match_counts]
        if not missing_ids:
            return
        self._client_count_queue.queue(missing_ids)

    def _queue_demande_counts(self, demande_ids: list[int]) -> None:
        if self._disposed.is_set():
            return
        missing_ids = [did for did in demande_ids if did not in self._demande_match_counts]
        if not missing_ids:
            return
        self._demande_count_queue.queue(missing_ids)

    def _apply_client_counts(self, counts: dict[int, int], batch_ids: list[int]) -> None:
        if self._disposed.is_set():
            return
        self._client_match_counts.update(counts)
        for client_id in batch_ids:
            self._client_match_counts.setdefault(client_id, 0)

        rows = [
            row
            for row, client in self._root_cache.items()
            if isinstance(client, Client) and client.id in batch_ids
        ]
        if not rows:
            return
        indexer = cast(_HasIndex, self)
        for row in rows:
            top_left = indexer.index(row, 0, QModelIndex())
            bottom_right = indexer.index(row, 0, QModelIndex())
            self.dataChanged.emit(top_left, bottom_right, [int(Qt.ItemDataRole.DisplayRole)])

    def _apply_demande_counts(self, counts: dict[int, int], batch_ids: list[int]) -> None:
        if self._disposed.is_set():
            return
        self._demande_match_counts.update(counts)
        for demande_id in batch_ids:
            self._demande_match_counts.setdefault(demande_id, 0)

        for parent_id, demandes in self._child_cache.items():
            parent_row = None
            for row, client in self._root_cache.items():
                if isinstance(client, Client) and client.id == parent_id:
                    parent_row = row
                    break
            if parent_row is None:
                continue
            indexer = cast(_HasIndex, self)
            parent_index = indexer.index(parent_row, 0, QModelIndex())
            for row_idx, demande in enumerate(demandes):
                if isinstance(demande, Demande) and demande.id in batch_ids:
                    top_left = indexer.index(row_idx, 2, parent_index)
                    bottom_right = indexer.index(row_idx, 2, parent_index)
                    self.dataChanged.emit(
                        top_left, bottom_right, [int(Qt.ItemDataRole.DisplayRole)]
                    )


__all__ = ["ClientMatchCountMixin"]
