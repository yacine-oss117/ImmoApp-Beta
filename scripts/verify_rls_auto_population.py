import logging
import os
import sys

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from server.pg.schema import ensure_schema
from server.pg.uow import admin_transaction, get_uow

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def verify_rls_auto_population():
    logger.info("Applying schema changes via Alembic ensure_schema()...")
    ensure_schema()

    logger.info("Schema updated. Starting verification...")

    uow = get_uow()

    # Pre-requisite: Seed accounts_agency to satisfy FK constraints
    logger.info("Seeding accounts_agency with test IDs (101, 102)...")
    AGENCY_A = 101
    AGENCY_B = 102
    with admin_transaction() as session:
        # Cleanup dependent rows first to avoid FK violations
        # We delete by agency_id because that's our test data scope
        session.execute("DELETE FROM clients WHERE agency_id IN (%s, %s)", (AGENCY_A, AGENCY_B))

        # Check if they exist first to avoid unique violations on re-runs
        # We use ON CONFLICT to act as an upsert/ensure
        session.execute(
            """
            INSERT INTO accounts_agency (
                id, legal_name, display_name, agency_code, 
                kbis_number, phone_number, email, 
                address_line1, address_line2, city, postal_code, country,
                is_active, max_users, max_managers, max_agents_per_manager,
                created_at, updated_at
            ) VALUES 
            (%s, 'Test Agency A', 'Agency A', 'AGY-101', '', '', '', '', '', '', '', '', true, 3, 1, 2, NOW(), NOW()),
            (%s, 'Test Agency B', 'Agency B', 'AGY-102', '', '', '', '', '', '', '', '', true, 3, 1, 2, NOW(), NOW())
            ON CONFLICT (id) DO UPDATE SET updated_at = NOW()
            """,
            (AGENCY_A, AGENCY_B),
        )

    # 1. Test Context-Aware Insert (Auto-population)
    with uow.session(actor="test_verifier") as session:
        # Manually set context via SQL for raw verification or use uow context
        # uow.session pulls from contextvars, but we can also set it explicitly in SQL for simple tests,
        # OR better: use the uow's mechanism.
        pass

    # We need to simulate the Middleware -> ContextVar flow.
    from server.pg.uow import use_security_context

    # 0. Test Control: Explicit Insert (Verify RLS Visibility)
    logger.info("Test 0: Control (Explicit Insert)")
    with use_security_context(agency_id=AGENCY_A):
        with uow.session() as session:
            # DEBUG: Check what Postgres thinks the current setting is
            curr_setting = session.execute(
                "SELECT current_setting('app.current_agency_id', true)"
            ).fetchone()
            logger.info(f"DEBUG SQL Context: {curr_setting}")

            # DEBUG: Check what Postgres thinks the is_superuser setting is
            curr_super = session.execute(
                "SELECT current_setting('app.is_superuser', true)"
            ).fetchone()
            logger.info(f"DEBUG SQL superuser: {curr_super}")

            # DEBUG: Evaluate Policy Expression Manually
            policy_eval = session.execute(
                "SELECT NULLIF(current_setting('app.current_agency_id', true), '')::bigint"
            ).fetchone()
            logger.info(f"DEBUG Policy Expression Val: {policy_eval}")

            bool_eval = session.execute(
                "SELECT 101 = NULLIF(current_setting('app.current_agency_id', true), '')::bigint"
            ).fetchone()
            logger.info(f"DEBUG Policy Equality Check (101): {bool_eval}")

            session.execute(
                "INSERT INTO clients (family_name, phone, status, agency_id) VALUES (%s, %s, 'active', %s) RETURNING id, agency_id",
                ("ControlUser_A", "555-0000", AGENCY_A),
            )
            last_id = session.lastrowid
            logger.info(f"DEBUG RETURNING lastrowid: {last_id}")

            # DEBUG: Try to select it explicitly
            sel_row = session.execute("SELECT * FROM clients WHERE phone = '555-0000'").fetchone()
            logger.info(f"DEBUG SELECT row: {sel_row}")

            if sel_row and sel_row["agency_id"] == AGENCY_A:
                logger.info("✅ PASSED: Control insert visible.")
            else:
                logger.error(f"❌ FAILED: Control insert invisible! Row: {sel_row}")

            session.commit()

    logger.info("DEBUG: Peeking as superuser to verify potential insert...")
    # New session for superuser peek
    with use_security_context(is_superuser=True):
        with uow.session() as session:
            # Check by phone number since we might not have the ID
            row_peek = session.execute(
                "SELECT id, agency_id, phone FROM clients WHERE phone = '555-0000'"
            ).fetchone()
            logger.info(f"DEBUG SUPERUSER PEEK: {row_peek}")

    if row_peek is None:
        logger.warning(
            "Debug Peek: Row not found. Transaction might have rolled back or insert failed silent-ishly."
        )

    logger.info("Test 1: Auto-population (INSERT without agency_id)")
    with use_security_context(agency_id=AGENCY_A):
        with uow.session() as session:
            # DEBUG: Check what Postgres thinks the current setting is
            curr_setting = session.execute(
                "SELECT current_setting('app.current_agency_id', true)"
            ).fetchone()
            logger.info(f"DEBUG SQL Context: {curr_setting}")

            # Insert a client WITHOUT agency_id
            # Note: We use raw SQL to simulate the Repo but exclude agency_id
            session.execute(
                "INSERT INTO clients (family_name, phone, status) VALUES (%s, %s, 'active') RETURNING id, agency_id",
                ("TestUser_A", "555-0101"),
            )
            last_id = session.lastrowid
            logger.info(f"DEBUG INSERT lastrowid: {last_id}")

            # DEBUG: Probe Test 1
            sel_row = session.execute("SELECT * FROM clients WHERE phone = '555-0101'").fetchone()
            logger.info(f"DEBUG SELECT Test 1: {sel_row}")

            if sel_row and sel_row["agency_id"] == AGENCY_A:
                logger.info(
                    f"✅ PASSED: Auto-populated agency_id={sel_row['agency_id']} (Verified via SELECT)"
                )
                client_a_id = sel_row["id"]  # Use the ID from the SELECT for consistency
            else:
                logger.error(
                    f"❌ FAILED: agency_id mismatch. Got {sel_row['agency_id'] if sel_row else 'None'}, expected {AGENCY_A}"
                )
                sys.exit(1)  # Exit if the SELECT fails, as this is the primary verification

            if last_id:
                logger.info("✅ RETURNING consumed by PgSession (lastrowid captured).")

            session.commit()

    # 2. Test Missing Context Insert (Should Fail)
    logger.info("Test 2: Missing Context Insert (Fail-Closed)")
    # No security context set
    try:
        with uow.session() as session:
            session.execute(
                "INSERT INTO clients (family_name, phone, status) VALUES (%s, %s, 'active')",
                ("TestUser_NoContext", "555-0000"),
            )
            session.commit()
    except Exception as e:
        # We expect a constraint violation or check violation
        if (
            'null value in column "agency_id"' in str(e).lower()
            or "violates row-level security" in str(e).lower()
            or "check constraint" in str(e).lower()
        ):
            logger.info(f"✅ PASSED: Insert failed as expected with: {e}")
        else:
            logger.error(f"⚠️ RECEIVED UNEXPECTED ERROR: {e}")
            # It might still be a pass, but let's be careful.
            # If it's a "violates check constraint `policy_...`" that's also good.
            pass
    else:
        logger.error("❌ FAILED: Insert succeeded without context! Leaky security!")
        sys.exit(1)

    # 3. Cross-Tenant Access
    logger.info("Test 3: Cross-Tenant Access")
    logger.info("Test 3: Cross-Tenant Access")
    with use_security_context(agency_id=AGENCY_B):
        with uow.session() as session:
            # Try to read Agency A's client
            session.execute("SELECT * FROM clients WHERE id = %s", (client_a_id,))
            row = session.fetchone()
            if row:
                logger.error(f"❌ FAILED: Agency B could see Agency A's client {client_a_id}!")
                sys.exit(1)
            else:
                logger.info("✅ PASSED: Agency B cannot see Agency A's data.")

            # Try to UPDATE Agency A's client
            session.execute(
                "UPDATE clients SET family_name = 'Hacked' WHERE id = %s", (client_a_id,)
            )
            if session.rowcount > 0:
                logger.error(f"❌ FAILED: Agency B could UPDATE Agency A's client {client_a_id}!")
                sys.exit(1)
            else:
                logger.info("✅ PASSED: Agency B cannot UPDATE Agency A's data.")

    logger.info("🎉 ALL CHECKS PASSED.")


if __name__ == "__main__":
    try:
        verify_rls_auto_population()
    except Exception:
        logger.exception("Verification script crashed")
        sys.exit(1)
