import os
import sys

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "server.immoapp_server.settings")
sys.path.append(os.getcwd())
sys.path.append(os.path.join(os.getcwd(), "server"))
django.setup()

from server.pg.uow import admin_transaction


def inspect():
    with admin_transaction() as session:
        for table in ["offers", "demandes"]:
            print(f"\n--- Columns for {table} ---")
            res = session.execute(
                f"SELECT column_name, data_type FROM information_schema.columns WHERE table_name = '{table}'"
            ).fetchall()
            for r in res:
                print(f"{r['column_name']}: {r['data_type']}")


if __name__ == "__main__":
    inspect()
