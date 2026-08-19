import logging
import os
import random
import sys
import time
from pathlib import Path

import django

# Resolve the repository from this script instead of a developer-specific path.
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "server"))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "server.immoapp_server.settings")


def verify_total_privacy():
    print("Setting up Django...")
    os.environ["IMMOAPP_SKIP_SCHEMA_INIT"] = "1"
    django.setup()
    print("Django setup done.")

    from core.ale_utils import MASK_BIDX_PREFIX, MASK_ENC
    from core.data import lookup_tables
    from server.pg.uow import get_uow, set_security_context
    from server.services import clients, crm_contracts, demandes, listings, offers

    print("Setting security context...")
    set_security_context(agency_id=1, is_superuser=True)
    print("Security context set.")

    uow = get_uow()
    print("Services ready.")

    with uow.session() as session:
        actions = lookup_tables.get_all_actions(session)
        types = lookup_tables.get_all_property_types(session)
        wilayas = lookup_tables.get_all_wilayas(session)
    if not actions or not types or not wilayas:
        raise RuntimeError("Lookup tables are required for privacy verification.")
    action_id, action_name = actions[0]
    type_id, type_name = types[0]
    wilaya_id, wilaya_name, _wilaya_code = wilayas[0]

    ts = int(time.time())
    failures = 0

    # Seed dedicated entities for this audit run.
    client_id = clients.upsert_client(
        {
            "family_name": f"Audit Contract Client {ts}",
            "phone": f"0{random.randint(100000000, 999999999)}",
            "remarks": "Contract seed client",
        }
    )
    listing_id = listings.upsert_listing(
        {
            "family_name": f"Audit Contract Listing {ts}",
            "phone": f"0{random.randint(100000000, 999999999)}",
            "remarks": "Contract seed listing",
            "status": "available",
        }
    )

    # 1. Verify Contracts (Financial ALE)
    logger.info("--- Phase 1: Contracts ---")
    with uow.transaction() as session:
        contract_id = crm_contracts.create_contract(
            {
                "client_id": client_id,
                "listing_id": listing_id,
                "contract_type": "rent",
                "amount": 150000.0,
                "deposit": 300000.0,
                "terms": f"Top Secret Terms {ts}",
                "notes": "Sensitive Contract Notes",
            }
        )

        row = session.execute("SELECT * FROM contracts WHERE id = %s", (contract_id,)).fetchone()
        if row.get("terms") == MASK_ENC and row.get("terms_enc"):
            logger.info("✅ Contract terms masked and encrypted")
        else:
            logger.error(f"❌ Contract terms leak! DB value: {row.get('terms')}")
            failures += 1

        contract = crm_contracts.get_contract_by_id(contract_id)
        if f"Top Secret Terms {ts}" in (contract.terms or ""):
            logger.info("✅ Contract transparent decryption working")
        else:
            logger.error("❌ Contract decryption failed")
            failures += 1

    # 2. Verify Clients (PII ALE with DB-native search hash indexes)
    logger.info("--- Phase 2: Clients (Searchable Name & Phone) ---")
    with uow.transaction() as session:
        unique_phone = f"0{random.randint(100000000, 999999999)}"
        client_name = f"Verified Name {ts}"
        client_id = clients.upsert_client(
            {"family_name": client_name, "phone": unique_phone, "remarks": "Secret Client Remark"}
        )
        row = session.execute("SELECT * FROM clients WHERE id = %s", (client_id,)).fetchone()

        # Check masking
        if row.get("family_name") == MASK_ENC:
            logger.info("✅ Client name masked in DB")
        else:
            logger.error(f"❌ Client name leak! DB value: {row.get('family_name')}")
            failures += 1

        db_phone = str(row.get("phone"))
        if db_phone.startswith(MASK_BIDX_PREFIX):
            logger.info(f"✅ Client phone using Blind Index: {db_phone[:20]}...")
        else:
            logger.error(f"❌ Client phone masking failed! DB value: {db_phone}")
            failures += 1

        # Check DB-native search hash indexes
        if row.get("family_name_search_idx") and row.get("phone_search_idx"):
            logger.info("✅ DB-native search hash indexes generated for both name and phone")
        else:
            logger.error(
                f"❌ Missing search indexes! Name: {bool(row.get('family_name_search_idx'))}, Phone: {bool(row.get('phone_search_idx'))}"
            )
            failures += 1

        # Check decryption
        client = clients.get_client_by_id(client_id)
        if client.family_name == client_name and client.phone == unique_phone:
            logger.info("✅ Client transparent decryption working for name and phone")
        else:
            logger.error(
                f"❌ Client decryption failed! Name matches: {client.family_name == client_name}, Phone matches: {client.phone == unique_phone}"
            )
            failures += 1

    # 3. Verify Offers (Location ALE)
    logger.info("--- Phase 3: Offers ---")
    with uow.transaction() as session:
        offer_id = offers.create_offer(
            listing_id,
            {
                "type": type_name,
                "type_id": type_id,
                "action": action_name,
                "action_id": action_id,
                "wilaya": wilaya_name,
                "wilaya_id": wilaya_id,
                "location": f"Avenue Pasteur {ts}, Algiers",
                "beds": 3,
                "surface": 120.0,
                "budget": 25000000,
                "floor": 2,
                "elevator": 1,
                "remarks": "High value",
            },
        )
        row = session.execute("SELECT * FROM offers WHERE id = %s", (offer_id,)).fetchone()
        if row.get("location") == MASK_ENC and row.get("location_enc"):
            logger.info("✅ Offer location masked and encrypted")
        else:
            logger.error(f"❌ Offer location leak! DB value: {row.get('location')}")
            failures += 1

        offer = offers.get_offer_by_id(offer_id)
        if f"Avenue Pasteur {ts}" in (offer.location or ""):
            logger.info("✅ Offer transparent decryption working")
        else:
            logger.error("❌ Offer decryption failed")
            failures += 1

    # 4. Verify Demandes (Locations ALE)
    logger.info("--- Phase 4: Demandes ---")
    with uow.transaction() as session:
        demande_id = demandes.create_demande(
            client_id,
            {
                "type": type_name,
                "type_id": type_id,
                "action": action_name,
                "action_id": action_id,
                "wilaya": wilaya_name,
                "wilaya_id": wilaya_id,
                "locations": f"Kouba {ts}, Hydra",
                "beds_min": 2,
                "surface_min": 60.0,
                "surface_max": 150.0,
                "budget_min": 10000000,
                "budget_max": 40000000,
                "floor_min": 0,
                "floor_max": 8,
                "elevator": 1,
                "remarks": "Client wants quiet area",
            },
        )
        row = session.execute("SELECT * FROM demandes WHERE id = %s", (demande_id,)).fetchone()
        if row.get("locations") == MASK_ENC and row.get("locations_enc"):
            logger.info("✅ Demande locations masked and encrypted")
        else:
            logger.error(f"❌ Demande locations leak! DB value: {row.get('locations')}")
            failures += 1

        demande = demandes.get_demande_by_id(demande_id)
        if f"Kouba {ts}" in (demande.locations or ""):
            logger.info("✅ Demande transparent decryption working")
        else:
            logger.error("❌ Demande decryption failed")
            failures += 1

    if failures > 0:
        logger.error(f"--- TOTAL PRIVACY VERIFICATION FAILED WITH {failures} ERRORS ---")
        sys.exit(1)
    else:
        logger.info("--- TOTAL PRIVACY VERIFICATION COMPLETE: ALL CHECKS PASSED ---")
        sys.exit(0)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    logger = logging.getLogger("VERIFY")
    try:
        verify_total_privacy()
    except Exception:
        logger.exception("Verification failed")
        sys.exit(1)
