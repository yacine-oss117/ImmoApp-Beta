from __future__ import annotations

import os
import time
from dataclasses import dataclass

from django.core import signing
from rest_framework import status
from rest_framework.test import APIRequestFactory


def _ensure_django() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "server.immoapp_server.settings")
    import django
    from django.apps import apps

    if not apps.ready:
        django.setup()


@dataclass
class _User:
    id: int = 77
    pk: int = 77
    is_authenticated: bool = True


def test_issue_step_up_token_includes_iat() -> None:
    _ensure_django()
    from server.api.step_up import issue_step_up_token

    token = issue_step_up_token(user_id=77)
    payload = signing.loads(token, salt="immoapp-step-up-v1")
    assert isinstance(payload, dict)
    assert isinstance(payload.get("iat"), int)


def test_parse_step_up_claims_rejects_missing_iat(monkeypatch) -> None:
    _ensure_django()
    from server.api.step_up import parse_step_up_claims

    monkeypatch.setenv("IMMOAPP_REQUIRE_STEP_UP_SENSITIVE", "1")
    token = signing.dumps({"uid": 77, "nonce": "abc"}, salt="immoapp-step-up-v1", compress=True)
    request = APIRequestFactory().post("/api/v1/users/", {}, format="json")
    request.META["HTTP_X_IMMOAPP_STEP_UP"] = token
    request.user = _User()
    _claims, err = parse_step_up_claims(request)
    assert err is not None
    assert err.status_code == status.HTTP_403_FORBIDDEN
    assert err.data.get("code") == "STEP_UP_INVALID"


def test_parse_step_up_claims_rejects_future_iat(monkeypatch) -> None:
    _ensure_django()
    from server.api.step_up import parse_step_up_claims, step_up_clock_skew_seconds

    monkeypatch.setenv("IMMOAPP_REQUIRE_STEP_UP_SENSITIVE", "1")
    future_iat = int(time.time()) + step_up_clock_skew_seconds() + 120
    token = signing.dumps(
        {"uid": 77, "nonce": "abc", "iat": future_iat},
        salt="immoapp-step-up-v1",
        compress=True,
    )
    request = APIRequestFactory().post("/api/v1/users/", {}, format="json")
    request.META["HTTP_X_IMMOAPP_STEP_UP"] = token
    request.user = _User()
    _claims, err = parse_step_up_claims(request)
    assert err is not None
    assert err.status_code == status.HTTP_403_FORBIDDEN
    assert err.data.get("code") == "STEP_UP_INVALID"
