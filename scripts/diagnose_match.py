import os
import sys

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "server.immoapp_server.settings")
sys.path.append(os.getcwd())
sys.path.append(os.path.join(os.getcwd(), "server"))
django.setup()

from server.pg.uow import admin_transaction, set_security_context


def diagnose():
    set_security_context(agency_id=1, is_superuser=True)
    with admin_transaction() as session:
        # Re-inject 1 pair
        session.execute("DELETE FROM offers WHERE agency_id = 1")
        session.execute("DELETE FROM demandes WHERE agency_id = 1")
        session.execute("DELETE FROM listings WHERE agency_id = 1")
        session.execute("DELETE FROM clients WHERE agency_id = 1")
        session.execute("DELETE FROM accounts_agency WHERE id = 1")

        session.execute("""
            INSERT INTO accounts_agency (id, legal_name, display_name, agency_code, kbis_number, phone_number, email, address_line1, address_line2, city, postal_code, country, is_active, max_users, max_managers, max_agents_per_manager, created_at, updated_at)
            VALUES (1, 'B', 'B', 'B', '1', '1', 'e', '1', '2', 'c', 'p', 'c', true, 1, 1, 1, NOW(), NOW())
        """)
        session.execute(
            "INSERT INTO clients (id, agency_id, family_name, phone, status, created_at, updated_at) VALUES (1, 1, 'C', '0', 'active', NOW(), NOW())"
        )
        session.execute(
            "INSERT INTO listings (id, agency_id, family_name, phone, status, created_at, updated_at) VALUES (1, 1, 'L', '1', 'available', NOW(), NOW())"
        )
        session.execute(
            "INSERT INTO offers (id, agency_id, listing_id, type_id, action_id, price_range, beds, surface, created_at, updated_at) VALUES (1, 1, 1, 1, 3, numrange(100, 200), 3, 75, NOW(), NOW())"
        )
        session.execute(
            "INSERT INTO demandes (id, agency_id, client_id, type_id, action_id, budget_range, surface_range, beds_range, created_at, updated_at) VALUES (1, 1, 1, 1, 1, numrange(100, 200), numrange(50, 100), int4range(2, 4), NOW(), NOW())"
        )

        print("Checking basic JOIN...")
        res = session.execute("""
            SELECT d.id as did, o.id as oid
            FROM demandes d
            JOIN clients c ON c.id = d.client_id
            JOIN offers o ON o.agency_id = d.agency_id
            JOIN listings l ON l.id = o.listing_id
            WHERE d.id = 1
        """).fetchall()
        print(f"Basic Join match count: {len(res)}")

        # Test individual filters
        filters = [
            ("Client Active", "c.status = 'active' AND c.deleted_at IS NULL"),
            ("Listing Active", "l.status = 'available' AND l.deleted_at IS NULL"),
            ("Action Match", "o.action_id = 3 AND d.action_id = 1"),
            ("Type Match", "d.type_id = o.type_id"),
            ("Price Match", "o.price_range && d.budget_range"),
            ("Surface Match", "o.surface::numeric <@ d.surface_range"),
            ("Beds Match", "o.beds <@ d.beds_range"),
        ]

        for name, sql in filters:
            test_sql = f"SELECT 1 FROM demandes d JOIN clients c ON c.id = d.client_id JOIN offers o ON o.agency_id = d.agency_id JOIN listings l ON l.id = o.listing_id WHERE d.id = 1 AND {sql}"
            match = session.execute(test_sql).fetchone()
            print(f"- {name}: {'PASS' if match else 'FAIL'}")


if __name__ == "__main__":
    diagnose()
