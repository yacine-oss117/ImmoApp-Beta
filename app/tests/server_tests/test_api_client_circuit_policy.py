from __future__ import annotations

import importlib


def _reload_circuit_module():
    import app.services.api_client_circuit as circuit

    return importlib.reload(circuit)


def test_should_retry_status_excludes_http_500() -> None:
    circuit = _reload_circuit_module()
    assert circuit.should_retry_status(500) is False


def test_should_retry_status_keeps_transient_codes() -> None:
    circuit = _reload_circuit_module()
    for code in (429, 502, 503, 504):
        assert circuit.should_retry_status(code) is True


def test_should_trip_circuit_skips_structured_registration_503() -> None:
    circuit = _reload_circuit_module()
    assert (
        circuit.should_trip_circuit(503, {"code": "REGISTRATION_UNAVAILABLE", "detail": "nope"})
        is False
    )


def test_should_trip_circuit_keeps_unstructured_503() -> None:
    circuit = _reload_circuit_module()
    assert circuit.should_trip_circuit(503, {"detail": "temporary"}) is True


def test_circuit_reset_default_is_30_seconds(monkeypatch) -> None:
    monkeypatch.delenv("API_CIRCUIT_RESET_SECONDS", raising=False)
    circuit = _reload_circuit_module()
    assert circuit._CB_RESET_SECONDS == 30.0


def test_circuit_reset_honors_env_override(monkeypatch) -> None:
    monkeypatch.setenv("API_CIRCUIT_RESET_SECONDS", "45")
    circuit = _reload_circuit_module()
    assert circuit._CB_RESET_SECONDS == 45.0


def test_retry_backoff_applies_jitter(monkeypatch) -> None:
    monkeypatch.setenv("API_CIRCUIT_RETRY_JITTER_RATIO", "0.30")
    circuit = _reload_circuit_module()
    sleeps: list[float] = []
    monkeypatch.setattr(circuit.time, "sleep", lambda seconds: sleeps.append(float(seconds)))
    monkeypatch.setattr(circuit.random, "uniform", lambda low, high: high)

    circuit.retry_backoff(1)

    assert sleeps == [0.65]
