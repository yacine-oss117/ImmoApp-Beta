"""
Deduplicate clients/listings by (agency_id, phone) and enforce uniqueness.
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(REPO_ROOT))

from core.utils.time import utc_now_iso  # noqa: E402
from server.pg.uow import PgSession, admin_transaction  # noqa: E402

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Only report duplicates.")
    args = parser.parse_args()

    with admin_transaction() as session:
        client_groups = _find_duplicates(session, "clients")
        listing_groups = _find_duplicates(session, "listings")

        logger.info("Duplicate client groups: %s", len(client_groups))
        logger.info("Duplicate listing groups: %s", len(listing_groups))

        if args.dry_run:
            return

        for group in client_groups:
            _merge_clients(session, group)
        for group in listing_groups:
            _merge_listings(session, group)


def _find_duplicates(session: PgSession, table: str) -> list[dict[str, object]]:
    rows = session.execute(f"""
        SELECT
            agency_id,
            phone,
            ARRAY_AGG(id ORDER BY updated_at DESC NULLS LAST, created_at DESC NULLS LAST, id DESC) AS ids
        FROM {table}
        WHERE deleted_at IS NULL
          AND phone IS NOT NULL
          AND btrim(phone) <> ''
        GROUP BY agency_id, phone
        HAVING COUNT(*) > 1
        """).fetchall()
    return [dict(row) for row in rows]


def _merge_clients(session: PgSession, group: dict[str, object]) -> None:
    ids = _coerce_ids(group.get("ids"))
    if len(ids) < 2:
        return
    canonical_id, dup_ids = ids[0], ids[1:]
    agency_id = group.get("agency_id")
    now = utc_now_iso()

    logger.info(
        "Dedup clients agency=%s phone=%s keep=%s drop=%s",
        agency_id,
        group.get("phone"),
        canonical_id,
        dup_ids,
    )

    session.execute(
        "UPDATE demandes SET client_id = ? WHERE agency_id = ? AND client_id = ANY(?)",
        (canonical_id, agency_id, dup_ids),
    )
    session.execute(
        "UPDATE visits SET client_id = ? WHERE agency_id = ? AND client_id = ANY(?)",
        (canonical_id, agency_id, dup_ids),
    )
    session.execute(
        "UPDATE contracts SET client_id = ? WHERE agency_id = ? AND client_id = ANY(?)",
        (canonical_id, agency_id, dup_ids),
    )
    session.execute(
        "DELETE FROM match_counts_cache WHERE client_id = ANY(?)",
        (dup_ids,),
    )
    session.execute(
        "UPDATE match_counts_cache SET is_dirty = 1 WHERE client_id = ?",
        (canonical_id,),
    )
    session.execute(
        "UPDATE clients SET deleted_at = ?, updated_at = ?, row_version = row_version + 1 "
        "WHERE agency_id = ? AND id = ANY(?)",
        (now, now, agency_id, dup_ids),
    )


def _merge_listings(session: PgSession, group: dict[str, object]) -> None:
    ids = _coerce_ids(group.get("ids"))
    if len(ids) < 2:
        return
    canonical_id, dup_ids = ids[0], ids[1:]
    agency_id = group.get("agency_id")
    now = utc_now_iso()

    logger.info(
        "Dedup listings agency=%s phone=%s keep=%s drop=%s",
        agency_id,
        group.get("phone"),
        canonical_id,
        dup_ids,
    )

    session.execute(
        "UPDATE offers SET listing_id = ? WHERE agency_id = ? AND listing_id = ANY(?)",
        (canonical_id, agency_id, dup_ids),
    )
    session.execute(
        "UPDATE visits SET listing_id = ? WHERE agency_id = ? AND listing_id = ANY(?)",
        (canonical_id, agency_id, dup_ids),
    )
    session.execute(
        "UPDATE contracts SET listing_id = ? WHERE agency_id = ? AND listing_id = ANY(?)",
        (canonical_id, agency_id, dup_ids),
    )
    session.execute(
        "UPDATE listings SET deleted_at = ?, updated_at = ?, row_version = row_version + 1 "
        "WHERE agency_id = ? AND id = ANY(?)",
        (now, now, agency_id, dup_ids),
    )


def _coerce_ids(raw: object) -> list[int]:
    if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
        result = []
        for value in raw:
            if isinstance(value, int):
                result.append(value)
            elif isinstance(value, str) and value.isdigit():
                result.append(int(value))
        return result
    return []


if __name__ == "__main__":
    main()
