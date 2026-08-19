"""WebSocket URL routing."""

from __future__ import annotations

from django.urls import path

from server.api.ws_notifications import NotificationConsumer
from server.api.ws_tasks import TaskStatusConsumer

websocket_urlpatterns = [
    path("ws/tasks/<str:task_id>/", TaskStatusConsumer.as_asgi()),
    path("ws/notifications/", NotificationConsumer.as_asgi()),
]

__all__ = ["websocket_urlpatterns"]
