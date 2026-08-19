"""CLI wrapper for ALE search index maintenance."""

from __future__ import annotations

import argparse
import logging

from server.services.ale_maintenance import reindex_ale_search

logger = logging.getLogger("reindex_ale_search")


def main() -> int:
    parser = argparse.ArgumentParser(description="Rebuild ALE trigram search indexes.")
    parser.add_argument("--dry-run", action="store_true", help="Do not write updates.")
    parser.add_argument("--force", action="store_true", help="Reindex all rows.")
    parser.add_argument("--limit", type=int, default=None, help="Max rows per table.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    total = reindex_ale_search(dry_run=args.dry_run, force=args.force, limit=args.limit)
    logger.info("Reindex complete. Fields updated: %s", total)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
