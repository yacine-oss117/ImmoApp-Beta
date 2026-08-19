from __future__ import annotations

import os
from dataclasses import dataclass
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec


def _ensure_django() -> None:
    pytest.importorskip(
        "daphne",
        reason="diagnostics verify algorithm contract tests require server deps",
    )
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "server.immoapp_server.settings")
    import django
    from django.apps import apps

    if not apps.ready:
        django.setup()


@dataclass
class _Actor:
    id: int = 7
    pk: int = 7
    username: str = "diag-actor"
    agency_id: int = 42
    role: str = "manager"
    is_authenticated: bool = True


def test_verify_diagnostics_rejects_unsupported_algorithm() -> None:
    _ensure_django()
    from server.services import diagnostics_keys

    result = diagnostics_keys.verify_diagnostics_signature(
        actor=_Actor(),
        device_id="device-x",
        signature_key_id="sig-x",
        payload={"message": "ok"},
        signature="AA==",
        algorithm="rsa-sha512",
    )
    assert result["valid"] is False
    assert result["code"] == "UNSUPPORTED_ALGORITHM"


def test_verify_diagnostics_rejects_algorithm_mismatch(monkeypatch) -> None:
    _ensure_django()
    from server.accounts.models import DiagnosticsSigningKey
    from server.services import diagnostics_keys

    public_key = ec.generate_private_key(ec.SECP256R1()).public_key()
    public_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")

    class _Manager:
        def filter(self, **kwargs):
            _ = kwargs
            return self

        def first(self):
            return SimpleNamespace(public_key=public_pem)

    monkeypatch.setattr(DiagnosticsSigningKey, "objects", _Manager())
    result = diagnostics_keys.verify_diagnostics_signature(
        actor=_Actor(),
        device_id="device-x",
        signature_key_id="sig-x",
        payload={"message": "ok"},
        signature="AA==",
        algorithm="ed25519",
    )
    assert result["valid"] is False
    assert result["code"] == "ALGORITHM_MISMATCH"
