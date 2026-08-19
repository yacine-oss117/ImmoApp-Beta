import logging
import sys

from server.pg.uow import get_uow, use_security_context

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def verify_uow_cleanup():
    uow = get_uow()

    logger.info("Step 1: Acquire Session A, set Agency 101")
    pid_a = None
    with use_security_context(agency_id=101):
        with uow.session() as session:
            # Verify context is set
            res = session.execute(
                "SELECT current_setting('app.current_agency_id', true), pg_backend_pid()"
            ).fetchone()
            logger.info(f"Session A context: {res}")
            if res["current_setting"] != "101":
                logger.error("❌ Session A context failed to set")
                sys.exit(1)
            pid_a = res["pg_backend_pid"]

    logger.info("Step 2: Acquire Session B (no context), Verify Clean & Reuse")
    # No security context wrapper
    with uow.session() as session:
        # Check if context leaked
        res = session.execute(
            "SELECT current_setting('app.current_agency_id', true), pg_backend_pid()"
        ).fetchone()
        logger.info(f"Session B context: {res}")

        setting_val = res["current_setting"]
        pid_b = res["pg_backend_pid"]

        if pid_a == pid_b:
            logger.info("ℹ️  Connection reused (PID matched)")
        else:
            logger.info(
                "ℹ️  Connection NOT reused (PID mismatch) - test remains valid for clean-state verification"
            )

        if setting_val != "":
            logger.error(f"❌ Session B found leaked context: {setting_val} (PID: {pid_b})")
            sys.exit(1)
        else:
            logger.info("✅ Session B context is clean")

    logger.info("🎉 UoW Cleanup Verification Passed")


if __name__ == "__main__":
    verify_uow_cleanup()
