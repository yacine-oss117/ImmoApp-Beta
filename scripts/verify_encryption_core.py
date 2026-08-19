"""
Verification script for core ALE controls and DB-native search hashing.
"""

import os
import sys

# Add root to sys.path
sys.path.append(os.getcwd())

from core.encryption import get_encryption_service
from core.blind_index import get_search_secret
from server.pg.uow import admin_transaction


def verify_encryption():
    print("--- Testing Encryption Engine ---")
    svc = get_encryption_service()

    plaintext = "Secret Phone: 0661223344"
    ciphertext = svc.encrypt(plaintext)

    print(f"Plaintext: {plaintext}")
    print(f"Ciphertext (B64): {ciphertext}")

    if ciphertext == plaintext:
        print("❌ FAIL: Ciphertext is identical to plaintext!")
        return False

    decrypted = svc.decrypt(ciphertext)
    print(f"Decrypted: {decrypted}")

    if decrypted != plaintext:
        print("❌ FAIL: Decrypted text does not match original!")
        return False

    print("✅ PASS: Encryption/Decryption verified.")
    return True


def verify_db_native_search_hashing() -> bool:
    print("\n--- Testing DB-Native ALE Search Hashing ---")
    name_source = "Märçô"
    name_query = "marco"  # diacritic/case insensitive exact query
    phone_source = "0661223344"
    phone_query = "1223"  # partial query

    try:
        secret = get_search_secret()
        with admin_transaction() as session:
            session.execute("SELECT set_config('app.ale_search_secret', %s, true)", (secret,))
            name_hashes = (
                session.execute(
                    "SELECT immoapp_hash_trigrams(%s) AS hashes", (name_source,)
                ).fetchone()["hashes"]
                or []
            )
            name_query_hashes = (
                session.execute(
                    "SELECT immoapp_hash_trigrams(%s) AS hashes", (name_query,)
                ).fetchone()["hashes"]
                or []
            )
            phone_hashes = (
                session.execute(
                    "SELECT immoapp_hash_trigrams(%s) AS hashes", (phone_source,)
                ).fetchone()["hashes"]
                or []
            )
            phone_query_hashes = (
                session.execute(
                    "SELECT immoapp_hash_trigrams(%s) AS hashes", (phone_query,)
                ).fetchone()["hashes"]
                or []
            )
            name_overlap = bool(
                session.execute(
                    "SELECT immoapp_hash_trigrams(%s) && immoapp_hash_trigrams(%s) AS ok",
                    (name_source, name_query),
                ).fetchone()["ok"]
            )
            phone_overlap = bool(
                session.execute(
                    "SELECT immoapp_hash_trigrams(%s) && immoapp_hash_trigrams(%s) AS ok",
                    (phone_source, phone_query),
                ).fetchone()["ok"]
            )

        print(f"Name Source: {name_source}")
        print(f"Name Query: {name_query}")
        print(f"Name Hashes Count: {len(name_hashes)} / {len(name_query_hashes)}")
        print(f"Phone Source: {phone_source}")
        print(f"Phone Query: {phone_query}")
        print(f"Phone Hashes Count: {len(phone_hashes)} / {len(phone_query_hashes)}")

        if name_overlap and phone_overlap:
            print("✅ PASS: Partial search match successful via DB-native hashes.")
            return True
        print("❌ FAIL: DB overlap operator did not detect expected matches.")
        return False
    except Exception as exc:
        print(f"❌ FAIL: DB-native hashing check failed: {exc}")
        return False


if __name__ == "__main__":
    # Ensure env vars for test
    os.environ.setdefault("ALE_MASTER_KEY", "super-secret-test-key-1234567890")
    os.environ.setdefault("ALE_SEARCH_SECRET", "super-secret-pepper-1234567890")
    os.environ.setdefault("ALE_KDF_SALT", "super-secret-kdf-salt-1234567890")

    e_ok = verify_encryption()
    t_ok = verify_db_native_search_hashing()

    if e_ok and t_ok:
        print("\n🎉 ALL CORE SECURITY TESTS PASSED.")
        sys.exit(0)
    else:
        print("\n💥 SOME TESTS FAILED.")
        sys.exit(1)
