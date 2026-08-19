import os
import sys

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "server.immoapp_server.settings")
sys.path.append(os.getcwd())
sys.path.append(os.path.join(os.getcwd(), "server"))
django.setup()

from server.pg.uow import admin_transaction

with admin_transaction() as session:
    rows = session.execute("""
        SELECT tablename, indexname, indexdef 
        FROM pg_indexes 
        WHERE tablename IN ('offers', 'demandes', 'offer_locations', 'demande_locations', 'clients', 'listings')
        ORDER BY tablename, indexname
    """).fetchall()

    print("=" * 80)
    print("CURRENT INDEXES ON MATCHING TABLES")
    print("=" * 80)

    for r in rows:
        print(f"\n{r['tablename']}.{r['indexname']}:")
        print(f"  {r['indexdef']}")
