"""
Postgres-backed health snapshot utilities.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from types import ModuleType

from core.data import agency_settings_repository as settings_data
from core.data import db_schema_meta, import_learning_repository, match_rebuild_state
from core.importer.security import import_security_limits_snapshot
from core.runtime.hub_runtime_profile import (
    resolve_hub_runtime_profile,
    summarize_hub_runtime_profile,
)
from core.utils.row_casts import row_int
from server.pg import schema_tenant_constants
from server.pg.observability import get_cache_stats
from server.pg.uow import get_pool_stats, get_uow
from server.services import (
    import_execution_governor,
    match_runtime_profile,
    postgres_match_health,
    tenant_resource_governor,
    tenant_usage_gauge,
)

import_runtime_maintenance: ModuleType | None = None


@dataclass(frozen=True)
class HealthSnapshot:
    """A snapshot of the system's operational health from the database perspective."""

    db_path: str
    active_connections: int
    audit_actor: str
    schema_version: str | None
    settings_schema_version: str | None
    last_repair: str | None
    last_backup_ts: str | None
    last_backup_reason: str | None
    last_backup_path: str | None


def fetch_health_snapshot() -> HealthSnapshot:
    """Collect various health metrics and metadata from Postgres."""
    host = os.environ.get("POSTGRES_HOST", "localhost")
    port = os.environ.get("POSTGRES_PORT", "5432")
    dbname = os.environ.get("POSTGRES_DB", "immoapp")
    db_path = f"postgres://{host}:{port}/{dbname}"

    with get_uow().session() as session:
        schema_version = db_schema_meta.get_meta(session, "schema_version")
        settings_schema = db_schema_meta.get_meta(session, "settings_schema_version")
        last_repair = db_schema_meta.get_meta(session, "last_repair")
        last_backup_ts = db_schema_meta.get_meta(session, "last_backup_ts")
        last_backup_reason = db_schema_meta.get_meta(session, "last_backup_reason")
        last_backup_path = db_schema_meta.get_meta(session, "last_backup_path")
        actor = settings_data.get_agency_setting(session, "audit_actor", "")

        active_row = session.execute(
            "SELECT COUNT(*) AS count FROM pg_stat_activity WHERE datname = current_database()"
        ).fetchone()
        active_connections = row_int(active_row, "count") if active_row else 0

    return HealthSnapshot(
        db_path=db_path,
        active_connections=active_connections,
        audit_actor=actor,
        schema_version=schema_version,
        settings_schema_version=settings_schema,
        last_repair=last_repair,
        last_backup_ts=last_backup_ts,
        last_backup_reason=last_backup_reason,
        last_backup_path=last_backup_path,
    )


