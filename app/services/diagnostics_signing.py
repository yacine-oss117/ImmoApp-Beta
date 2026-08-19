"""Client-side diagnostics signing helpers (Model B flow)."""

from __future__ import annotations

import base64
import os
import sys
from dataclasses import dataclass
from typing import Any, Protocol, cast

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from core.contracts.diagnostics_contract import (
    DIAGNOSTICS_PAYLOAD_VERSION,
    DIAGNOSTICS_SIGNATURE_ALGORITHM,
)
from core.contracts.idempotency_canonical_json import canonical_json_dumps

_WINDOWS_CNG_BACKEND_CLS: type[object] | None = None
if sys.platform == "win32":
    try:
        from .diagnostics_signing_windows import WindowsCngDiagnosticsBackend as _WIN_BACKEND

        _WINDOWS_CNG_BACKEND_CLS = _WIN_BACKEND
    except Exception:  # pragma: no cover - guarded by runtime fallback policy
        _WINDOWS_CNG_BACKEND_CLS = None

WindowsCngDiagnosticsBackend = _WINDOWS_CNG_BACKEND_CLS

_ALLOW_EXPORTABLE_FALLBACK_ENV = "IMMOAPP_ALLOW_EXPORTABLE_DIAGNOSTICS_FALLBACK"
_REQUIRE_NON_EXPORTABLE_ENV = "IMMOAPP_DIAGNOSTICS_REQUIRE_NON_EXPORTABLE"


