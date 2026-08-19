from __future__ import annotations

from unittest.mock import patch

from django.test import Client


def test_health_liveness_endpoint_is_public_and_ok() -> None:
    web = Client()
    response = web.get("/api/v1/health/live/", HTTP_HOST="localhost")
    assert response.status_code == 200
    payload = response.json()
    assert payload.get("alive") is True
    assert payload.get("status") == "ok"


def test_health_readiness_returns_503_when_not_ready() -> None:
    web = Client()
    with patch(
        "server.api.views_health.health_service.readiness",
        return_value={"status": "not_ready", "ready": False, "checks": {}},
    ):
        response = web.get("/api/v1/health/ready/", HTTP_HOST="localhost")
    assert response.status_code == 503
    payload = response.json()
    assert payload.get("ready") is False


def test_health_readiness_returns_200_when_ready() -> None:
    web = Client()
    with patch(
        "server.api.views_health.health_service.readiness",
        return_value={"status": "ready", "ready": True, "checks": {}},
    ):
        response = web.get("/api/v1/health/ready/", HTTP_HOST="localhost")
    assert response.status_code == 200
    payload = response.json()
    assert payload.get("ready") is True
