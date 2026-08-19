"""CLI wrapper for ALE PII purge operations."""

from __future__ import annotations

import argparse
import logging
import os

from server.services.ale_maintenance import purge_ale_pii

logger = logging.getLogger("purge_ale_pii")


def main() -> int:
    parser = argparse.ArgumentParser(description="Purge ALE PII for deleted rows.")
    parser.add_argument("--dry-run", action="store_true", help="Do not write updates.")
    parser.add_argument(
        "--days",
        type=int,
        default=int(os.environ.get("ALE_PII_RETENTION_DAYS", "365")),
        help="Retention window in days.",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    total = purge_ale_pii(days=args.days, dry_run=args.dry_run)
    logger.info("Purge complete. Rows affected: %s", total)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
