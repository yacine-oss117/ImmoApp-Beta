"""CLI wrapper for ALE search-key rotation helpers."""

from __future__ import annotations

import argparse
import logging

from server.services.ale_maintenance import (
    finalize_ale_search_rotation,
    start_ale_search_rotation,
)

logger = logging.getLogger("rotate_ale_search_keys")


def main() -> int:
    parser = argparse.ArgumentParser(description="Rotate ALE search key versions")
    parser.add_argument("--start", metavar="VERSION", help="Start rotation to VERSION (vN)")
    parser.add_argument(
        "--finalize", action="store_true", help="Finalize rotation and clear previous"
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    if bool(args.start) == bool(args.finalize):
        logger.error("Use exactly one of --start VERSION or --finalize")
        return 1

    try:
        if args.start:
            result = start_ale_search_rotation(to_version=args.start)
        else:
            result = finalize_ale_search_rotation()
    except Exception as exc:
        logger.error("Rotation command failed: %s", exc)
        return 1

    logger.info("Search-key rotation result: %s", result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
