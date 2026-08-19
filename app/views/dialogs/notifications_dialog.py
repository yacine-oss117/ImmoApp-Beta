"""Notification inbox dialog."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from app.services.notification_severity import severity_for_event_type
from app.services.notifications_repository import (
    clear_notifications,
    fetch_notifications,
    fetch_notifications_page,
    fetch_unread_count,
    mark_notifications_read,
    mark_notifications_unread,
)
from app.utils.i18n import tr_factory
from app.utils.time_humanize import humanize_relative
from app.widgets.workspace_dialog import WorkspaceDialogSpec, apply_workspace_dialog

_TR = tr_factory("NotificationsDialog")


class _NotificationCard(QFrame):
    """Card widget used for notification list items."""

    def __init__(self, item: dict[str, object], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        unread = not bool(item.get("is_read"))
        severity = severity_for_event_type(str(item.get("type") or ""))
        self.setObjectName("NotificationCard_unread" if unread else "NotificationCard")

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        accent = QFrame(self)
        accent.setObjectName(f"notificationCardAccent_{severity}")
        accent.setFixedWidth(4)
        root.addWidget(accent, 0)

        content = QVBoxLayout()
        content.setContentsMargins(0, 8, 10, 8)
        content.setSpacing(4)
        root.addLayout(content, 1)

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(6)

        title = QLabel(str(item.get("title") or ""), self)
        title.setWordWrap(True)
        title.setObjectName("notificationCardTitle")
        title_row.addWidget(title, 1)

        unread_dot = QLabel("\u25cf", self)
        unread_dot.setObjectName("notificationCardUnreadDot")
        unread_dot.setVisible(unread)
        title_row.addWidget(unread_dot, 0, Qt.AlignmentFlag.AlignTop)

        content.addLayout(title_row)

        body = QLabel(str(item.get("body") or ""), self)
        body.setObjectName("notificationCardBody")
        body.setWordWrap(True)
        content.addWidget(body)

        time_text = humanize_relative(str(item.get("created_at") or ""))
        time_label = QLabel(time_text, self)
        time_label.setObjectName("notificationCardTime")
        content.addWidget(time_label)


class NotificationsDialog(QDialog):
    """Notification inbox with card layout and severity filters."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("NotificationsDialog")
        self.setWindowTitle(_TR("Notifications"))
        apply_workspace_dialog(
            self,
            WorkspaceDialogSpec(
                settings_key="dialogs/notifications_geometry",
                default_width=1040,
                default_height=720,
                min_width=860,
                min_height=540,
                allow_maximize=True,
            ),
        )

        self._items: list[dict[str, object]] = []
        self._active_filter = "all"

        self._list = QListWidget(self)
        self._list.setObjectName("notificationsList")
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._list.setAlternatingRowColors(False)

        filter_row = QWidget(self)
        filter_row.setObjectName("NotificationFilterBar")
        filter_layout = QHBoxLayout(filter_row)
        filter_layout.setContentsMargins(0, 0, 0, 0)
        filter_layout.setSpacing(8)
        self._filter_group = QButtonGroup(self)
        self._filter_group.setExclusive(True)
        self._filter_buttons: dict[str, QPushButton] = {}
        for key, label in (
            ("all", _TR("All")),
            ("unread", _TR("Unread")),
            ("info", _TR("Info")),
            ("success", _TR("Success")),
            ("warning", _TR("Warning")),
            ("error", _TR("Error")),
        ):
            btn = QPushButton(label, filter_row)
            btn.setCheckable(True)
            if key == "all":
                btn.setChecked(True)
            btn.clicked.connect(lambda checked, k=key: self._set_filter(k) if checked else None)
            self._filter_group.addButton(btn)
            self._filter_buttons[key] = btn
            filter_layout.addWidget(btn)
        filter_layout.addStretch(1)

        self._empty_state = QWidget(self)
        empty_layout = QVBoxLayout(self._empty_state)
        empty_layout.setContentsMargins(20, 30, 20, 20)
        empty_layout.setSpacing(8)
        self._empty_icon = QLabel("\U0001f514", self._empty_state)
        self._empty_icon.setObjectName("notificationEmptyIcon")
        self._empty_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_text = QLabel(_TR("No notifications yet."), self._empty_state)
        self._empty_text.setObjectName("notificationEmptyText")
        self._empty_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addStretch(1)
        empty_layout.addWidget(self._empty_icon)
        empty_layout.addWidget(self._empty_text)
        empty_layout.addStretch(2)

        self._count_label = QLabel("", self)
        self._count_label.setObjectName("notificationsCountLabel")

        self._refresh_btn = QPushButton(_TR("Refresh"), self)
        self._mark_read_btn = QPushButton(_TR("Mark Read"), self)
        self._mark_unread_btn = QPushButton(_TR("Mark Unread"), self)
        self._mark_all_read_btn = QPushButton(_TR("Mark All Read"), self)
        self._clear_btn = QPushButton(_TR("Clear"), self)
        self._close_btn = QPushButton(_TR("Close"), self)
        self._refresh_btn.setObjectName("notificationsRefreshButton")
        self._mark_read_btn.setObjectName("notificationsMarkReadButton")
        self._mark_unread_btn.setObjectName("notificationsMarkUnreadButton")
        self._mark_all_read_btn.setObjectName("notificationsMarkAllReadButton")
        self._clear_btn.setObjectName("notificationsClearButton")
        self._close_btn.setObjectName("notificationsCloseButton")
        self._refresh_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload))
        self._mark_read_btn.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DialogApplyButton)
        )
        self._mark_unread_btn.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload)
        )
        self._mark_all_read_btn.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DialogYesButton)
        )
        self._clear_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_TrashIcon))
        self._close_btn.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DialogCloseButton)
        )

        self._refresh_btn.clicked.connect(self._refresh)
        self._mark_read_btn.clicked.connect(self._mark_read)
        self._mark_unread_btn.clicked.connect(self._mark_unread)
        self._mark_all_read_btn.clicked.connect(self._mark_all_read)
        self._clear_btn.clicked.connect(self._clear_all)
        self._close_btn.clicked.connect(self.accept)

        layout = QVBoxLayout(self)
        layout.addWidget(filter_row)
        layout.addWidget(self._list)
        layout.addWidget(self._empty_state)
        layout.addWidget(self._count_label)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self._refresh_btn)
        buttons.addWidget(self._mark_read_btn)
        buttons.addWidget(self._mark_unread_btn)
        buttons.addWidget(self._mark_all_read_btn)
        buttons.addWidget(self._clear_btn)
        buttons.addWidget(self._close_btn)
        layout.addLayout(buttons)

        self.latest_total = 0
        self.latest_unread = 0
        self._refresh()

    def _set_filter(self, filter_name: str) -> None:
        self._active_filter = filter_name
        self._render_items()

    def _accept_filter(self, item: dict[str, object]) -> bool:
        if self._active_filter == "all":
            return True
        if self._active_filter == "unread":
            return not bool(item.get("is_read"))
        severity = severity_for_event_type(str(item.get("type") or ""))
        return severity == self._active_filter

    def _render_items(self) -> None:
        self._list.clear()
        filtered = [item for item in self._items if self._accept_filter(item)]
        for item in filtered:
            list_item = QListWidgetItem(self._list)
            notif_id = item.get("id")
            if notif_id is not None:
                list_item.setData(Qt.ItemDataRole.UserRole, notif_id)
            card = _NotificationCard(item, self._list)
            list_item.setSizeHint(card.sizeHint())
            self._list.addItem(list_item)
            self._list.setItemWidget(list_item, card)
        has_items = bool(filtered)
        self._list.setVisible(has_items)
        self._empty_state.setVisible(not has_items)
        self._count_label.setText(
            _TR("Showing: {shown} of {total} • Unread: {unread}").format(
                shown=len(filtered),
                total=self.latest_total,
                unread=self.latest_unread,
            )
        )

    def _refresh(self) -> None:
        pages: list[dict[str, object]] = []
        total = 0
        cursor: int | None = None
        while len(pages) < 500:
            page, page_total, next_cursor = fetch_notifications_page(
                limit=min(200, 500 - len(pages)),
                cursor=cursor,
            )
            if total == 0:
                total = page_total
            pages.extend(page)
            if next_cursor is None:
                break
            cursor = next_cursor
        if not pages and total == 0:
            items, total = fetch_notifications(limit=500, offset=0)
        else:
            items = pages
        self.latest_total = total
        self.latest_unread = fetch_unread_count()
        self._items = list(items)
        self._render_items()

    def _selected_ids(self) -> list[int]:
        ids: list[int] = []
        for list_item in self._list.selectedItems():
            raw = list_item.data(Qt.ItemDataRole.UserRole)
            try:
                ids.append(int(raw))
            except (TypeError, ValueError):
                continue
        return ids

    def _mark_read(self) -> None:
        ids = self._selected_ids()
        if not ids:
            QMessageBox.information(
                self, _TR("Mark Read"), _TR("Select at least one notification.")
            )
            return
        mark_notifications_read(ids)
        self._refresh()

    def _mark_unread(self) -> None:
        ids = self._selected_ids()
        if not ids:
            QMessageBox.information(
                self, _TR("Mark Unread"), _TR("Select at least one notification.")
            )
            return
        mark_notifications_unread(ids)
        self._refresh()

    def _mark_all_read(self) -> None:
        reply = QMessageBox.question(
            self,
            _TR("Mark All Read"),
            _TR("Mark all visible notifications as read?"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        mark_notifications_read(mark_all=True)
        self._refresh()

    def _clear_all(self) -> None:
        reply = QMessageBox.warning(
            self,
            _TR("Clear Notifications"),
            _TR("This will delete all visible notifications.\n\nContinue?"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        before = self.latest_total
        deleted = clear_notifications()
        self._refresh()
        message = _TR("Deleted {count} notifications.").format(count=deleted)
        if self.latest_total > 0 and deleted < before:
            message = _TR(
                "Deleted {count} notifications.\n"
                "Some notifications remain due to permission rules."
            ).format(count=deleted)
        QMessageBox.information(self, _TR("Cleared"), message)


__all__ = ["NotificationsDialog"]
