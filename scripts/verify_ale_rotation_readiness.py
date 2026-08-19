"""
Verify ALE rotation readiness for CI / production gates.

Checks:
1) ALE key config present
2) Search pepper present
3) Rotation timestamps not overdue (if DB available)
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone

from core.blind_index import (
    get_previous_search_key_version,
    get_search_key_version,
    get_search_secret,
    get_search_secret_set,
)
from core.encryption import get_encryption_service

logger = logging.getLogger("verify_ale_rotation_readiness")
_VERSION_RE = re.compile(r"^v\d+$")


def _parse_ts(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _days_since(ts: datetime | None) -> int | None:
    if ts is None:
        return None
    now = datetime.now(timezone.utc)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    delta = now - ts
    return int(delta.total_seconds() // 86400)


def _require_key() -> bool:
    require_key = os.environ.get("IMMOAPP_REQUIRE_ALE_KEY") == "1"
    if "DJANGO_DEBUG" in os.environ:
        debug = os.environ.get("DJANGO_DEBUG", "0") == "1"
    else:
        try:
            from django.conf import settings

            debug = bool(getattr(settings, "DEBUG", True))
        except Exception:
            debug = True
    return require_key or not debug


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    require_key = _require_key()

    # Ensure encryption/search services can initialize (config present).
    try:
        enc = get_encryption_service()
        _ = enc.current_key_id
        logger.info("ALE encryption configured: %s", enc.current_key_id)
    except Exception as exc:  # pragma: no cover - config check only
        if require_key:
            logger.error("ALE encryption not configured: %s", exc)
            return 1
        logger.warning("ALE encryption not configured (dev mode): %s", exc)

    try:
        _ = get_search_secret()
        logger.info(
            "ALE search secret configured (current=%s, previous=%s)",
            get_search_key_version(),
            get_previous_search_key_version() or "-",
        )
    except Exception as exc:  # pragma: no cover
        if require_key:
            logger.error("ALE search secret not configured: %s", exc)
            return 1
        logger.warning("ALE search secret not configured (dev mode): %s", exc)

    if os.environ.get("IMMOAPP_SKIP_ROTATION_CHECK_DB", "0") == "1":
        logger.info("DB rotation check skipped (IMMOAPP_SKIP_ROTATION_CHECK_DB=1).")
        return 0

    try:
        from core.data import db_schema_meta
        from server.pg.uow import admin_transaction

        key_days = int(os.environ.get("ALE_KEY_ROTATION_DAYS", "180"))
        pepper_days = int(os.environ.get("ALE_SEARCH_ROTATION_DAYS", "180"))

        with admin_transaction() as session:
            db_schema_meta.ensure_meta_table(session)
            key_ts = _parse_ts(db_schema_meta.get_meta(session, "ale_key_rotation_at"))
            pepper_ts = _parse_ts(db_schema_meta.get_meta(session, "ale_search_rotation_at"))
            current_version = db_schema_meta.get_meta(session, "ale_search_key_version") or "v1"
            prev_version = db_schema_meta.get_meta(session, "ale_search_key_prev_version") or ""
            if not _VERSION_RE.match(current_version):
                logger.error("Invalid ale_search_key_version meta: %s", current_version)
                return 1
            if prev_version and not _VERSION_RE.match(prev_version):
                logger.error("Invalid ale_search_key_prev_version meta: %s", prev_version)
                return 1

            # DB-native search hashing readiness smoke-check.
            secrets = get_search_secret_set()
            session.execute(
                "SELECT set_config('app.ale_search_secret', %s, true)",
                (get_search_secret(version=current_version),),
            )
            session.execute(
                "SELECT set_config('app.ale_search_secret_version', %s, true)",
                (current_version,),
            )
            session.execute(
                "SELECT set_config('app.ale_search_secret_prev_version', %s, true)",
                (prev_version,),
            )
            session.execute(
                "SELECT set_config('app.ale_search_secrets', %s, true)",
                (";".join(secrets),),
            )
            hash_row = session.execute(
                "SELECT immoapp_hash_trigrams(%s) AS hashes", ("rotation readiness",)
            ).fetchone()
            if not hash_row:
                logger.error("DB hash function check returned no rows.")
                return 1

        key_age = _days_since(key_ts)
        pepper_age = _days_since(pepper_ts)

        if key_age is None:
            logger.error("Missing ale_key_rotation_at meta.")
            return 1
        if pepper_age is None:
            logger.error("Missing ale_search_rotation_at meta.")
            return 1
        if key_age > key_days:
            logger.error("Key rotation overdue: %s days (limit %s)", key_age, key_days)
            return 1
        if pepper_age > pepper_days:
            logger.error(
                "Search pepper rotation overdue: %s days (limit %s)", pepper_age, pepper_days
            )
            return 1

        logger.info("Rotation readiness OK: key_age=%s, pepper_age=%s", key_age, pepper_age)
    except Exception as exc:  # pragma: no cover
        logger.error("Rotation readiness DB check failed: %s", exc)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
