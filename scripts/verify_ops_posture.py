from __future__ import annotations

from pathlib import Path

from repo_layout import OPS_POLICY_ROOT, OPS_RUNBOOK_ROOT, PIP_AUDIT_IGNORE


def _require(path: str) -> Path:
    p = Path(path)
    if not p.exists():
        raise SystemExit(f"verify_ops_posture: missing required file {path}")
    return p


def _assert_tokens(path: Path, tokens: tuple[str, ...]) -> None:
    text = path.read_text(encoding="utf-8")
    for token in tokens:
        if token not in text:
            raise SystemExit(f"verify_ops_posture: {path} missing token: {token}")


def main() -> None:
    slo_doc = _require(OPS_POLICY_ROOT / "SLO_AND_RELEASE_GUARDRAILS.md")
    restore_doc = _require(OPS_RUNBOOK_ROOT / "RESTORE_DRILL_RUNBOOK.md")
    observability_doc = _require("docs/guides/OBSERVABILITY.md")
    db_schema_doc = _require("docs/reference/DB_SCHEMA_REFERENCE.md")
    api_policy_doc = _require("docs/reference/API_VERSIONING_PAGINATION_POLICY.md")
    load_doc = _require("docs/reference/LOAD_TESTING_BASELINE.md")
    domain_matrix_doc = _require("docs/reference/DOMAIN_INTEGRATION_MATRIX.md")
    ops_slo = _require(OPS_POLICY_ROOT / "slo.yaml")
    game_day_policy = _require(OPS_POLICY_ROOT / "GAME_DAY_POLICY.md")
    runbook_db = _require("ops/runbooks/db-down.md")
    runbook_queue = _require("ops/runbooks/queue-down.md")
    runbook_storage = _require("ops/runbooks/storage-down.md")
    runbook_migration = _require("ops/runbooks/migration-failure.md")
    runbook_restore = _require("ops/runbooks/restore-drill.md")
    runbook_keys = _require("ops/runbooks/key-rotation.md")
    dep_audit_policy = _require(PIP_AUDIT_IGNORE)

    _assert_tokens(
        slo_doc,
        (
            "SLO Targets",
            "p95",
            "Error Budget",
            "Alert Thresholds",
            "Canary Rollout",
            "Rollback Playbook",
            "On-call Runbook",
            "/api/v1/health/",
        ),
    )
    _assert_tokens(
        restore_doc,
        (
            "Run this drill at least monthly",
            "verify_restore_drill_execution.py",
            "tenant smoke checks",
        ),
    )
    _assert_tokens(
        observability_doc,
        (
            "SigNoz",
            "OTEL_EXPORTER_OTLP_ENDPOINT",
            "Django request tracing",
            "Celery task tracing",
        ),
    )
    _assert_tokens(
        db_schema_doc,
        (
            "Tenant Isolation",
            "RLS",
            "FORCE RLS",
            "match_rebuild_state",
            "storage_objects",
        ),
    )
    _assert_tokens(
        api_policy_doc,
        (
            "/api/v1/",
            "items",
            "total",
            "next_cursor",
            "verify_no_exception_leakage.py",
        ),
    )
    _assert_tokens(
        load_doc,
        (
            "verify_query_budgets.py",
            "verify_load_baseline.py",
            "verify_api_queue_baseline.py",
            "p95",
        ),
    )
    _assert_tokens(
        domain_matrix_doc,
        (
            "Importer",
            "Storage",
            "CRM Lifecycle",
            "Security/RLS/Auth",
            "verify_domain_integration_matrix.py",
        ),
    )
    _assert_tokens(
        ops_slo,
        (
            "api_availability",
            "api_latency",
            "background_tasks",
            "queue_backlog",
            "db_pool",
            "alerts",
        ),
    )
    _assert_tokens(runbook_db, ("Trigger", "Recovery", "Rollback"))
    _assert_tokens(runbook_queue, ("Trigger", "Recovery", "Rollback"))
    _assert_tokens(runbook_storage, ("Trigger", "Recovery", "Rollback"))
    _assert_tokens(runbook_migration, ("Trigger", "Recovery", "Rollback"))
    _assert_tokens(runbook_restore, ("Policy", "Procedure", "Success Criteria"))
    _assert_tokens(runbook_keys, ("ALE Rotation", "Validation", "Rollback"))
    _assert_tokens(dep_audit_policy, ("[", "]"))
    _assert_tokens(
        game_day_policy,
        (
            "Scenarios",
            "Combined DB+queue+storage outage/recovery validation",
            "Automation",
            "RTO",
            "report",
            "Success Criteria",
        ),
    )

    print("verify_ops_posture: OK")


if __name__ == "__main__":
    main()
