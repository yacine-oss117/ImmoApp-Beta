from __future__ import annotations

import os
from collections.abc import Iterator

import django
from django.conf import settings
from django.urls import URLPattern, URLResolver


def _setup_django() -> None:
    if settings.configured:
        return
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "server.immoapp_server.settings")
    django.setup()


def _iter_callbacks(
    patterns: list[URLPattern | URLResolver],
) -> Iterator[tuple[str, object]]:
    for pattern in patterns:
        if isinstance(pattern, URLResolver):
            yield from _iter_callbacks(pattern.url_patterns)
        else:
            yield (str(pattern.pattern), pattern.callback)


def test_api_routes_are_secured_or_explicitly_allowlisted() -> None:
    _setup_django()
    from server.api.middleware_security import PUBLIC_API_ALLOW_LIST
    from server.api.urls import urlpatterns  # type: ignore

    public_routes = {"health/", "health/live/", "health/ready/", "health/snapshot/"}
    # This endpoint is intentionally unsecured to prove default-deny middleware.
    intentionally_unsecured = {"firewall-verification/"}
    allowlisted = set(PUBLIC_API_ALLOW_LIST)

    unsecured: list[str] = []
    for route, callback in _iter_callbacks(urlpatterns):
        if route in public_routes or route in intentionally_unsecured:
            continue
        if getattr(callback, "_is_explicitly_secured", False):
            continue
        callback_name = getattr(callback, "__name__", "<unknown>")
        if callback_name in allowlisted:
            continue
        unsecured.append(route)
    assert not unsecured, f"Unsecured API routes found: {sorted(unsecured)}"
