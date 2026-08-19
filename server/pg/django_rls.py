"""Ensure Django ORM connections start with safe RLS defaults."""

from __future__ import annotations

from typing import Any

from django.db.backends.signals import connection_created
from django.dispatch import receiver


def _apply_safe_defaults(connection: Any) -> None:
    with connection.cursor() as cursor:
        cursor.execute("RESET ROLE")
        cursor.execute("SET search_path TO public")
        cursor.execute("SELECT set_config('app.current_agency_id', '', false)")
        cursor.execute("SELECT set_config('app.is_superuser', 'false', false)")
        cursor.execute("SELECT set_config('app.audit_actor', '', false)")
        cursor.execute("SELECT set_config('app.actor_id', '', false)")
        cursor.execute("SELECT set_config('app.actor_email', '', false)")
        cursor.execute("SELECT set_config('app.actor_role', '', false)")
        cursor.execute("SELECT set_config('app.actor_is_owner', '', false)")


@receiver(connection_created)
def _on_connection_created(sender: Any, connection: Any, **kwargs: object) -> None:
    _apply_safe_defaults(connection)
