from __future__ import annotations

import ast
from pathlib import Path


def _read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def _module(path: str) -> ast.Module:
    return ast.parse(_read(path), filename=path)


def _canonical_identity_dict_literals(path: str) -> list[set[str]]:
    offenders: list[set[str]] = []
    required = {"schema", "agency_id", "correlation_id", "actor_id", "actor_role"}
    for node in ast.walk(_module(path)):
        if not isinstance(node, ast.Dict):
            continue
        keys = {
            key.value
            for key in node.keys
            if isinstance(key, ast.Constant) and isinstance(key.value, str)
        }
        if required.issubset(keys):
            offenders.append(keys)
    return offenders


def test_request_originated_match_and_cache_enqueues_use_canonical_async_identity_helper() -> None:
    matches_text = _read("server/api/views_matches.py")
    cache_text = _read("server/api/views_cache_tasks.py")

    assert "build_request_async_task_identity" in matches_text
    assert "build_request_async_task_identity" in cache_text
    assert "int(agency or 0)" not in matches_text


def test_service_side_match_async_handoffs_use_canonical_context_identity_helper() -> None:
    match_jobs_text = _read("server/services/match_jobs.py")
    handoff_text = _read("server/services/import_rebuild_handoff.py")
    task_pairs_text = _read("server/api/tasks_match_pairs.py")

    assert "build_context_async_task_identity" in match_jobs_text
    assert "build_context_async_task_identity" in handoff_text
    assert "build_async_task_identity" in task_pairs_text
    assert _canonical_identity_dict_literals("server/api/tasks_match_pairs.py") == []
