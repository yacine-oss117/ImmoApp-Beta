from __future__ import annotations

import os
from typing import cast

import pytest


def _ensure_django() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "server.immoapp_server.settings")
    import django
    from django.apps import apps

    if not apps.ready:
        django.setup()


def test_secured_view_records_request_latency(monkeypatch: pytest.MonkeyPatch) -> None:
    _ensure_django()
    from rest_framework import status
    from rest_framework.decorators import permission_classes
    from rest_framework.permissions import AllowAny
    from rest_framework.response import Response
    from rest_framework.test import APIRequestFactory

    from server.api.api_view import api_view
    from server.immoapp_server import business_metrics_runtime

    calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        business_metrics_runtime,
        "record_http_request_latency",
        lambda **kwargs: calls.append(dict(kwargs)),
    )

    @api_view(["GET"])
    @permission_classes([AllowAny])
    def _demo(_request: object) -> Response:
        return Response({"ok": True})

    request = APIRequestFactory().get("/api/v1/users/")
    response = cast(Response, _demo(request))
    assert response.status_code == status.HTTP_200_OK
    assert calls
    assert calls[0]["status_code"] == 200
    assert str(calls[0]["outcome"]) == "ok"
    assert str(calls[0]["route_name"]).strip()


def test_secured_view_emits_latency_alert_on_budget_breach(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ensure_django()
    from rest_framework import status
    from rest_framework.decorators import permission_classes
    from rest_framework.permissions import AllowAny
    from rest_framework.response import Response
    from rest_framework.test import APIRequestFactory

    from server.api import secured_view
    from server.api.api_view import api_view
    from server.immoapp_server import business_metrics_runtime
    from server.services import auth_security_alerts, latency_rollups

    alerts: list[dict[str, object]] = []
    monkeypatch.setattr(
        business_metrics_runtime,
        "record_http_request_latency",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        auth_security_alerts,
        "emit_security_alert",
        lambda **kwargs: alerts.append(dict(kwargs)),
    )
    monkeypatch.setattr(
        latency_rollups,
        "record_latency_sample",
        lambda **_kwargs: None,
    )
    monotonic_values = iter([0.0, 1.0])
    monkeypatch.setattr(secured_view.time, "monotonic", lambda: next(monotonic_values))

    @api_view(["GET"])
    @permission_classes([AllowAny])
    def _demo(_request: object) -> Response:
        return Response({"ok": True})

    request = APIRequestFactory().get("/api/v1/users/")
    response = cast(Response, _demo(request))
    assert response.status_code == status.HTTP_200_OK
    assert alerts
    assert alerts[0]["reason_code"] == "route_latency_budget_exceeded"
