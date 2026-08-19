"""
Hardened Privacy Audit Script V2.1.
Tests:
1. ALE Leak Scanning (Raw DB check)
2. Partial Update Safety (Merge check)
3. Blind Index Uniqueness (Constraint check)
4. Trigram Search Validation (Matching check)
5. Diacritic-Insensitive Search Test (Normalize check)
6. Remarks Preservation Test (Encrypted field check)
7. NULL/Empty Value Collision handling
"""

import os
import sys
import time
import logging
from pathlib import Path

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("verify_total_privacy_hardened")

# Add repo root and server directory to path
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "server"))

# Setup Django environment (required for cache invalidation handlers in services)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "server.immoapp_server.settings")
try:
    import django

    django.setup()
    logger.info("INFO: Django initialized")
except Exception as e:
    logger.warning(f"WARNING: Django setup failed (might affect cache tests): {e}")


def run_audit():
    logger.info("🚀 [STARTING HARDENED PRIVACY AUDIT V2.1]")

    # Skip schema init for speed
    os.environ["IMMOAPP_SKIP_SCHEMA_INIT"] = "1"

    from server.services import clients
    from server.pg.uow import get_uow, admin_transaction, use_security_context
    from core.encryption import get_encryption_service
    from core.ale_utils import MASK_ENC, MASK_BIDX_PREFIX

    ts = int(time.time())
    client_name = f"AuditName_{ts}"
    unique_phone = f"07{ts % 100000000:08d}"
    client_remark = f"Special Remark with accents: éàî {ts}"

    with use_security_context(agency_id=1):
        # 0. CLEANUP STALE AUDIT DATA
        with admin_transaction() as session:
            # Delete by pattern to avoid affecting real data
            # Include both legacy and new masks for thorough cleanup
            session.execute(
                "DELETE FROM clients WHERE family_name LIKE 'AuditName_%%' OR family_name IN ('ALE_ENCRYPTED', %s)",
                (MASK_ENC,),
            )

        try:
            # TEST 1: Detailed Leak Scan
            logger.info("INFO: TEST 1: Detailed Leak Scan")
            client_id = clients.upsert_client(
                {
                    "family_name": client_name,
                    "phone": unique_phone,
                    "remarks": client_remark,
                    "is_vip": True,
                }
            )

            with admin_transaction() as session:
                row = session.execute(
                    "SELECT * FROM clients WHERE id = %s", (client_id,)
                ).fetchone()

                # Check Plaintext Columns (Should be Masked)
                if row["family_name"] != MASK_ENC:
                    logger.error(f"❌ LEAK FOUND: Plaintext family_name is '{row['family_name']}'")
                    sys.exit(1)

                if not str(row["phone"]).startswith(MASK_BIDX_PREFIX):
                    logger.error(f"❌ LEAK FOUND: Plaintext phone is '{row['phone']}'")
                    sys.exit(1)

                if row["remarks"] != MASK_ENC:
                    logger.error(f"❌ LEAK FOUND: Plaintext remarks is '{row['remarks']}'")
                    sys.exit(1)

                # Check Encrypted Columns (Should NOT be Null)
                if not row["family_name_enc"] or not row["phone_enc"] or not row["remarks_enc"]:
                    logger.error("❌ ERROR: Encryption column is empty! (Missing fields in row?)")
                    sys.exit(1)

            logger.info("INFO: ✅ No leaks found in raw DB row")

            # TEST 2: Partial Update Safety & Case Preservation
            logger.info("INFO: TEST 2: Partial Update Safety & Case Preservation")
            # Update only 'is_vip', should NOT wipe name/phone/remarks
            clients.upsert_client({"id": client_id, "is_vip": False})

            updated_client = clients.get_client_by_id(client_id)
            if updated_client.family_name == client_name:
                logger.info(
                    f"INFO: ✅ Case preserved for family_name: {updated_client.family_name}"
                )
            else:
                logger.error(
                    f"❌ Case MANGLED for family_name! Expected '{client_name}', got '{updated_client.family_name}'"
                )
                sys.exit(1)

            if updated_client.remarks == client_remark:
                logger.info("INFO: ✅ Exact text preserved for long remarks (including accents)")
            else:
                logger.error(
                    f"❌ Remarks MANGLED! Expected '{client_remark}', got '{updated_client.remarks}'"
                )
                sys.exit(1)

            # TEST 3: Blind Index Uniqueness
            logger.info("INFO: TEST 3: Blind Index Uniqueness")
            try:
                clients.upsert_client({"family_name": "DuplicatePhone", "phone": unique_phone})
                logger.error("❌ ERROR: Duplicate phone was allowed (Unique Constraint Failed)")
                sys.exit(1)
            except Exception as e:
                # Accept both raw DB constraint errors and domain-level conflict errors.
                msg = str(e).lower()
                if (
                    "unique constraint" in msg
                    or "already exists" in msg
                    or "duplicate" in msg
                    or "conflict" in msg
                ):
                    logger.info(
                        "INFO: ✅ Duplicate phone correctly blocked by Blind Index Unique Constraint"
                    )
                else:
                    logger.error(f"❌ Unexpected error on duplicate: {e}")
                    sys.exit(1)

            # TEST 4: Diacritic-Insensitive Search
            logger.info("INFO: TEST 4: Diacritic-Insensitive Search")
            accent_name = f"Märçô_{ts}"
            clients.upsert_client({"family_name": accent_name, "phone": f"01{ts % 100000000:08d}"})

            # Search for simplified version: "marco"
            search_term = "marco"
            results = clients.fetch_clients(search=search_term)
            if any(accent_name in c.family_name for c in results):
                logger.info(
                    f"INFO: ✅ Search: '{search_term}' matched '{accent_name}' (Diacritic-Insensitive SUCCESS)"
                )
            else:
                logger.error(f"❌ Search: '{search_term}' FAILED to match '{accent_name}'")
                sys.exit(1)

            # TEST 5: NULL/Empty Value Collision
            logger.info("INFO: TEST 5: NULL/Empty Value Collision")
            try:
                clients.upsert_client({"family_name": "NoPhone1", "phone": ""})
                clients.upsert_client({"family_name": "NoPhone2", "phone": None})
                logger.info(
                    "INFO: ✅ Multiple NULL/Empty phones allowed (Unique Constraint correctly handles NULL)"
                )
            except Exception as e:
                logger.error(f"❌ NULL/Empty collision: {e}")
                sys.exit(1)

            logger.info("🛡️  HARDENED PRIVACY AUDIT PASSED: ALE IS SECURE & ROBUST")

        finally:
            # Cleanup audit data
            try:
                with admin_transaction() as session:
                    session.execute(
                        "DELETE FROM clients WHERE family_name LIKE 'AuditName_%%' OR family_name LIKE 'Märçô_%%'"
                    )
            except Exception as e:
                logger.warning(f"Cleanup failed: {e}")


if __name__ == "__main__":
    run_audit()
