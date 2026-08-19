import os
import sys

import django

# Set up environment
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "server.immoapp_server.settings")
sys.path.append(os.getcwd())
sys.path.append(os.path.join(os.getcwd(), "server"))
django.setup()

from server.pg.uow import admin_transaction  # noqa: E402


def verify_tri_state():
    print("Verifying Tri-State Schema...")
    with admin_transaction() as session:
        # Check defaults
        query = """
            SELECT column_name, column_default 
            FROM information_schema.columns 
            WHERE table_schema = 'public'
            AND table_name = 'demandes' 
            AND column_name IN ('elevator', 'accessibility_required')
        """
        rows = session.execute(query).fetchall()
        for row in rows:
            name = row["column_name"]
            default = row["column_default"]
            print(f"Demande {name} default: {default}")
            if default is not None:
                print(f"!! FAILURE: {name} still has default {default}")
            else:
                print(f"Confirmed: {name} has NO default.")

        # Check existing data
        row_zero = session.execute(
            "SELECT count(*) as count FROM demandes WHERE elevator = 0"
        ).fetchone()
        count_zero = row_zero["count"]
        print(f"Demandes with elevator=0: {count_zero} (Should be 0 if migration ran)")


if __name__ == "__main__":
    try:
        verify_tri_state()
    except Exception as e:
        print(f"Error: {e}")
        import traceback

        traceback.print_exc()
