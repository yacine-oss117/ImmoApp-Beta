"""Fail if critical business metrics instrumentation is removed."""

from __future__ import annotations

from pathlib import Path

REQUIRED: dict[str, tuple[str, ...]] = {
    "server/immoapp_server/business_metrics_core.py": (
        "def _counter(",
        "def _histogram(",
        "def _observable_gauge(",
    ),
    "server/immoapp_server/business_metrics_imports.py": (
        "record_import_execution",
        "record_import_status_signal",
    ),
    "server/immoapp_server/business_metrics_match.py": (
        "record_match_pair_rebuild",
        "record_match_cache_lookup",
        "record_match_artifact_pipeline",
    ),
    "server/immoapp_server/business_metrics_governance.py": (
        "record_queue_saturation",
        "record_tenant_budget_event",
        "record_tenant_usage_gauge",
    ),
    "server/immoapp_server/business_metrics_runtime.py": ("record_http_request_latency",),
    "server/services/import_execution_metrics.py": ("record_import_execution(",),
    "server/services/import_executor.py": ("record_import_metrics(",),
    "server/api/match_pairs_compute.py": ("record_match_pair_rebuild(",),
    "server/services/match_cache.py": ("record_match_cache_lookup(",),
}

DELETED = "server/immoapp_server/business_metrics.py"


def main() -> int:
    missing: list[str] = []
    if Path(DELETED).exists():
        missing.append(f"{DELETED}: deleted sink reintroduced")
    for rel_path, tokens in REQUIRED.items():
        path = Path(rel_path)
        if not path.exists():
            missing.append(f"{rel_path}: file missing")
            continue
        text = path.read_text(encoding="utf-8")
        for token in tokens:
            if token not in text:
                missing.append(f"{rel_path}: missing token '{token}'")

    if missing:
        print("Business metrics instrumentation verification FAILED:")
        for issue in missing:
            print(f"- {issue}")
        return 1

    print("Business metrics instrumentation verification passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
