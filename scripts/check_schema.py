import os
import sys

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "server.immoapp_server.settings")
sys.path.append(os.getcwd())
sys.path.append(os.path.join(os.getcwd(), "server"))
django.setup()

from server.pg.uow import admin_transaction


def check():
    with admin_transaction() as session:
        for t in ["accounts_agency"]:
            print(f"--- {t} ---")
            res = session.execute(
                f"SELECT column_name, is_nullable FROM information_schema.columns WHERE table_name='{t}'"
            ).fetchall()
            for r in res:
                print(f"{r['column_name']}: {r['is_nullable']}")


if __name__ == "__main__":
    check()
