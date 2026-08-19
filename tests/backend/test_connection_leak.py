import os

from server.pg import uow


def setup_module() -> None:
    """Force pool to size 1 for deterministic reuse."""
    # Close existing pool if any
    if uow._POOL:
        uow._POOL.close()
        uow._POOL = None

    os.environ["PG_POOL_MIN"] = "1"
    os.environ["PG_POOL_MAX"] = "1"
    os.environ["PG_IDLE_TX_TIMEOUT_MS"] = "1000"


def teardown_module() -> None:
    if uow._POOL:
        uow._POOL.close()
        uow._POOL = None


def test_connection_context_leak() -> None:
    """Verify that session variables do not leak between connection checkouts."""

    # 1. Borrow connection and dirty it with Tenant A
    with uow.use_security_context(agency_id=123, is_superuser=True):
        with uow.get_uow().session(actor="dirty_actor") as session:
            # Verify it was set
            row = session.execute(
                "SELECT current_setting('app.current_agency_id', true) as ag, current_setting('app.audit_actor', true) as ac"
            ).fetchone()
            print(f"DEBUG ROW: {row}")
            assert row is not None
            assert row["ag"] == "123"
            assert row["ac"] == "dirty_actor"

            # Manually dirty something else just in case (e.g. valid-looking actor_id)
            session.execute("SELECT set_config('app.actor_id', '999', false)")
            session.execute("SELECT set_config('app.actor_email', 'leak@test.com', false)")
            session.execute("SET search_path TO sim, public")

    # 2. Borrow connection again (should be the SAME connection due to pool=1)
    # with clean context
    with uow.use_security_context(agency_id=None, is_superuser=False):
        with uow.get_uow().session() as session:
            row = session.execute("""
                SELECT 
                    current_setting('app.current_agency_id', true) as agency,
                    current_setting('app.audit_actor', true) as actor,
                    current_setting('app.is_superuser', true) as superuser,
                    current_setting('app.actor_id', true) as actor_id,
                    current_setting('app.actor_email', true) as actor_email,
                    current_setting('search_path', true) as search_path
            """).fetchone()

            # Must be empty/clean
            assert row is not None
            assert row["agency"] == "", "Leaked agency_id"
            assert row["actor"] == "", "Leaked audit_actor"
            assert row["superuser"] == "false", "Leaked superuser status"
            assert row["actor_id"] == "", "Leaked actor_id"
            assert row["actor_email"] == "", "Leaked actor_email"
            assert row["search_path"] == "public", f"Leaked search_path: {row['search_path']}"


def test_pool_reset_callback_strict() -> None:
    """Verify reset hook cleans state even when bypassing UoW."""
    pool = uow._get_pool()

    # 1) Borrow raw pooled connection and dirty it
    with pool.connection() as conn:
        conn.execute("SELECT set_config('app.current_agency_id', '999', false)")
        conn.execute("SELECT set_config('app.is_superuser', 'true', false)")
        conn.execute("SELECT set_config('app.actor_id', '42', false)")
        conn.execute("SELECT set_config('app.actor_email', 'leak@test.com', false)")
        conn.execute("SET search_path TO sim, public")

    # 2) Re-borrow (pool size=1 ensures same connection)
    with pool.connection() as conn:
        row = conn.execute("""
            SELECT
                current_setting('app.current_agency_id', true) as agency,
                current_setting('app.is_superuser', true) as superuser,
                current_setting('app.actor_id', true) as actor_id,
                current_setting('app.actor_email', true) as actor_email,
                current_setting('search_path', true) as search_path
            """).fetchone()

        assert row is not None
        assert row["agency"] == "", "Leaked agency_id from raw pool"
        assert row["superuser"] in ("", "false"), "Leaked superuser from raw pool"
        assert row["actor_id"] == "", "Leaked actor_id from raw pool"
        assert row["actor_email"] == "", "Leaked actor_email from raw pool"
        assert row["search_path"] == "public", f"Leaked search_path: {row['search_path']}"


if __name__ == "__main__":
    # verification run
    try:
        setup_module()
        test_connection_context_leak()
        print("Leak test PASSED")
    except Exception:
        import traceback

        traceback.print_exc()
        exit(1)
    finally:
        teardown_module()
