from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_run_import_perf_exposes_named_quick_and_medium_profiles() -> None:
    source = (REPO_ROOT / "scripts" / "run_import_perf.ps1").read_text(encoding="utf-8")
    for profile_name in (
        "quick_create",
        "quick_review",
        "medium_create",
        "medium_review",
    ):
        assert f'"{profile_name}"' in source


def test_perf_profiles_doc_tracks_script_profile_names() -> None:
    source = (REPO_ROOT / "docs" / "guides" / "PERF_PROFILES.md").read_text(encoding="utf-8")
    for profile_name in (
        "quick_create",
        "quick_review",
        "medium_create",
        "medium_review",
    ):
        assert f"-Profile {profile_name}" in source
