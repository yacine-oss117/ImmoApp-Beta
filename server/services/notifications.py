"""
Notification persistence facade (queries + mutations).
"""

from server.services.notifications_mutations import (
    clear_visible_notifications,
    insert_notification,
    insert_notification_in_atomic,
    mark_notifications_read,
    mark_notifications_unread,
    purge_notifications_older_than,
)
from server.services.notifications_queries import (
    count_notifications,
    count_unread_notifications,
    get_notifications_scope_generations,
    list_notification_items,
    list_notification_items_with_total,
    list_notifications,
    list_notifications_with_total,
)

__all__ = [
    "clear_visible_notifications",
    "count_notifications",
    "count_unread_notifications",
    "get_notifications_scope_generations",
    "insert_notification",
    "insert_notification_in_atomic",
    "list_notification_items",
    "list_notification_items_with_total",
    "list_notifications",
    "list_notifications_with_total",
    "mark_notifications_read",
    "mark_notifications_unread",
    "purge_notifications_older_than",
]
