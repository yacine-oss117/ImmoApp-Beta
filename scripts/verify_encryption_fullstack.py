import os
import sys

# Add root to sys.path
sys.path.append(os.getcwd())

# Fail-secure ALE defaults for standalone execution.
os.environ.setdefault("ALE_MASTER_KEY", "prod-style-audit-key-for-verification")
os.environ.setdefault("ALE_SEARCH_SECRET", "prod-style-audit-search-secret-for-verification")
os.environ.setdefault("ALE_KDF_SALT", "prod-style-audit-kdf-salt-for-verification")
os.environ.setdefault("ALE_KEY_VERSION", "v1")
os.environ.setdefault("IMMOAPP_REQUIRE_ALE_KEY", "1")

import django

from core.encryption import get_encryption_service
from server.pg.uow import get_uow, use_actor_context, use_security_context
from server.services.clients import fetch_clients, upsert_client

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "server.immoapp_server.settings")
sys.path.append(os.path.join(os.getcwd(), "server"))
django.setup()


def verify_fullstack_ale():
    print("--- Full-Stack ALE Verification ---")

    import uuid

    uid = uuid.uuid4().hex[:8]
    actor = "test-security-audit"
    agency_id = 1
    client_data = {
        "family_name": f"Audit_Target_{uid}",
        "phone": f"06{uid}",  # 2 + 8 = 10 digits/chars
        "remarks": "Sensitive remark that must be encrypted",
        "is_vip": 1,
    }

    with use_security_context(agency_id=agency_id):
        with use_actor_context(actor_id=999):
            print(f"Upserting client: {client_data['family_name']}")
            client_id = upsert_client(client_data, actor=actor)
            print(f"Created Client ID: {client_id}")

            # 1. Verify DB state (Direct SQL bypasses transparent decryption in model)
            with get_uow().session() as session:
                row = session.execute(
                    "SELECT family_name, family_name_enc, phone, phone_enc, remarks, remarks_enc, phone_search_idx "
                    "FROM clients WHERE id = %s",
                    (client_id,),
                ).fetchone()

                if not row:
                    print("❌ FAIL: Row not found in DB!")
                    return False

                print(f"Row plaintext family_name: {row['family_name']}")
                print(f"Row encrypted family_name_enc: {row['family_name_enc'][:20]}...")
                print(f"Row encrypted remarks_enc: {row['remarks_enc'][:20]}...")

                if not row["family_name_enc"] or not row["remarks_enc"]:
                    print("❌ FAIL: Encrypted fields are empty!")
                    return False

                if row["family_name_enc"] == row["family_name"]:
                    print("❌ FAIL: Data is NOT encrypted in DB!")
                    return False

                enc = get_encryption_service()
                if enc.decrypt(row["family_name_enc"]) != client_data["family_name"]:
                    print("❌ FAIL: Ciphertext cannot decrypt to original family_name!")
                    return False
                if enc.decrypt(row["remarks_enc"]) != client_data["remarks"]:
                    print("❌ FAIL: Ciphertext cannot decrypt to original remarks!")
                    return False

                print("✅ DB Persistence Verified: Data is stored in encrypted format.")

                # 2. Verify Search Index
                idx = row["phone_search_idx"]
                print(f"Trigram Index size: {len(idx) if idx else 0}")
                if not idx or len(idx) < 5:
                    print(f"❌ FAIL: Trigram index looks incomplete or missing! {idx}")
                    return False
                print("✅ Search Index Verified.")

            # 3. Verify search path + decrypted service contract
            print(
                f"Testing decrypted service output via fetch_clients(search={client_data['family_name']})..."
            )
            clients = fetch_clients(search=client_data["family_name"])
            if not clients:
                print("❌ FAIL: Could not find client via search!")
                return False

            found = next(
                (
                    c
                    for c in clients
                    if int(getattr(c, "id", 0) or 0) == int(client_id)
                    or c.family_name == client_data["family_name"]
                ),
                None,
            )
            if found is None:
                print("❌ FAIL: Search result did not include the created client!")
                return False
            print(f"Found Client family_name: {found.family_name}")
            if found.family_name != client_data["family_name"]:
                print("❌ FAIL: Service output did not return decrypted family_name!")
                return False

            print("✅ Search + decrypted service contract verified.")

    print("\n🎉 PHASE B FULL-STACK VERIFIED.")
    return True


if __name__ == "__main__":
    try:
        success = verify_fullstack_ale()
        if success:
            sys.exit(0)
        else:
            sys.exit(1)
    except Exception as e:
        print(f"💥 Verification Error: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
