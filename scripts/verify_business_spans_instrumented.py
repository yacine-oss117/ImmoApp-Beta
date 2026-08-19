"""Fail if critical business span instrumentation is removed."""

from __future__ import annotations

from pathlib import Path

REQUIRED: dict[str, tuple[str, ...]] = {
    "server/api/match_pairs_compute.py": ("matcher.compute_pairs_for_demande",),
    "server/services/matches.py": (
        "matcher.fetch_matches_for_demande",
        "matcher.fetch_matches_for_client",
    ),
    "server/api/tasks_match_pairs.py": ("matcher.task.rebuild_pairs_for_demande",),
    "server/services/storage_ops_upload_presign.py": (
        "storage.generate_presigned_upload",
        "storage.complete_presigned_upload",
    ),
    "server/services/storage_ops_access.py": ("storage.generate_download_url",),
    "server/services/storage_ops_maintenance.py": (
        "storage.mark_deleted",
        "storage.purge_deleted_objects",
    ),
}


def main() -> int:
    missing: list[str] = []

    for rel_path, span_names in REQUIRED.items():
        path = Path(rel_path)
        if not path.exists():
            missing.append(f"{rel_path}: file missing")
            continue
        text = path.read_text(encoding="utf-8")
        if "business_span(" not in text:
            missing.append(f"{rel_path}: business_span() usage missing")
        for span_name in span_names:
            if span_name not in text:
                missing.append(f"{rel_path}: missing span '{span_name}'")

    if missing:
        print("Business span instrumentation verification FAILED:")
        for issue in missing:
            print(f"- {issue}")
        return 1

    print("Business span instrumentation verification passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
