"""
Application Layer Encryption (ALE) Service.
Uses AES-256-GCM for authenticated encryption of PII with key versioning.
"""

from __future__ import annotations

import base64
import os
import re
from dataclasses import dataclass

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


class EncryptionError(Exception):
    """Raised when encryption or decryption fails."""

    pass


_VERSION_RE = re.compile(r"^v\d+$")


@dataclass(frozen=True)
class _KeyMaterial:
    key_id: str
    key: str


class EncryptionService:
    """
    Handles AES-256-GCM encryption/decryption for a single key.
    Keys are derived from a master secret using PBKDF2.
    """

    def __init__(self, master_key: str, *, salt: str = "immoapp-ale-v1"):
        if not master_key:
            raise ValueError("Master key is required for encryption")

        # Derive a 32-byte (256-bit) key
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt.encode(),
            iterations=100000,
        )
        self._key = kdf.derive(master_key.encode())
        self._aesgcm = AESGCM(self._key)

    def encrypt_raw(self, plaintext: str) -> str:
        """
        Encrypt plaintext and return a base64 encoded string.
        Format: b64(nonce + ciphertext + tag)
        """
        if not plaintext:
            return ""

        try:
            nonce = os.urandom(12)  # 96-bit nonce for GCM
            data = plaintext.encode("utf-8")
            ciphertext = self._aesgcm.encrypt(nonce, data, None)

            # Combine nonce and ciphertext
            combined = nonce + ciphertext
            return base64.b64encode(combined).decode("utf-8")
        except Exception as e:
            raise EncryptionError(f"Encryption failed: {e}") from e

    def decrypt_raw(self, b64_ciphertext: str) -> str:
        """
        Decrypt a base64 encoded string and return the plaintext.
        """
        if not b64_ciphertext:
            return ""

        try:
            combined = base64.b64decode(b64_ciphertext)
            if len(combined) < 12:
                raise EncryptionError("Invalid ciphertext format")

            nonce = combined[:12]
            ciphertext = combined[12:]

            plaintext_bytes = self._aesgcm.decrypt(nonce, ciphertext, None)
            return plaintext_bytes.decode("utf-8")
        except Exception as e:
            raise EncryptionError(f"Decryption failed: {e}") from e


class KeyringEncryptionService:
    """
    Encryption service that supports multiple key versions.
    New encryptions are tagged with the current key_id (e.g. v1:...).
    Legacy ciphertext (no prefix) will be tried against all keys in order.
    """

    def __init__(self, *, keys: list[_KeyMaterial], current_id: str, salt: str) -> None:
        if not keys:
            raise ValueError("At least one key is required for encryption")
        self._current_id = current_id
        self._services: dict[str, EncryptionService] = {
            item.key_id: EncryptionService(item.key, salt=salt) for item in keys
        }
        self._order = [item.key_id for item in keys]

    @property
    def current_key_id(self) -> str:
        return self._current_id

    def encrypt(self, plaintext: str) -> str:
        if not plaintext:
            return ""
        service = self._services[self._current_id]
        token = service.encrypt_raw(plaintext)
        return f"{self._current_id}:{token}"

    def decrypt(self, ciphertext: str) -> str:
        if not ciphertext:
            return ""
        if ":" in ciphertext:
            key_id, _, payload = ciphertext.partition(":")
            if key_id in self._services and payload:
                return self._services[key_id].decrypt_raw(payload)
            if _VERSION_RE.match(key_id):
                raise EncryptionError(f"Unknown key version: {key_id}")
        # Legacy path: attempt all keys in order.
        for key_id in self._order:
            service = self._services[key_id]
            try:
                return service.decrypt_raw(ciphertext)
            except EncryptionError:
                continue
        raise EncryptionError("Decryption failed for all configured keys.")


# Global instance (initialized on first use)
_instance: KeyringEncryptionService | None = None


def get_encryption_service() -> KeyringEncryptionService:
    global _instance
    if _instance is None:
        current_id = os.environ.get("ALE_KEY_VERSION", "v1").strip() or "v1"
        if not _VERSION_RE.match(current_id):
            raise RuntimeError("ALE_KEY_VERSION must match pattern vN (e.g., v1, v2).")

        # Load key material
        keys: list[_KeyMaterial] = []

        # Parse ALE_MASTER_KEYS if provided: "v1=key1;v2=key2"
        keyring_raw = os.environ.get("ALE_MASTER_KEYS", "")
        if keyring_raw:
            for part in re.split(r"[;,]", keyring_raw):
                part = part.strip()
                if not part or "=" not in part:
                    continue
                key_id, key_val = part.split("=", 1)
                key_id = key_id.strip()
                key_val = key_val.strip()
                if key_id and key_val:
                    keys.append(_KeyMaterial(key_id=key_id, key=key_val))

        # Explicit versioned key env: ALE_MASTER_KEY_V1, ALE_MASTER_KEY_V2
        for env_key, env_val in os.environ.items():
            if env_key.startswith("ALE_MASTER_KEY_V") and env_val:
                key_id = "v" + env_key.split("ALE_MASTER_KEY_V", 1)[1]
                keys.append(_KeyMaterial(key_id=key_id, key=env_val))

        # Default primary key
        master_key = os.environ.get("ALE_MASTER_KEY")
        if master_key:
            keys.append(_KeyMaterial(key_id=current_id, key=master_key))

        legacy_key = os.environ.get("ALE_MASTER_KEY_OLD")
        if legacy_key:
            keys.append(_KeyMaterial(key_id="v0", key=legacy_key))

        if not keys:
            raise RuntimeError("ALE master key material is required (fail-secure policy).")

        # Deduplicate keys by id (keep last)
        dedup: dict[str, _KeyMaterial] = {}
        for item in keys:
            dedup[item.key_id] = item
        if current_id in dedup:
            ordered = [dedup[current_id]] + [
                value for key, value in dedup.items() if key != current_id
            ]
        else:
            ordered = list(dedup.values())

        # Ensure current key is present
        if current_id not in {item.key_id for item in ordered}:
            raise RuntimeError(f"Missing encryption key for {current_id}")

        salt = os.environ.get("ALE_KDF_SALT", "").strip()
        if len(salt) < 16:
            raise RuntimeError("ALE_KDF_SALT must be set and >= 16 chars (fail-secure policy).")
        _instance = KeyringEncryptionService(keys=ordered, current_id=current_id, salt=salt)
    return _instance


def get_optional_encryption_service() -> KeyringEncryptionService | None:
    """
    Best-effort ALE accessor for read-path consumers.

    Returns None when key material is unavailable. This is used by thin clients
    that may receive already-decrypted API payloads and should not crash on
    missing local key material.
    """
    try:
        return get_encryption_service()
    except RuntimeError:
        return None
