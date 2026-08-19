from __future__ import annotations

from django.apps import AppConfig


class ApiConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "server.api"

    def ready(self) -> None:
        # Ensure Django ORM connections are RLS-safe by default.
        from server.pg import django_rls  # noqa: F401
