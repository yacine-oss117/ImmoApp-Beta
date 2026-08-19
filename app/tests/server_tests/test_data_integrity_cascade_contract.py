"""Contract tests for data integrity cascade behaviour."""

from __future__ import annotations

import ast
from pathlib import Path

_TASKS_MATCH_PAIRS = Path("server/api/tasks_match_pairs.py")
_MATCH_CACHE_READ = Path("core/data/match_cache_read.py")
_IMPORT_EXECUTOR = Path("server/services/import_executor.py")
_IMPORT_FINALIZE = Path("server/services/import_finalize_service.py")
_IMPORT_REBUILD_HANDOFF = Path("server/services/import_rebuild_handoff.py")
_MATCH_DETAILS = Path("core/matcher/match_details.py")
_SETTINGS_DATABASE = Path("server/immoapp_server/settings_database.py")
_IMPORT_REVIEW_VIEW = Path("server/api/views_import_review.py")
_IMPORT_REVIEW_PAYLOADS = Path("server/services/import_review_payloads.py")

_PAIR_MUTATING_TASKS = (
    "rebuild_match_pairs_for_demande",
    "rebuild_match_pairs_for_demandes_batch",
    "expand_match_pairs_for_demande",
    "rebuild_match_pairs_for_wilaya",
    "rebuild_match_pairs_for_client",
    "rebuild_match_pairs_for_offer",
)


def _function_source(path: Path, function_name: str) -> str:
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == function_name:
            source = ast.get_source_segment(text, node)
            if source is None:
                raise AssertionError(f"Could not extract source for {function_name}")
            return source
    raise AssertionError(f"Function {function_name} not found in {path}")


def test_janitor_schedule_is_at_most_fifteen_minutes() -> None:
    """The janitor must run at least every 15 minutes, not daily."""
    text = _SETTINGS_DATABASE.read_text(encoding="utf-8")
    assert '"match-janitor"' in text or "'match-janitor'" in text
    assert '"match-janitor-daily"' not in text
    assert "900.0" in text or "900" in text


def test_pair_mutating_tasks_cascade_count_cache_refresh() -> None:
    text = _TASKS_MATCH_PAIRS.read_text(encoding="utf-8")
    assert "def _cascade_count_cache_refresh" in text
    assert "rebuild_match_cache_dirty" in text
    for function_name in _PAIR_MUTATING_TASKS:
        source = _function_source(_TASKS_MATCH_PAIRS, function_name)
        assert "_cascade_count_cache_refresh(" in source, function_name


def test_match_cache_reads_only_use_match_counts_cache() -> None:
    text = _MATCH_CACHE_READ.read_text(encoding="utf-8")
    assert "match_counts_cache" in text
    assert "match_pairs" not in text


def test_import_executor_handles_all_post_import_entity_types() -> None:
    executor_text = _IMPORT_EXECUTOR.read_text(encoding="utf-8")
    finalize_text = _IMPORT_FINALIZE.read_text(encoding="utf-8")
    handoff_text = _IMPORT_REBUILD_HANDOFF.read_text(encoding="utf-8")
    assert "record_import_metrics" in executor_text
    assert "import_rebuild_handoff" in finalize_text
    assert "ENTITY_TYPE_CLIENT" in handoff_text
    assert "ENTITY_TYPE_DEMANDE" in handoff_text
    assert "ENTITY_TYPE_OFFER" in handoff_text
    assert "ENTITY_TYPE_LISTING" in handoff_text
    assert "enqueue_rebuild_demande_pairs_batch" in handoff_text
    assert "enqueue_rebuild_client_pairs" in handoff_text
    assert "enqueue_rebuild_offer_pairs" in handoff_text
    assert "enqueue_rebuild_wilaya_pairs" in handoff_text
    assert "rebuild_match_cache_dirty.delay" in handoff_text


def test_demande_detail_count_path_reads_match_pairs_directly() -> None:
    text = _MATCH_DETAILS.read_text(encoding="utf-8")
    assert "count_pairs_for_demande" in text
    assert "match_counts_cache" not in text


def test_import_review_submit_accepted_payload_includes_status_and_stage() -> None:
    payload_text = _IMPORT_REVIEW_PAYLOADS.read_text(encoding="utf-8")
    view_text = _IMPORT_REVIEW_VIEW.read_text(encoding="utf-8")

    assert '"request_status": "accepted"' in payload_text
    assert '"task_id": str(task_id or "")' in payload_text
    assert '"status": str(job.status)' in payload_text
    assert '"stage": str(job.stage)' in payload_text
    assert '"result_summary": dict(job.result_summary or {})' in payload_text
    assert "service.submit_review(" in view_text
    assert "HTTP_202_ACCEPTED" in view_text
