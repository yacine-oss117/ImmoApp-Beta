"""CLI wrapper for ALE key rotation."""

from __future__ import annotations

import argparse
import logging

from server.services.ale_maintenance import rotate_ale_keys

logger = logging.getLogger("rotate_ale_keys")


def main() -> int:
    parser = argparse.ArgumentParser(description="Re-encrypt ALE ciphertext with current key.")
    parser.add_argument("--dry-run", action="store_true", help="Do not write updates.")
    parser.add_argument("--limit", type=int, default=None, help="Max rows per table.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    rotated = rotate_ale_keys(dry_run=args.dry_run, limit=args.limit)
    logger.info("Rotation complete. Fields updated: %s", rotated)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
