"""Windows CNG-backed diagnostics signing with non-exportable private keys."""

from __future__ import annotations

import ctypes
import hashlib
import os
from contextlib import contextmanager
from ctypes import wintypes
from dataclasses import dataclass
from typing import Iterator

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

from core.contracts.diagnostics_contract import DIAGNOSTICS_SIGNATURE_ALGORITHM_CNG_P256
from core.contracts.idempotency_canonical_json import canonical_json_dumps

_NCRYPT = ctypes.WinDLL("ncrypt.dll")

_NCRYPT_SUCCESS = 0
_NTE_BAD_KEYSET = 0x80090016
_NCRYPT_MACHINE_KEY_FLAG = 0x00000020
_NCRYPT_OVERWRITE_KEY_FLAG = 0x00000080

_MS_KEY_STORAGE_PROVIDER = "Microsoft Software Key Storage Provider"
_ALG_ECDSA_P256 = "ECDSA_P256"
_BLOB_ECC_PUBLIC = "ECCPUBLICBLOB"
_PRIVATE_BLOB_TYPES: tuple[str, ...] = ("ECCPRIVATEBLOB", "PKCS8_PRIVATEKEY")
_PROP_EXPORT_POLICY = "Export Policy"
_PROP_KEY_USAGE = "Key Usage"
_NCRYPT_ALLOW_SIGNING_FLAG = 0x00000002
_REQUIRE_NON_EXPORTABLE_ENV = "IMMOAPP_DIAGNOSTICS_REQUIRE_NON_EXPORTABLE"
_VERIFIED_NON_EXPORTABLE_KEYS: set[str] = set()


def _status_u32(status: int) -> int:
    return ctypes.c_uint32(status).value


def _status_hex(status: int) -> str:
    return f"0x{_status_u32(status):08X}"


class WindowsCngError(RuntimeError):
    pass


def _raise_if_error(status: int, context: str) -> None:
    if status != _NCRYPT_SUCCESS:
        raise WindowsCngError(f"{context} failed with status {_status_hex(status)}")


def _is_key_not_found(status: int) -> bool:
    return _status_u32(status) == _NTE_BAD_KEYSET


_NCryptOpenStorageProvider = _NCRYPT.NCryptOpenStorageProvider
_NCryptOpenStorageProvider.argtypes = [
    ctypes.POINTER(wintypes.HANDLE),
    wintypes.LPCWSTR,
    wintypes.DWORD,
]
_NCryptOpenStorageProvider.restype = wintypes.LONG

_NCryptOpenKey = _NCRYPT.NCryptOpenKey
_NCryptOpenKey.argtypes = [
    wintypes.HANDLE,
    ctypes.POINTER(wintypes.HANDLE),
    wintypes.LPCWSTR,
    wintypes.DWORD,
    wintypes.DWORD,
]
_NCryptOpenKey.restype = wintypes.LONG

_NCryptCreatePersistedKey = _NCRYPT.NCryptCreatePersistedKey
_NCryptCreatePersistedKey.argtypes = [
    wintypes.HANDLE,
    ctypes.POINTER(wintypes.HANDLE),
    wintypes.LPCWSTR,
    wintypes.LPCWSTR,
    wintypes.DWORD,
    wintypes.DWORD,
]
_NCryptCreatePersistedKey.restype = wintypes.LONG

_NCryptSetProperty = _NCRYPT.NCryptSetProperty
_NCryptSetProperty.argtypes = [
    wintypes.HANDLE,
    wintypes.LPCWSTR,
    ctypes.c_void_p,
    wintypes.DWORD,
    wintypes.DWORD,
]
_NCryptSetProperty.restype = wintypes.LONG

_NCryptFinalizeKey = _NCRYPT.NCryptFinalizeKey
_NCryptFinalizeKey.argtypes = [wintypes.HANDLE, wintypes.DWORD]
_NCryptFinalizeKey.restype = wintypes.LONG

_NCryptSignHash = _NCRYPT.NCryptSignHash
_NCryptSignHash.argtypes = [
    wintypes.HANDLE,
    ctypes.c_void_p,
    ctypes.c_void_p,
    wintypes.DWORD,
    ctypes.c_void_p,
    wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD),
    wintypes.DWORD,
]
_NCryptSignHash.restype = wintypes.LONG

_NCryptExportKey = _NCRYPT.NCryptExportKey
_NCryptExportKey.argtypes = [
    wintypes.HANDLE,
    wintypes.HANDLE,
    wintypes.LPCWSTR,
    ctypes.c_void_p,
    ctypes.c_void_p,
    wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD),
    wintypes.DWORD,
]
_NCryptExportKey.restype = wintypes.LONG

