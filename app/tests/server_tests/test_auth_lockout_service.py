from __future__ import annotations

from server.services import auth_lockout


def test_lockout_threshold_and_reset(monkeypatch) -> None:
    alerts: list[dict[str, object]] = []
    monkeypatch.setattr(
        "server.services.auth_security_alerts.emit_security_alert",
        lambda **kwargs: alerts.append(kwargs),
    )
    identifier = "agent@example.com"
    source_ip = "127.0.0.1"
    auth_lockout.clear_failures(identifier=identifier, source_ip=source_ip)

    threshold = int(getattr(auth_lockout, "_FAILURE_THRESHOLD", 6))
    for _ in range(threshold - 1):
        assert (
            auth_lockout.record_failure(
                identifier=identifier,
                source_ip=source_ip,
                agency_id=1,
                user_id=9,
            )
            is None
        )
    locked = auth_lockout.record_failure(
        identifier=identifier,
        source_ip=source_ip,
        agency_id=1,
        user_id=9,
    )
    assert locked is not None
    assert auth_lockout.locked_until(identifier=identifier, source_ip=source_ip) is not None
    assert alerts, "security alert should be emitted on lockout threshold"

    auth_lockout.clear_failures(identifier=identifier, source_ip=source_ip)
    assert auth_lockout.locked_until(identifier=identifier, source_ip=source_ip) is None
