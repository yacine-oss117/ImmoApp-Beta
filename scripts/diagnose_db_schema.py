import logging
import os
import sys

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from server.pg.uow import get_uow

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def check_defaults():
    logger.info("Checking RLS policies on clients table...")
    uow = get_uow()
    with uow.session() as session:
        policies = session.execute("""
            SELECT polname, polcmd, polpermissive, polroles, polqual, polwithcheck
            FROM pg_policy p
            JOIN pg_class c ON p.polrelid = c.oid
            WHERE c.relname = 'clients'
        """).fetchall()
        for p in policies:
            logger.info(f"Policy: {p['polname']}, Permissive: {p['polpermissive']}")
            logger.info(f"  USING: {p['polqual']}")
            logger.info(f"  CHECK: {p['polwithcheck']}")


if __name__ == "__main__":
    try:
        check_defaults()
    except Exception:
        logger.exception("Diagnostic crashed")
        sys.exit(1)