_NCryptFreeObject = _NCRYPT.NCryptFreeObject
_NCryptFreeObject.argtypes = [wintypes.HANDLE]
_NCryptFreeObject.restype = wintypes.LONG


@dataclass(frozen=True)
class WindowsCngDiagnosticsBackend:
    provider_name: str = _MS_KEY_STORAGE_PROVIDER
    machine_scope: bool = False
    algorithm: str = DIAGNOSTICS_SIGNATURE_ALGORITHM_CNG_P256

    def _key_name(self, *, device_id: str, signature_key_id: str) -> str:
        material = f"{device_id}|{signature_key_id}|immoapp-diagnostics".encode()
        digest = hashlib.sha256(material).hexdigest()[:32]
        return f"ImmoAppDiag_{digest}"

    @staticmethod
    def _require_non_exportable() -> bool:
        raw = (os.environ.get(_REQUIRE_NON_EXPORTABLE_ENV) or "").strip().lower()
        if not raw:
            return True
        return raw in {"1", "true", "yes", "on"}

    def _assert_private_export_blocked(
        self,
        *,
        key_handle: wintypes.HANDLE,
        key_name: str,
    ) -> None:
        if not self._require_non_exportable():
            return
        if key_name in _VERIFIED_NON_EXPORTABLE_KEYS:
            return
        for blob_type in _PRIVATE_BLOB_TYPES:
            size = wintypes.DWORD(0)
            status = _NCryptExportKey(
                key_handle,
                wintypes.HANDLE(),
                blob_type,
                None,
                None,
                0,
                ctypes.byref(size),
                0,
            )
            if int(status) == _NCRYPT_SUCCESS:
                raise WindowsCngError(
                    "Diagnostics key export self-test failed: private key export is allowed "
                    f"(blob_type={blob_type!r}, key_name={key_name!r})."
                )
        _VERIFIED_NON_EXPORTABLE_KEYS.add(key_name)

    @contextmanager
    def _provider(self) -> Iterator[wintypes.HANDLE]:
        handle = wintypes.HANDLE()
        status = _NCryptOpenStorageProvider(ctypes.byref(handle), self.provider_name, 0)
        _raise_if_error(int(status), "NCryptOpenStorageProvider")
        try:
            yield handle
        finally:
            if handle:
                _NCryptFreeObject(handle)

    def _set_dword_property(self, key_handle: wintypes.HANDLE, name: str, value: int) -> None:
        prop_value = wintypes.DWORD(value)
        status = _NCryptSetProperty(
            key_handle,
            name,
            ctypes.byref(prop_value),
            wintypes.DWORD(ctypes.sizeof(prop_value)),
            0,
        )
        _raise_if_error(int(status), f"NCryptSetProperty({name})")

    @contextmanager
    def _open_or_create_key(
        self,
        *,
        provider: wintypes.HANDLE,
        device_id: str,
        signature_key_id: str,
    ) -> Iterator[wintypes.HANDLE]:
        key_handle = wintypes.HANDLE()
        key_name = self._key_name(device_id=device_id, signature_key_id=signature_key_id)
        open_flags = _NCRYPT_MACHINE_KEY_FLAG if self.machine_scope else 0
        status = _NCryptOpenKey(
            provider,
            ctypes.byref(key_handle),
            key_name,
            0,
            open_flags,
        )
        if _is_key_not_found(int(status)):
            create_flags = _NCRYPT_MACHINE_KEY_FLAG if self.machine_scope else 0
            status = _NCryptCreatePersistedKey(
                provider,
                ctypes.byref(key_handle),
                _ALG_ECDSA_P256,
                key_name,
                0,
                create_flags | _NCRYPT_OVERWRITE_KEY_FLAG,
            )
            _raise_if_error(int(status), "NCryptCreatePersistedKey")
            # Enforce non-exportable key usage policy.
            self._set_dword_property(key_handle, _PROP_EXPORT_POLICY, 0)
            self._set_dword_property(key_handle, _PROP_KEY_USAGE, _NCRYPT_ALLOW_SIGNING_FLAG)
            status = _NCryptFinalizeKey(key_handle, 0)
            _raise_if_error(int(status), "NCryptFinalizeKey")
        else:
            _raise_if_error(int(status), "NCryptOpenKey")
        self._assert_private_export_blocked(key_handle=key_handle, key_name=key_name)
        try:
            yield key_handle
        finally:
            if key_handle:
                _NCryptFreeObject(key_handle)

    def public_key_pem(self, *, device_id: str, signature_key_id: str) -> str:
        with self._provider() as provider:
            with self._open_or_create_key(
                provider=provider,
                device_id=device_id,
                signature_key_id=signature_key_id,
            ) as key_handle:
                size = wintypes.DWORD(0)
                status = _NCryptExportKey(
                    key_handle,
                    wintypes.HANDLE(),
                    _BLOB_ECC_PUBLIC,
                    None,
                    None,
                    0,
                    ctypes.byref(size),
                    0,
                )
                _raise_if_error(int(status), "NCryptExportKey(size)")
                if int(size.value) <= 0:
                    raise WindowsCngError("NCryptExportKey returned empty public blob")
                buf = ctypes.create_string_buffer(int(size.value))
                status = _NCryptExportKey(
                    key_handle,
                    wintypes.HANDLE(),
                    _BLOB_ECC_PUBLIC,
                    None,
                    buf,
                    size,
                    ctypes.byref(size),
                    0,
                )
                _raise_if_error(int(status), "NCryptExportKey(data)")
                blob = ctypes.string_at(buf, int(size.value))
        if len(blob) < 8:
            raise WindowsCngError("Invalid ECDSA public blob from CNG")
        cb_key = int.from_bytes(blob[4:8], byteorder="little", signed=False)
        expected = 8 + cb_key * 2
        if cb_key <= 0 or len(blob) < expected:
            raise WindowsCngError("Malformed ECDSA public blob from CNG")
        x = int.from_bytes(blob[8 : 8 + cb_key], byteorder="big", signed=False)
        y = int.from_bytes(blob[8 + cb_key : 8 + cb_key * 2], byteorder="big", signed=False)
        public_key = ec.EllipticCurvePublicNumbers(x, y, ec.SECP256R1()).public_key()
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
        digest = hashlib.sha256(message).digest()
        digest_arr = (ctypes.c_ubyte * len(digest)).from_buffer_copy(digest)
        with self._provider() as provider:
            with self._open_or_create_key(
                provider=provider,
                device_id=device_id,
                signature_key_id=signature_key_id,
            ) as key_handle:
                result_size = wintypes.DWORD(0)
                status = _NCryptSignHash(
                    key_handle,
                    None,
                    ctypes.cast(digest_arr, ctypes.c_void_p),
                    len(digest),
                    None,
                    0,
                    ctypes.byref(result_size),
                    0,
                )
                _raise_if_error(int(status), "NCryptSignHash(size)")
                if int(result_size.value) <= 0:
                    raise WindowsCngError("NCryptSignHash returned empty signature")
                out_buf = ctypes.create_string_buffer(int(result_size.value))
                status = _NCryptSignHash(
                    key_handle,
                    None,
                    ctypes.cast(digest_arr, ctypes.c_void_p),
                    len(digest),
                    ctypes.cast(out_buf, ctypes.c_void_p),
                    int(result_size.value),
                    ctypes.byref(result_size),
                    0,
                )
                _raise_if_error(int(status), "NCryptSignHash(data)")
                raw_sig = ctypes.string_at(out_buf, int(result_size.value))
        if len(raw_sig) != 64:
            raise WindowsCngError(f"Unexpected ECDSA signature length: {len(raw_sig)}")
        r = int.from_bytes(raw_sig[:32], byteorder="big", signed=False)
        s = int.from_bytes(raw_sig[32:], byteorder="big", signed=False)
        return encode_dss_signature(r, s)

    def verify_locally(
        self,
        *,
        payload: dict[str, object],
        payload_version: str,
        device_id: str,
        signature_key_id: str,
        signature_b64: str,
    ) -> bool:
        import base64

        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric import ec as ecc

        canonical = canonical_json_dumps(
            {
                "payload_version": payload_version,
                "payload": payload,
            }
        ).encode("utf-8")
        try:
            sig = base64.b64decode(signature_b64, validate=True)
            pub = serialization.load_pem_public_key(
                self.public_key_pem(
                    device_id=device_id,
                    signature_key_id=signature_key_id,
                ).encode("utf-8")
            )
            if not isinstance(pub, ec.EllipticCurvePublicKey):
                return False
            pub.verify(sig, canonical, ecc.ECDSA(hashes.SHA256()))
        except (InvalidSignature, ValueError, TypeError):
            return False
        return True
