import random
import sys
from pathlib import Path

# Add repo root to sys.path
repo_root = Path(__file__).resolve().parents[2]
sys.path.append(str(repo_root))

from server.pg.uow import admin_transaction  # noqa: E402


def seed_bench_data(batch_size=500):
    with admin_transaction() as session:
        # Get a valid agency_id
        agency_row = session.execute("SELECT id FROM accounts_agency LIMIT 1").fetchone()
        if not agency_row:
            session.execute(
                "INSERT INTO accounts_agency (legal_name, agency_code, is_active) VALUES ('Bench Agency', 'BENCH001', True)"
            )
            agency_row = session.execute(
                "SELECT id FROM accounts_agency WHERE agency_code = 'BENCH001'"
            ).fetchone()
        agency_id = agency_row["id"]
        print(f"Using agency_id: {agency_id}")

        print("Cleaning old bench data...")
        session.execute("DELETE FROM match_pairs")
        session.execute("DELETE FROM match_candidates")
        session.execute("DELETE FROM demande_locations")
        session.execute("DELETE FROM offer_locations")
        session.execute("DELETE FROM offers")
        session.execute("DELETE FROM demandes")

        # Ensure base records
        session.execute(
            "INSERT INTO clients (id, status, agency_id) VALUES (1, 'active', %s) ON CONFLICT (id) DO UPDATE SET agency_id = EXCLUDED.agency_id",
            (agency_id,),
        )
        session.execute(
            "INSERT INTO listings (id, status, agency_id) VALUES (1, 'available', %s) ON CONFLICT (id) DO UPDATE SET agency_id = EXCLUDED.agency_id",
            (agency_id,),
        )

        # Create some locations
        session.execute(
            "INSERT INTO locations (location_norm) SELECT 'Location ' || i FROM generate_series(1, 100) i ON CONFLICT DO NOTHING"
        )
        locations = session.execute("SELECT location_id FROM locations").fetchall()
        loc_ids = [loc["location_id"] for loc in locations]

        print("Seeding 20,000 offers in batches...")
        offer_ids = []
        for _ in range(0, 20000, batch_size):
            batch_data = []
            for _ in range(batch_size):
                batch_data.append(
                    (
                        1,  # listing_id
                        random.choice([1, 2, 3]),  # type_id
                        random.choice([1, 2, 3]),  # action_id
                        random.choice([1, 2, 3]),  # wilaya_id
                        random.uniform(100000, 5000000),  # budget/price
                        random.uniform(50, 300),  # surface
                        random.randint(1, 6),  # beds
                        1 if random.random() > 0.5 else 0,  # negotiable
                        0.1 if random.random() > 0.5 else 0,  # flex_pct
                        agency_id,
                    )
                )

            # Multi-row insert for efficiency
            placeholders = ",".join(["(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"] * len(batch_data))
            flat_params = [item for row in batch_data for item in row]
            rows = session.execute(
                f"INSERT INTO offers (listing_id, type_id, action_id, wilaya_id, budget, surface, beds, price_negotiable, price_flex_pct, agency_id) VALUES {placeholders} RETURNING id",
                flat_params,
            ).fetchall()
            offer_ids.extend([r["id"] for r in rows])
            print(f"  - Offers: {len(offer_ids)}/20000")

        print("Seeding offer_locations...")
        loc_data = []
        for oid in offer_ids:
            for _ in range(random.randint(1, 2)):
                loc_data.append((oid, random.choice(loc_ids), agency_id))

        for i in range(0, len(loc_data), batch_size * 2):
            chunk = loc_data[i : i + batch_size * 2]
            placeholders = ",".join(["(%s, %s, %s)"] * len(chunk))
            flat = [v for row in chunk for v in row]
            session.execute(
                f"INSERT INTO offer_locations (offer_id, location_id, agency_id) VALUES {placeholders} ON CONFLICT DO NOTHING",
                flat,
            )

        print("Seeding 5,000 demandes in batches...")
        demande_ids = []
        for _ in range(0, 5000, batch_size):
            batch_data = []
            for _ in range(batch_size):
                bmin = random.uniform(50000, 1000000)
                smin = random.uniform(40, 100)
                batch_data.append(
                    (
                        1,  # client_id
                        random.choice([1, 2, 3, None]),
                        random.choice([1, 2, 3]),
                        random.choice([1, 2, 3, None]),
                        bmin,
                        bmin + random.uniform(100000, 2000000),
                        smin,
                        smin + random.uniform(50, 200),
                        random.randint(1, 3),
                        agency_id,
                    )
                )
            placeholders = ",".join(["(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"] * len(batch_data))
            flat = [item for row in batch_data for item in row]
            rows = session.execute(
                f"INSERT INTO demandes (client_id, type_id, action_id, wilaya_id, budget_min, budget_max, surface_min, surface_max, beds_min, agency_id) VALUES {placeholders} RETURNING id",
                flat,
            ).fetchall()
            demande_ids.extend([r["id"] for r in rows])
            print(f"  - Demandes: {len(demande_ids)}/5000")

        print("Seeding demande_locations...")
        dloc_data = []
        for did in demande_ids:
            if random.random() > 0.3:
                for _ in range(random.randint(1, 2)):
                    dloc_data.append((did, random.choice(loc_ids), agency_id))

        for i in range(0, len(dloc_data), batch_size * 2):
            chunk = dloc_data[i : i + batch_size * 2]
            placeholders = ",".join(["(%s, %s, %s)"] * len(chunk))
            flat = [v for row in chunk for v in row]
            session.execute(
                f"INSERT INTO demande_locations (demande_id, location_id, agency_id) VALUES {placeholders} ON CONFLICT DO NOTHING",
                flat,
            )

        print("Finalizing range columns...")
        session.execute("""
            UPDATE demandes SET
                budget_range = numrange(COALESCE(budget_min, 0)::numeric, COALESCE(budget_max, 1e18)::numeric, '[]'),
                surface_range = numrange(COALESCE(surface_min, 0)::numeric, COALESCE(surface_max, 1e18)::numeric, '[]'),
                beds_range = int4range(COALESCE(beds_min, 0), NULL, '[]')
            WHERE budget_range IS NULL
        """)
        session.execute("""
            UPDATE offers SET
                price_range = numrange(
                    (budget * (1 - (COALESCE(price_flex_pct, 0) / 100.0)))::numeric,
                    (budget * (1 + (COALESCE(price_flex_pct, 0) / 100.0)))::numeric,
                    '[]'
                )
            WHERE price_range IS NULL
        """)
        print("Seeding complete.")


if __name__ == "__main__":
    seed_bench_data()
