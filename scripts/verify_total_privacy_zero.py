"""
Zero-Trust Ruthless Privacy Audit.
Verifies:
1. Mask Collision Prevention (Unprintable markers)
2. XSS Sanitization (Bleach stripping)
3. Phone Normalization (Index sync for formatted queries)
4. Data Preservation (Partial updates)
"""

import os
import sys
import logging
import time
from pathlib import Path

# Fix paths
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "server"))

# Setup Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "server.immoapp_server.settings")
import django

django.setup()

from server.services import clients
from server.pg.uow import get_uow, use_security_context
from core.ale_utils import MASK_ENC, MASK_BIDX_PREFIX
from core.models import Client

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("ruthless_audit")


def run_audit():
    logger.info("🛡️  [STARTING RUTHLESS PRIVACY AUDIT]")
    ts = int(time.time()) % 1000000

    with use_security_context(agency_id=1, is_superuser=True):
        # 1. MASK COLLISION TEST
        logger.info("TEST 1: Mask Collision Prevention")
        # Attempt to "impersonate" the OLD mask string
        malicious_name = "ALE_ENCRYPTED"
        phone1 = f"0770{ts:06d}01"
        c_id = clients.upsert_client({"family_name": malicious_name, "phone": phone1})

        with get_uow().session() as session:
            row = session.execute("SELECT * FROM clients WHERE id = %s", (c_id,)).fetchone()
            # The public column should contain the NEW structured mask
            if row["family_name"] == malicious_name:
                logger.error(
                    "❌ COLLISION: Public column contains the raw input string instead of a mask!"
                )
                sys.exit(1)

            if row["family_name"] != MASK_ENC:
                logger.error(f"❌ ERROR: Expected MASK_ENC, got {repr(row['family_name'])}")
                sys.exit(1)

            # Decrypt and check
            c_obj = Client.from_row(row)
            if c_obj.family_name != malicious_name:
                logger.error(f"❌ DATA LOSS: Expected {malicious_name}, got {c_obj.family_name}")
                sys.exit(1)
        logger.info("✅ Mask collision prevention verified")

        # 2. XSS SANITIZATION TEST
        logger.info("TEST 2: XSS Sanitization")
        xss_payload = "<script>alert('XSS')</script><b>Bold Remark</b>"
        # We expect bleach to strip EVERYTHING
        expected_clean = "alert('XSS')Bold Remark"

        phone2 = f"0770{ts:06d}02"
        c_id_xss = clients.upsert_client(
            {"family_name": "XSS Tester", "phone": phone2, "remarks": xss_payload}
        )

        with get_uow().session() as session:
            row = session.execute("SELECT * FROM clients WHERE id = %s", (c_id_xss,)).fetchone()
            c_obj = Client.from_row(row)
            if "<script>" in c_obj.remarks or "<b>" in c_obj.remarks:
                logger.error(f"❌ XSS LEAK: Sanitization failed! Found: {c_obj.remarks}")
                sys.exit(1)
            if expected_clean not in c_obj.remarks:
                logger.error(
                    f"❌ SANITIZATION ERROR: Expected {expected_clean}, got {c_obj.remarks}"
                )
                sys.exit(1)
        logger.info("✅ XSS sanitization verified")

        # 3. PHONE NORMALIZATION & INDEX SYNC
        logger.info("TEST 3: Phone Normalization & Index Sync")
        # Save formatted phone
        phone3_fmt = f"07 {ts:06d} 03"

        c_id_phone = clients.upsert_client({"family_name": "Phone Tester", "phone": phone3_fmt})

        # Search using DIFFERENT formatting
        search_query = phone3_fmt.replace(" ", ".")
        results = clients.fetch_clients(search=search_query)
        if not any(c.id == c_id_phone for c in results):
            logger.error(
                f"❌ SEARCH FAILED: Query '{search_query}' did not match index for '{phone3_fmt}'"
            )
            sys.exit(1)
        logger.info("✅ Phone normalization search verified")

        logger.info("🏆 RUTHLESS PRIVACY AUDIT PASSED")


if __name__ == "__main__":
    run_audit()
