"""
SQLV2Model - A lazy-loading tree model for high-volume data.

This model is designed to handle 100M+ records by only fetching data
from the database as it becomes visible in the UI.
"""

import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Generic, Protocol, TypeVar, cast, overload

from PySide6.QtCore import QAbstractItemModel, QModelIndex, QObject, QPersistentModelIndex, Qt

logger = logging.getLogger(__name__)


class _HasId(Protocol):
    """Protocol for objects that expose an integer id."""

    id: int


@dataclass(frozen=True)
class ChildFetchStatusRow:
    parent_id: int
    message: str


class ChildFetchUnavailableError(RuntimeError):
    """Raised when child rows cannot be fetched and the UI should show a calm inline state."""


T = TypeVar("T", bound=_HasId)
C = TypeVar("C")


class SQLV2Model(QAbstractItemModel, Generic[T, C]):
    """
    Paginated tree model that fetches data from SQL on demand.

    Currently supports a 2-level hierarchy (e.g., Client -> Demandes).
    """

    def __init__(
        self,
        columns: list[str],
        count_fn: Callable[[], int],
        fetch_fn: Callable[[int, int], Sequence[T]],
        child_fetch_fn: Callable[[int], Sequence[C]] | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.columns = columns
        self._count_fn = count_fn
        self._fetch_fn = fetch_fn
        self._child_fetch_fn = child_fetch_fn  # fn(parent_id) -> List[children]

        self._total_count = 0
        self._root_cache: dict[int, T] = {}  # row -> object
        self._child_cache: dict[int, list[C]] = {}  # parent_id -> list of objects
        self._child_fetch_status: dict[int, ChildFetchStatusRow] = {}
        self._page_fetch_backoff_until: dict[int, float] = {}  # page_start -> monotonic deadline
        self._child_fetch_backoff_until: dict[int, float] = {}  # parent_id -> monotonic deadline

        self._page_size = 100

    @staticmethod
    def _is_leaf_child(obj: object) -> bool:
        """Return True when object is already a child node (no nested children)."""
        return hasattr(obj, "client_id") or hasattr(obj, "listing_id")

    def load_data(self) -> None:
        """Initial load - get total count and reset cache."""
        self.refresh_data()

    def refresh_data(self) -> None:
        """Reset cache and reload counts/data."""
        self.beginResetModel()
        self._total_count = self._count_fn()
        self._root_cache.clear()
        self._child_cache.clear()
        self._child_fetch_status.clear()
        self._page_fetch_backoff_until.clear()
        self._child_fetch_backoff_until.clear()
        self.endResetModel()

    def loaded_root_rows(self) -> list[int]:
        """Return currently cached root row indices."""
        return list(self._root_cache.keys())

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex | None = None) -> int:
        """Return the number of rows under the given parent index."""
        if parent is None:
            parent = QModelIndex()
        if not parent.isValid():
            return self._total_count

        # Level 1 (Children)
        parent_obj = parent.internalPointer()
        if parent_obj and hasattr(parent_obj, "id"):
            # Prevent infinite nesting: only root rows can have children.
            if self._is_leaf_child(parent_obj):
                return 0
            # Lazy mode: rowCount should never trigger network/database fetches.
            parent_id = cast(_HasId, parent_obj).id
            cached_children = self._child_cache.get(parent_id)
            if cached_children is not None:
                return len(cached_children)
            return 1 if parent_id in self._child_fetch_status else 0

        return 0

    def columnCount(self, parent: QModelIndex | QPersistentModelIndex | None = None) -> int:
        """Return the number of columns for the children of the given parent."""
        if parent is None:
            parent = QModelIndex()
        return len(self.columns)

    def index(
        self,
        row: int,
        column: int,
        parent: QModelIndex | QPersistentModelIndex | None = None,
    ) -> QModelIndex:
        """Return the index of the item at the specified row and column."""
        if parent is None:
            parent = QModelIndex()
        if row < 0 or column < 0 or column >= len(self.columns):
            return QModelIndex()

        if not parent.isValid():
            # Root level (Clients)
            if row >= self._total_count:
                return QModelIndex()
            obj = self._get_root_obj(row)
            if obj:
                return self.createIndex(row, column, obj)
        else:
            # Child level (Demandes/Offers)
            parent_obj = parent.internalPointer()
            if parent_obj and hasattr(parent_obj, "id"):
                if self._is_leaf_child(parent_obj):
                    return QModelIndex()
                parent_id = cast(_HasId, parent_obj).id
                children = self._child_cache.get(parent_id)
                if children is not None and 0 <= row < len(children):
                    return self.createIndex(row, column, children[row])
                status_row = self._child_fetch_status.get(parent_id)
                if status_row is not None and row == 0:
                    return self.createIndex(row, column, status_row)

        return QModelIndex()

    @overload
    def parent(self) -> QObject: ...

    @overload
    def parent(self, index: QModelIndex | QPersistentModelIndex) -> QModelIndex: ...

    def parent(
        self, index: QModelIndex | QPersistentModelIndex | None = None
    ) -> QObject | QModelIndex:
        """Return the parent of the given model index."""
        if index is None:
            return super().parent()
        if not index.isValid():
            return QModelIndex()

        obj = index.internalPointer()
        if not obj:
            return QModelIndex()

        if isinstance(obj, ChildFetchStatusRow):
            for r, root in self._root_cache.items():
                if root.id == obj.parent_id:
                    return self.createIndex(r, 0, root)
            return QModelIndex()

        # If it's a child (has client_id or listing_id), find parent row
        # This is the tricky part without reverse mapping.
        # For now, let's assume if it's a child, we can find the parent row in cache.

        # Check if it's a 'Demande'
        client_id = getattr(obj, "client_id", None)
        if client_id:
            # Find which row in _root_cache has this client_id
            for r, c in self._root_cache.items():
                if c.id == client_id:
                    return self.createIndex(r, 0, c)

        # Check if it's an 'Offer'
        listing_id = getattr(obj, "listing_id", None)
        if listing_id:
            for r, listing in self._root_cache.items():
                if listing.id == listing_id:
                    return self.createIndex(r, 0, listing)

        return QModelIndex()

    def data(
        self,
        index: QModelIndex | QPersistentModelIndex,
        role: int = int(Qt.ItemDataRole.DisplayRole),
    ) -> object | None:
        """Return the data stored under the given role for the item referred to by the index."""
        if index.isValid():
            status_cell = self.child_status_data(
                index.internalPointer(),
                column=index.column(),
                role=role,
            )
            if status_cell is not None:
                return status_cell
        # Implementation will be specialized in subclasses
        # Note: data() must return object or None for PySide6
        return None

    def hasChildren(self, parent: QModelIndex | QPersistentModelIndex | None = None) -> bool:
        """Cheap child-existence hint without triggering API/DB calls."""
        if parent is None:
            parent = QModelIndex()
        if not parent.isValid():
            return self._total_count > 0

        parent_obj = parent.internalPointer()
        if not (parent_obj and hasattr(parent_obj, "id")):
            return False
        if self._is_leaf_child(parent_obj):
            return False

        parent_id = cast(_HasId, parent_obj).id
        cached_children = self._child_cache.get(parent_id)
        if cached_children is not None:
            return len(cached_children) > 0
        if parent_id in self._child_fetch_status:
            return True
        return self._child_fetch_fn is not None

    def canFetchMore(self, parent: QModelIndex | QPersistentModelIndex) -> bool:
        """Tell Qt that children are lazily fetchable for expanded root rows."""
        if not parent.isValid() or self._child_fetch_fn is None:
            return False

        parent_obj = parent.internalPointer()
        if not (parent_obj and hasattr(parent_obj, "id")):
            return False
        if self._is_leaf_child(parent_obj):
            return False

        parent_id = cast(_HasId, parent_obj).id
        if parent_id in self._child_fetch_status:
            return not self._is_child_fetch_throttled(parent_id)
        return parent_id not in self._child_cache and not self._is_child_fetch_throttled(parent_id)

    def fetchMore(self, parent: QModelIndex | QPersistentModelIndex) -> None:
        """Load children on demand (triggered by row expansion)."""
        if not self.canFetchMore(parent):
            return

        parent_obj = parent.internalPointer()
        if not (parent_obj and hasattr(parent_obj, "id")):
            return
        parent_id = cast(_HasId, parent_obj).id
        if self._is_child_fetch_throttled(parent_id):
            return
        if parent_id in self._child_fetch_status:
            self.beginRemoveRows(parent, 0, 0)
            self._child_fetch_status.pop(parent_id, None)
            self.endRemoveRows()

        try:
            children = list(self._child_fetch_fn(parent_id)) if self._child_fetch_fn else []
        except Exception as exc:  # pragma: no cover - defensive UI stability guard
            self._mark_child_fetch_failed(parent_id)
            self._set_child_fetch_status(
                parent=parent,
                parent_id=parent_id,
                message=self._child_fetch_error_message(exc),
            )
            if isinstance(exc, ChildFetchUnavailableError):
                logger.warning(
                    "Failed to fetch children for parent id=%s; throttling retries",
                    parent_id,
                )
            else:
                logger.warning(
                    "Failed to fetch children for parent id=%s; throttling retries",
                    parent_id,
                    exc_info=True,
                )
            return

        if not children:
            self._child_cache[parent_id] = []
            return

        self.beginInsertRows(parent, 0, len(children) - 1)
        self._child_cache[parent_id] = children
        self.endInsertRows()

    def _get_root_obj(self, row: int) -> T | None:
        if row in self._root_cache:
            return self._root_cache[row]

        # Batch fetch around this row
        page_start = (row // self._page_size) * self._page_size
        if self._is_page_fetch_throttled(page_start):
            return None
        try:
            new_objs = list(self._fetch_fn(self._page_size, page_start))
        except Exception:  # pragma: no cover - UI stability guard
            self._mark_page_fetch_failed(page_start)
            logger.exception("Failed to fetch root page starting at row %s", page_start)
            return None

        for i, obj in enumerate(new_objs):
            self._root_cache[page_start + i] = obj

        return self._root_cache.get(row)

    def _is_page_fetch_throttled(self, page_start: int) -> bool:
        """Return True when recent failures should temporarily throttle this page fetch."""
        blocked_until = self._page_fetch_backoff_until.get(page_start)
        if blocked_until is None:
            return False
        if blocked_until <= time.monotonic():
            self._page_fetch_backoff_until.pop(page_start, None)
            return False
        return True

    def _mark_page_fetch_failed(self, page_start: int, *, cooldown_seconds: float = 2.0) -> None:
        """Throttle repeated failing fetches to avoid exception/log storms in Qt paint loops."""
        self._page_fetch_backoff_until[page_start] = time.monotonic() + max(
            0.1, float(cooldown_seconds)
        )

    def _is_child_fetch_throttled(self, parent_id: int) -> bool:
        blocked_until = self._child_fetch_backoff_until.get(parent_id)
        if blocked_until is None:
            return False
        if blocked_until <= time.monotonic():
            self._child_fetch_backoff_until.pop(parent_id, None)
            return False
        return True

    def _mark_child_fetch_failed(self, parent_id: int, *, cooldown_seconds: float = 5.0) -> None:
        self._child_fetch_backoff_until[parent_id] = time.monotonic() + max(
            0.5, float(cooldown_seconds)
        )

    def _set_child_fetch_status(
        self,
        *,
        parent: QModelIndex | QPersistentModelIndex,
        parent_id: int,
        message: str,
    ) -> None:
        status_row = ChildFetchStatusRow(parent_id=parent_id, message=message)
        if parent_id in self._child_fetch_status:
            self._child_fetch_status[parent_id] = status_row
            return
        self.beginInsertRows(parent, 0, 0)
        self._child_fetch_status[parent_id] = status_row
        self.endInsertRows()

    @staticmethod
    def _child_fetch_error_message(exc: Exception) -> str:
        text = str(exc or "").strip()
        if text:
            return text
        return "We couldn't load related lines right now. Refresh after reconnecting."

    @staticmethod
    def child_status_data(
        obj: object,
        *,
        column: int,
        role: int,
    ) -> object | None:
        if not isinstance(obj, ChildFetchStatusRow):
            return None
        if role == int(Qt.ItemDataRole.DisplayRole):
            return obj.message if column == 0 else ""
        if role == int(Qt.ItemDataRole.ToolTipRole):
            return obj.message
        return None

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = int(Qt.ItemDataRole.DisplayRole),
    ) -> object | None:
        """Return the data for the given role and section in the header with the specified orientation."""
        if orientation == Qt.Orientation.Horizontal and role == int(Qt.ItemDataRole.DisplayRole):
            if 0 <= section < len(self.columns):
                return self.columns[section]
        return None