def health_snapshot(*, include_tenant_usage: bool = False) -> dict[str, object]:
    """Return a serializable health snapshot with observability stats."""
    snapshot = fetch_health_snapshot()
    payload: dict[str, object] = asdict(snapshot)

    # Database Ping (Implicit in fetch_health_snapshot query)
    payload["database_connected"] = True

    # Redis Ping
    from django.core.cache import cache

    try:
        cache.set("health_check_ping", "pong", timeout=5)
        payload["redis_connected"] = cache.get("health_check_ping") == "pong"
    except Exception:
        payload["redis_connected"] = False

    # Celery Ping (Optional / Lightweight)

    # For now, we assume Celery is up if Redis is up, as we use Redis broker.
    # A true generic task ping requires a result backend check.
    payload["celery_broker_connected"] = payload["redis_connected"]

    payload["pool_stats"] = get_pool_stats()
    payload["cache_stats"] = get_cache_stats()
    payload["import_security_limits"] = import_security_limits_snapshot()
    payload["hub_runtime_profile"] = summarize_hub_runtime_profile(resolve_hub_runtime_profile())
    if include_tenant_usage:
        global import_runtime_maintenance
        if import_runtime_maintenance is None:
            from server.services import import_runtime_maintenance as runtime_maintenance_service

            import_runtime_maintenance = runtime_maintenance_service
        tenant_usage = tenant_usage_gauge.compute_all_tenant_usage()
        payload["tenant_usage"] = tenant_usage
        match_snapshot = postgres_match_health.load_match_artifact_health_snapshot()
        profile_state = match_runtime_profile.effective_profile_state()
        payload["import_runtime_health"] = import_execution_governor.import_runtime_health_payload()
        payload["import_runtime_cleanup"] = import_runtime_maintenance.runtime_health_snapshot()
        payload["tenant_surface_classification_version"] = (
            schema_tenant_constants.tenant_surface_classification_version()
        )
        agency_ids = [
            agency_id
            for entry in tenant_usage
            if isinstance(entry, dict)
            for agency_id in [entry.get("agency_id")]
            if isinstance(agency_id, int) and agency_id > 0
        ]
        payload["tenant_budget_state"] = tenant_resource_governor.budget_state_snapshot(
            agency_ids=agency_ids,
            budget_names=[
                "import_parse",
                "import_execute",
                "match_pairs_rebuild",
                "match_cache_rebuild",
            ],
        )
        payload["offline_sync_health"] = {
            "available": False,
            "reason": "client_local_only",
        }
        try:
            with get_uow().session() as session:
                payload["match_rebuild_health"] = {
                    "pending_demande_rebuilds": match_rebuild_state.count_pending(
                        session,
                        scope="demande",
                    ),
                    "dispatchable_demande_rebuilds": match_rebuild_state.count_dispatchable(
                        session,
                        scope="demande",
                    ),
                    "claimed_demande_rebuilds": match_rebuild_state.count_claimed_dispatches(
                        session,
                        scope="demande",
                    ),
                    "expired_demande_dispatch_claims": (
                        match_rebuild_state.count_expired_dispatch_claims(
                            session,
                            scope="demande",
                        )
                    ),
                }
        except Exception:
            payload["match_rebuild_health"] = {
                "pending_demande_rebuilds": 0,
                "dispatchable_demande_rebuilds": 0,
                "claimed_demande_rebuilds": 0,
                "expired_demande_dispatch_claims": 0,
            }
        try:
            payload["import_learning_health"] = (
                import_learning_repository.import_learning_health_counts()
            )
        except Exception:
            payload["import_learning_health"] = {
                "trusted_agency_aliases": 0,
                "shadow_agency_aliases": 0,
                "rejected_agency_aliases": 0,
                "correction_signals": 0,
                "agency_profiles": 0,
                "dead_letter_rows": 0,
                "manual_mapping_required_jobs": 0,
            }
        if match_snapshot is not None:
            payload["match_artifact_health"] = asdict(match_snapshot)
        payload["match_runtime_profile"] = profile_state.profile
        payload["match_runtime_profile_reason"] = profile_state.reason
        payload["match_runtime_profile_sample_age_seconds"] = profile_state.sample_age_seconds
    return payload


def liveness() -> dict[str, object]:
    """Return a lightweight liveness payload (process is up)."""
    return {"status": "ok", "service": "immoapp-api", "alive": True}


def readiness() -> dict[str, object]:
    """Return dependency readiness suitable for orchestrators."""
    checks = {
        "database": _check_database(),
        "cache": _check_cache(),
        "broker": _check_broker(),
    }
    ready = all(bool(entry.get("ok")) for entry in checks.values())
    return {
        "status": "ready" if ready else "not_ready",
        "ready": ready,
        "checks": checks,
    }


def _check_database() -> dict[str, object]:
    try:
        with get_uow().session() as session:
            row = session.execute("SELECT 1 AS ok").fetchone()
            ok = bool(row and row.get("ok") == 1)
            return {"ok": ok}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _check_cache() -> dict[str, object]:
    from django.core.cache import cache

    try:
        cache.set("health_ready_ping", "pong", timeout=5)
        ok = cache.get("health_ready_ping") == "pong"
        return {"ok": bool(ok)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _check_broker() -> dict[str, object]:
    broker_url = os.environ.get("CELERY_BROKER_URL", "").strip()
    if not broker_url:
        return {"ok": False, "error": "CELERY_BROKER_URL not configured"}

    try:
        from kombu import Connection

        with Connection(broker_url, connect_timeout=2) as conn:
            conn.ensure_connection(max_retries=1)
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
