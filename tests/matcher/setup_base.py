import sys
from pathlib import Path

# Add repo root to sys.path
repo_root = Path(__file__).resolve().parents[2]
sys.path.append(str(repo_root))

from server.pg.uow import admin_transaction  # noqa: E402


def setup_base():
    with admin_transaction() as session:
        session.execute(
            "INSERT INTO clients (id, status) VALUES (1, 'active') ON CONFLICT DO NOTHING"
        )
        session.execute(
            "INSERT INTO listings (id, status) VALUES (1, 'available') ON CONFLICT DO NOTHING"
        )
        print("Base records ensured.")


if __name__ == "__main__":
    setup_base()
