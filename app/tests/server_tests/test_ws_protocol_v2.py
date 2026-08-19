from __future__ import annotations

import os

import django
from django.apps import apps
from django.conf import settings

from core.contracts.ws_protocol import (
    WS_CLOSE_BAD_REQUEST,
    WS_CLOSE_FORBIDDEN,
    WS_CLOSE_UNAUTHORIZED,
)
from server.api import ws_protocol
from server.api.ws_auth import _extract_token_exp
from server.api.ws_protocol import (
    CONTROL_FIELD,
    CONTROL_HEARTBEAT,
    control_payload,
    scope_supports_v2,
)


def _setup_django() -> None:
    if apps.ready:
        return
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "server.immoapp_server.settings")
    if not settings.configured:
        django.setup()
        return
    django.setup(set_prefix=False)


def test_scope_supports_v2_when_query_flag_present() -> None:
    scope = {"query_string": b"schema=public&ws_v=2"}
    assert scope_supports_v2(scope) is True


def test_scope_supports_v2_when_query_flag_missing() -> None:
    scope = {"query_string": b"schema=public"}
    assert scope_supports_v2(scope) is False


def test_control_payload_sets_control_key() -> None:
    payload = control_payload(CONTROL_HEARTBEAT, ts=123)
    assert payload[CONTROL_FIELD] == CONTROL_HEARTBEAT
    assert payload["ts"] == 123


def test_extract_token_exp_invalid_token_returns_none() -> None:
    _setup_django()
    assert _extract_token_exp("not-a-token") is None


def test_server_ws_close_codes_match_shared_contract() -> None:
    assert ws_protocol.WS_CLOSE_BAD_REQUEST == WS_CLOSE_BAD_REQUEST
    assert ws_protocol.WS_CLOSE_UNAUTHORIZED == WS_CLOSE_UNAUTHORIZED
    assert ws_protocol.WS_CLOSE_FORBIDDEN == WS_CLOSE_FORBIDDEN