def _env_flag(name: str, *, default: bool = False) -> bool:
    raw = (os.environ.get(name) or "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _canonical_message(*, payload: dict[str, object], payload_version: str) -> bytes:
    return canonical_json_dumps(
        {
            "payload_version": payload_version,
            "payload": payload,
        }
    ).encode("utf-8")


class DiagnosticsKeyStore(Protocol):
    def get(self, key: str) -> str | None: ...

    def set(self, key: str, value: str) -> None: ...


class DiagnosticsSigningBackend(Protocol):
    @property
    def algorithm(self) -> str: ...

    def public_key_pem(self, *, device_id: str, signature_key_id: str) -> str: ...

    def sign_message(
        self,
        *,
        message: bytes,
        device_id: str,
        signature_key_id: str,
    ) -> bytes: ...

    def verify_locally(
        self,
        *,
        payload: dict[str, object],
        payload_version: str,
        device_id: str,
        signature_key_id: str,
        signature_b64: str,
    ) -> bool: ...


class InMemoryDiagnosticsKeyStore:
    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self._store.get(key)

    def set(self, key: str, value: str) -> None:
        self._store[key] = value


class KeyringDiagnosticsKeyStore:
    def __init__(self, service_name: str = "ImmoAppDiagnostics") -> None:
        self._service_name = service_name

    def _keyring(self) -> Any:
        import keyring

        return keyring

    def get(self, key: str) -> str | None:
        value = self._keyring().get_password(self._service_name, key)
        return cast(str | None, value)

    def set(self, key: str, value: str) -> None:
        self._keyring().set_password(self._service_name, key, value)


class Ed25519KeyringBackend:
    """Exportable diagnostics backend retained for explicit dev/test fallback only."""

    algorithm = DIAGNOSTICS_SIGNATURE_ALGORITHM

    def __init__(self, store: DiagnosticsKeyStore | None = None) -> None:
        self._store = store or KeyringDiagnosticsKeyStore()

    def _storage_key(self, *, device_id: str, signature_key_id: str) -> str:
        return f"diag-sign:{device_id}:{signature_key_id}:ed25519"

    def _load_or_create_private_key(
        self,
        *,
        device_id: str,
        signature_key_id: str,
    ) -> Ed25519PrivateKey:
        key_name = self._storage_key(device_id=device_id, signature_key_id=signature_key_id)
        stored = self._store.get(key_name)
        if stored:
            key_bytes = stored.encode("utf-8")
            loaded = serialization.load_pem_private_key(key_bytes, password=None)
            if not isinstance(loaded, Ed25519PrivateKey):
                raise ValueError("Stored diagnostics key is not an Ed25519 private key")
            return loaded
        private_key = Ed25519PrivateKey.generate()
        pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        self._store.set(key_name, pem.decode("utf-8"))
        return private_key

    def public_key_pem(self, *, device_id: str, signature_key_id: str) -> str:
        private_key = self._load_or_create_private_key(
            device_id=device_id,
            signature_key_id=signature_key_id,
        )
        public_key = private_key.public_key()
        return public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode("utf-8")

    def sign_message(
        self,
        *,
        message: bytes,
        device_id: str,
        signature_key_id: str,
    ) -> bytes:
        private_key = self._load_or_create_private_key(
            device_id=device_id,
            signature_key_id=signature_key_id,
        )
        return private_key.sign(message)

    def verify_locally(
        self,
        *,
        payload: dict[str, object],
        payload_version: str,
        device_id: str,
        signature_key_id: str,
        signature_b64: str,
    ) -> bool:
        private_key = self._load_or_create_private_key(
            device_id=device_id,
            signature_key_id=signature_key_id,
        )
        public_key = private_key.public_key()
        return verify_signature(
            message=_canonical_message(payload=payload, payload_version=payload_version),
            public_key=public_key,
            signature_b64=signature_b64,
        )


@dataclass(frozen=True)
class SignedDiagnosticsPayload:
    device_id: str
    signature_key_id: str
    payload: dict[str, object]
    signature: str
    payload_version: str
    algorithm: str

    def to_verify_request(self) -> dict[str, object]:
        return {
            "device_id": self.device_id,
            "signature_key_id": self.signature_key_id,
            "payload": self.payload,
            "signature": self.signature,
            "payload_version": self.payload_version,
            "algorithm": self.algorithm,
        }


class DiagnosticsSigner:
    def __init__(
        self,
        store: DiagnosticsKeyStore | None = None,
        *,
        backend: DiagnosticsSigningBackend | None = None,
    ) -> None:
        self._backend = backend or self._build_default_backend(store=store)

    @staticmethod
    def _build_default_backend(*, store: DiagnosticsKeyStore | None) -> DiagnosticsSigningBackend:
        require_non_exportable = _env_flag(_REQUIRE_NON_EXPORTABLE_ENV, default=True)
        allow_exportable_fallback = _env_flag(_ALLOW_EXPORTABLE_FALLBACK_ENV, default=False)
        if store is not None:
            if require_non_exportable and not allow_exportable_fallback:
                raise RuntimeError(
                    "Custom diagnostics key store is exportable and is disabled in strict "
                    "bank-grade mode. Set IMMOAPP_ALLOW_EXPORTABLE_DIAGNOSTICS_FALLBACK=1 "
                    "only for local development/tests."
                )
            return Ed25519KeyringBackend(store=store)
        if _WINDOWS_CNG_BACKEND_CLS is not None:
            return cast(DiagnosticsSigningBackend, _WINDOWS_CNG_BACKEND_CLS())
        if require_non_exportable and not allow_exportable_fallback:
            raise RuntimeError(
                "Non-exportable diagnostics signing key backend is required but unavailable. "
                "Set IMMOAPP_ALLOW_EXPORTABLE_DIAGNOSTICS_FALLBACK=1 only for local development."
            )
        return Ed25519KeyringBackend(store=KeyringDiagnosticsKeyStore())

    def public_key_pem(self, *, device_id: str, signature_key_id: str) -> str:
        return self._backend.public_key_pem(
            device_id=device_id,
            signature_key_id=signature_key_id,
        )

    def sign_payload(
        self,
        *,
        payload: dict[str, object],
        device_id: str,
        signature_key_id: str,
    ) -> SignedDiagnosticsPayload:
        canonical = _canonical_message(
            payload=payload,
            payload_version=DIAGNOSTICS_PAYLOAD_VERSION,
        )
        signature = base64.b64encode(
            self._backend.sign_message(
                message=canonical,
                device_id=device_id,
                signature_key_id=signature_key_id,
            )
        ).decode("ascii")
        return SignedDiagnosticsPayload(
            device_id=device_id,
            signature_key_id=signature_key_id,
            payload=payload,
            signature=signature,
            payload_version=DIAGNOSTICS_PAYLOAD_VERSION,
            algorithm=self._backend.algorithm,
        )

    def verify_locally(
        self,
        *,
        payload: dict[str, object],
        device_id: str,
        signature_key_id: str,
        signature_b64: str,
    ) -> bool:
        return self._backend.verify_locally(
            payload=payload,
            payload_version=DIAGNOSTICS_PAYLOAD_VERSION,
            device_id=device_id,
            signature_key_id=signature_key_id,
            signature_b64=signature_b64,
        )


def verify_signature(
    *,
    message: bytes,
    public_key: Ed25519PublicKey,
    signature_b64: str,
) -> bool:
    try:
        signature_bytes = base64.b64decode(signature_b64, validate=True)
    except Exception:
        return False
    try:
        public_key.verify(signature_bytes, message)
    except InvalidSignature:
        return False
    return True


__all__ = [
    "DiagnosticsSigner",
    "DiagnosticsKeyStore",
    "DiagnosticsSigningBackend",
    "Ed25519KeyringBackend",
    "InMemoryDiagnosticsKeyStore",
    "KeyringDiagnosticsKeyStore",
    "SignedDiagnosticsPayload",
    "WindowsCngDiagnosticsBackend",
    "verify_signature",
]
