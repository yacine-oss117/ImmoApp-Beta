from __future__ import annotations

import ast
from pathlib import Path


def _read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def _module(path: str) -> ast.Module:
    return ast.parse(_read(path), filename=path)


def _function_names(path: str) -> set[str]:
    return {
        node.name
        for node in _module(path).body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _imported_modules(path: str) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(_module(path)):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def _imported_names_from(path: str, module: str) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(_module(path)):
        if isinstance(node, ast.ImportFrom) and node.module == module:
            names.update(alias.name for alias in node.names)
    return names


def _fn(path: str, name: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    for node in _module(path).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"Function {name} not found in {path}")


def _line_count(path: str) -> int:
    return len(_read(path).splitlines())


def test_views_import_execute_stays_view_only() -> None:
    path = "server/api/views_import_execute.py"
    imports = _imported_modules(path)
    text = _read(path)

    assert "server.services.import_execute_request" in imports
    assert "server.services.import_status_api_facade" in imports
    facade_imports = _imported_modules("server/services/import_status_api_facade.py")
    assert "server.services.import_cancel_flow" in facade_imports
    assert "server.services.import_status_payload" in facade_imports
    assert "def _optional_int(" not in text
    assert "def _coerce_progress_int(" not in text
    assert "def _coerce_summary_mapping(" not in text
    assert "def _status_poll_after_ms(" not in text
    assert "def _queue_poll_after_ms(" not in text
    assert "def _cached_agency_queue_depth(" not in text
    assert _line_count(path) <= 260


def test_import_prepare_service_stays_thin_facade() -> None:
    path = "server/services/import_prepare_service.py"

    assert "server.services.import_prepare_flows" in _imported_modules(path)
    assert _function_names(path) == {
        "prepare_child_only_import",
        "prepare_same_side_bundle_import",
        "prepare_single_entity_import",
    }
    assert _line_count(path) <= 140


def test_import_planning_service_stays_thin_facade() -> None:
    path = "server/services/import_planning_service.py"

    assert "server.services.import_plan_flows" in _imported_modules(path)
    assert _function_names(path) == {
        "_apply_planning_recovery",
        "_blocked_duplicate_resolution_error",
        "plan_child_only_import",
        "plan_same_side_bundle_import",
        "plan_single_entity_import",
        "prefetch_child_match_cache",
        "prefetch_root_match_cache",
        "resolve_child_anchor",
        "resolve_existing_matches",
        "validate_row",
    }
    assert _line_count(path) <= 220


def test_import_chunk_workflow_stays_facade_over_split_helpers() -> None:
    path = "server/services/import_chunk_workflow.py"
    imports = _imported_modules(path)
    functions = _function_names(path)

    assert "server.services.import_workflow_storage" in imports
    assert "server.services.import_workflow_manifests" in imports
    assert "server.services.import_workflow_leases" in imports
    assert "server.services.import_workflow_dispatch" in imports
    assert "_workflow_state_payload" not in functions
    assert "_copy_payload_to_workflow_state" not in functions
    assert "persist_json_manifest" not in functions
    assert "persist_jsonl_manifest" not in functions
    assert "persist_file_manifest" not in functions
    assert "manifest_for_chunk" not in functions
    assert "job_manifest" not in functions
    assert "acquire_phase" not in functions
    assert "complete_phase" not in functions
    assert "fail_phase" not in functions
    assert "heartbeat_phase_lease" not in functions
    assert "phase_lease_active" not in functions
    assert "cancel_pending_phases" not in functions
    assert "requeue_expired_import_phases" not in functions
    assert "advance_workflow_dispatch" not in functions
    assert "rollup_workflow_progress" not in functions
    assert "_aggregate_review_overflow_count" not in functions
    assert _line_count(path) <= 280


def test_import_control_plane_stays_thin_compatibility_facade() -> None:
    path = "server/services/import_control_plane.py"

    assert "server.services.import_execution_state" in _imported_modules(path)
    assert "server.services.import_cancel_flow" in _imported_modules(path)
    assert "server.services.import_workflow_dispatch" in _imported_modules(path)
    assert _function_names(path) == {"cancel_import_immediately"}
    assert _line_count(path) <= 100


def test_import_executor_uses_checkpoint_helper_and_not_inline_checkpoint_internals() -> None:
    path = "server/services/import_executor.py"
    text = _read(path)
    functions = _function_names(path)

    assert "server.services.import_executor_checkpoint" in _imported_modules(path)
    assert "from server.services.import_artifact_checkpoint import" not in text
    assert "_restore_planned_checkpoint_state" not in functions
    assert "_persist_direct_execution_state" in functions
    assert "_mark_job_failed" in functions
    assert "_clear_planned_checkpoint_best_effort" in functions
    assert _line_count(path) <= 460


def test_import_executor_helpers_stays_batch_write_seam() -> None:
    path = "server/services/import_executor_helpers.py"
    imports = _imported_modules(path)
    functions = _function_names(path)

    assert "server.pg.lookup_resolver" in imports
    assert "server.services.import_review_duplicates" in imports
    assert "server.services.import_rows" in imports
    assert "server.services.import_prepare_service" not in imports
    assert "server.services.import_planning_service" not in imports
    assert "server.services.import_load_service" not in imports
    assert "server.services.import_finalize_service" not in imports
    assert {"collect_listing_wilaya_ids", "insert_batch"}.issubset(functions)
    assert "insert_batch_refs" not in functions
    assert "_build_candidate_field_diffs" not in functions
    assert "execute_import" not in functions
    assert _line_count(path) <= 250


def test_tasks_import_stays_task_entry_surface() -> None:
    path = "server/api/tasks_import.py"
    imports = _imported_modules(path)
    functions = _function_names(path)
    text = _read(path)

    assert "tasks_import_parse" in imports
    assert "tasks_import_execute" in imports
    assert "tasks_import_phase_tasks" in imports
    assert functions == {
        "_enqueue_prepare_phase_task",
        "_queue_import_dispatch",
        "import_execute_task",
        "import_finalize_job_task",
        "import_load_chunk_task",
        "import_parse_task",
        "import_plan_chunk_task",
        "import_prepare_phase_task",
    }
    assert "def _friendly_import_failure_message(" not in text
    assert "def _collect_distributed_failure_errors(" not in text
    assert "def _semantic_inference_inputs(" not in text
    assert "def _semantic_evidence_inputs(" not in text
    assert "def _cleanup_prepared_artifact(" not in text
    assert "def _mark_distributed_job_failed(" not in text
    assert "def _phase_retryable(" not in text
    assert "def _handle_phase_exception(" not in text
    assert _line_count(path) <= 260


def test_tasks_import_parse_owns_parse_runner_and_semantic_projection_helpers() -> None:
    path = "server/api/tasks_import_parse.py"
    imports = _imported_modules(path)
    functions = _function_names(path)

    assert "server.services.import_column_semantics" in imports
    assert "tasks_import_helpers" in imports
    assert functions == {
        "_semantic_evidence_inputs",
        "_semantic_inference_inputs",
        "run_import_parse_task",
    }
    assert _line_count(path) <= 340


def test_tasks_import_failures_own_task_failure_helpers() -> None:
    path = "server/api/tasks_import_failures.py"
    imports = _imported_modules(path)
    functions = _function_names(path)

    assert "server.services.import_execution_state" in imports
    assert "server.services.import_review_store" in imports
    assert functions == {
        "collect_distributed_failure_errors",
        "friendly_import_failure_message",
        "handle_phase_exception",
        "mark_distributed_job_failed",
        "phase_retryable",
    }
    assert _line_count(path) <= 250


def test_tasks_import_execute_owns_execute_runner() -> None:
    path = "server/api/tasks_import_execute.py"
    imports = _imported_modules(path)
    functions = _function_names(path)
    text = _read(path)

    assert "server.services.import_chunk_workflow" in imports
    assert "tasks_import_failures" in imports
    assert "server.api.tasks_import" not in imports
    assert functions == {"run_import_execute_task"}
    assert "class QueueImportDispatchFn" in text
    assert "class EnqueuePreparePhaseTaskFn" in text
    assert _line_count(path) <= 280


def test_tasks_import_phase_tasks_own_phase_runners_and_cleanup() -> None:
    path = "server/api/tasks_import_phase_tasks.py"
    imports = _imported_modules(path)
    functions = _function_names(path)
    text = _read(path)

    assert "server.services.import_prepare_service" in imports
    assert "server.services.import_finalize_service" in imports
    assert "server.services.import_phase_attempts" in imports
    assert "ImportPhaseAttemptCancelled" in text
    assert "cancel_phase_attempt(" in text
    assert "cancelled = cancel_phase_attempt(" in text
    assert 'status = "cancelled" if cancelled else "stale"' in text
    assert "tasks_import_failures" in imports
    assert "server.api.tasks_import" not in imports
    runner_fn = _fn(path, "_run_chunk_phase_task")
    cancel_handler = next(
        handler
        for handler in ast.walk(runner_fn)
        if isinstance(handler, ast.ExceptHandler)
        and getattr(handler.type, "id", "") == "ImportPhaseAttemptCancelled"
    )
    cancel_branch = ast.get_source_segment(text, cancel_handler) or ""
    assert "complete_phase_attempt(" not in cancel_branch
    assert "queue_import_dispatch_fn(" not in cancel_branch
    assert "handle_phase_exception(" not in cancel_branch
    assert functions == {
        "_run_chunk_phase_task",
        "cleanup_prepared_artifact",
        "run_import_finalize_job_task",
        "run_import_load_chunk_task",
        "run_import_plan_chunk_task",
        "run_import_prepare_phase_task",
    }
    assert "class QueueImportDispatchFn" in text
    assert _line_count(path) <= 400


def test_import_execution_runtime_stays_deleted() -> None:
    path = "server/services/import_execution_runtime.py"

    assert not Path(path).exists()


def test_importer_production_modules_do_not_import_deleted_runtime_sink() -> None:
    patterns = (
        "server/services/import*.py",
        "server/api/tasks_import*.py",
        "server/api/views_import*.py",
    )
    offenders: list[str] = []

    for pattern in patterns:
        for path in Path(".").glob(pattern):
            if path.as_posix() == "server/services/import_execution_runtime.py":
                continue
            if "server.services.import_execution_runtime" in _imported_modules(path.as_posix()):
                offenders.append(path.as_posix())

    assert offenders == []


def test_import_review_runtime_owns_review_overflow_helpers() -> None:
    path = "server/services/import_review_runtime.py"
    imports = _imported_modules(path)

    assert "core.importer.security" in imports
    assert "server.services.import_types" in imports
    assert _function_names(path) == {
        "append_review_row_limited",
        "record_review_overflow",
        "review_overflow_count",
        "review_overflow_errors",
    }
    assert _line_count(path) <= 100


def test_import_runtime_artifacts_owns_jsonl_and_path_helpers() -> None:
    path = "server/services/import_runtime_artifacts.py"
    imports = _imported_modules(path)

    assert "server.services.json_safe" in imports
    assert _function_names(path) == {
        "entry_dict",
        "entry_int",
        "entry_row_num",
        "entry_str",
        "entry_str_list",
        "iter_jsonl_entries",
        "iter_jsonl_entry_batches",
        "require_path",
        "write_jsonl_entry",
    }
    assert _line_count(path) <= 140


def test_import_progress_runtime_owns_progress_payload_and_persistence() -> None:
    path = "server/services/import_progress_runtime.py"
    imports = _imported_modules(path)

    assert "core.data" in imports
    assert "server.pg.uow" in imports
    assert _function_names(path) == {
        "_progress_pool_timeout_seconds",
        "build_progress_detail",
        "persist_job_progress",
    }
    assert _line_count(path) <= 170


def test_import_review_runtime_state_owns_review_state_persistence_and_notification() -> None:
    path = "server/services/import_review_runtime_state.py"
    imports = _imported_modules(path)

    assert "server.services.import_review_runtime" in imports
    assert "server.services.import_review_store" in imports
    assert "server.services.import_notifications" in imports
    assert _function_names(path) == {
        "emit_review_required_notification",
        "persist_review_state",
    }
    assert _line_count(path) <= 140


def test_import_review_row_runtime_owns_review_row_shaping_and_anchors() -> None:
    path = "server/services/import_review_row_runtime.py"
    imports = _imported_modules(path)

    assert "server.services.import_diff_builder" in imports
    assert "server.services.import_review_policy" in imports
    assert "server.services.import_types" in imports
    assert _function_names(path) == {
        "anchor_map_keys",
        "manual_review_row",
        "normalized_review_fields",
        "remember_anchor",
        "review_row_from_resolution",
    }
    assert _line_count(path) <= 230


def test_import_distributed_execution_stays_thin_phase_surface() -> None:
    path = "server/services/import_distributed_execution.py"
    imports = _imported_modules(path)
    functions = _function_names(path)
    plan_fn = _fn(path, "plan_chunk_phase")
    load_fn = _fn(path, "load_chunk_phase")

    assert "server.services.import_distributed_plan_phase" in imports
    assert "server.services.import_distributed_load_phase" in imports
    assert "server.services.import_phase_attempts" in imports
    assert "_plan_phase_deps" in functions
    assert "_load_phase_deps" in functions
    assert len(plan_fn.body) == 1 and isinstance(plan_fn.body[0], ast.Return)
    assert len(load_fn.body) == 1 and isinstance(load_fn.body[0], ast.Return)
    assert _line_count(path) <= 520


def test_import_distributed_plan_phase_owns_planning_body() -> None:
    path = "server/services/import_distributed_plan_phase.py"
    imports = _imported_modules(path)
    functions = _function_names(path)
    text = _read(path)

    assert "server.services.import_planning_service" in imports
    assert "server.services.import_identity_resolution" in imports
    assert "server.services.import_review_row_runtime" in imports
    assert "server.services.import_review_runtime" in imports
    assert "server.services.import_runtime_artifacts" in imports
    assert "run_with_phase_attempt_fence_fn" in text
    assert "raise_phase_attempt_cancelled(" in text
    assert "cancelled_before_apply" not in text
    assert "cancelled_mid_chunk" not in text
    assert "server.services.import_execution_runtime" not in imports
    assert functions == {"run_plan_chunk_phase"}
    assert _line_count(path) <= 590


def test_import_distributed_load_phase_owns_load_body_and_counting() -> None:
    path = "server/services/import_distributed_load_phase.py"
    imports = _imported_modules(path)
    functions = _function_names(path)
    text = _read(path)

    assert "server.services.import_load_accounting" in imports
    assert "server.services.import_load_policy" in imports
    assert "server.services.import_load_service" in imports
    assert "server.services.import_runtime_artifacts" in imports
    assert "child_anchor_failure_delta" not in text
    assert "run_with_phase_attempt_fence_fn" in text
    assert "raise_phase_attempt_cancelled(" in text
    assert "cancelled_before_apply" not in text
    assert "cancelled_mid_chunk" not in text
    assert functions == {"run_load_chunk_phase"}
    assert _line_count(path) <= 370


def test_ref_based_importer_paths_depend_on_canonical_ref_seam_directly() -> None:
    ref_module = "server.services.import_batch_write_refs"

    assert "insert_batch_refs" in _imported_names_from(
        "server/services/import_load_policy.py",
        ref_module,
    )
    assert "insert_batch_refs" in _imported_names_from(
        "server/services/import_load_conflict_isolation.py",
        ref_module,
    )
    assert "insert_batch_refs" not in _imported_names_from(
        "server/services/import_load_service.py",
        ref_module,
    )
    assert "insert_batch_refs" in _imported_names_from(
        "server/services/import_distributed_execution.py",
        ref_module,
    )
    assert "insert_batch_refs" in _imported_names_from(
        "server/services/import_review_resolution_creates.py",
        ref_module,
    )
    assert "insert_batch_refs" not in _imported_names_from(
        "server/services/import_review_resolution.py",
        ref_module,
    )


def test_import_review_created_rows_requires_explicit_job_id_contract() -> None:
    path = "server/services/import_review_created_rows.py"
    functions = _function_names(path)
    text = _read(path)

    assert "call_insert_review_corrections" in functions
    assert "insert_review_corrections_supports_job_id" not in functions
    assert "inspect.signature" not in text
    assert "job_id=job_id" in text


def test_repo_batch_writers_depend_on_neutral_ref_contract() -> None:
    contract_module = "core.contracts.import_batch_refs"
    legacy_module = "server.services.import_types"
    writer_paths = [
        "core/data/client_repo_write.py",
        "core/data/listing_repo_write.py",
        "core/data/demande_repo_write_create.py",
        "core/data/offer_repo_write.py",
    ]

    for path in writer_paths:
        assert "CreatedRowRef" in _imported_names_from(path, contract_module)
        assert "CreatedRowRef" not in _imported_names_from(path, legacy_module)


def test_import_review_duplicates_stays_narrow_review_row_shaper() -> None:
    path = "server/services/import_review_duplicates.py"
    imports = _imported_modules(path)
    functions = _function_names(path)

    assert "server.services.duplicate_checker" in imports
    assert "server.services.import_diff_builder" in imports
    assert "server.services.import_review_policy" in imports
    assert "server.services.import_review_runtime" in imports
    assert "server.services.import_execution_runtime" not in imports
    assert "server.services.import_executor" not in imports
    assert "server.services.import_prepare_service" not in imports
    assert "server.services.import_planning_service" not in imports
    assert "server.services.import_load_service" not in imports
    assert "server.services.import_finalize_service" not in imports
    assert "append_db_duplicate_reviews" in functions
    assert _line_count(path) <= 240


def test_import_finalize_service_stays_finalization_orchestrator() -> None:
    path = "server/services/import_finalize_service.py"
    imports = _imported_modules(path)
    functions = _function_names(path)
    text = _read(path)
    finalize_fn = _fn(path, "finalize_distributed_import_job")

    assert "server.services.import_follow_up" in imports
    assert "server.services.import_rebuild_handoff" in imports
    assert "server.services.import_job_topology" in imports
    assert "server.services.import_execution_metrics" in imports
    assert functions == {
        "_decide_terminal_state",
        "_emit_terminal_notification",
        "_existing_finalized_payload",
        "_finalize_progress_detail",
        "_workflow_duration_seconds",
        "_rollup_load_phase",
        "_rollup_review_phase",
        "_save_finalized_job",
        "_terminal_notification_data",
        "_update_terminal_result_summary",
        "_json_safe_dict",
        "_json_safe_dict_list",
        "finalize_distributed_import_job",
    }
    assert "normalize_follow_up_outcome" not in functions
    assert "merge_follow_up_outcomes" not in functions
    assert "persist_post_import_follow_up" not in functions
    assert "run_post_import_follow_up" not in functions
    assert "enqueue_post_import_rebuilds" not in functions
    assert "enqueue_post_import_rebuilds_for_entities" not in functions
    assert "schedule_single_entity_after_commit" not in functions
    assert "schedule_bundle_after_commit" not in functions
    assert "schedule_review_corrections_after_commit" not in functions
    assert "job_topology" not in functions
    assert "record_import_metrics" not in functions
    collected_index = next(
        index
        for index, stmt in enumerate(finalize_fn.body)
        if isinstance(stmt, ast.Assign)
        and "collected_review_rows(job)" in (ast.get_source_segment(text, stmt) or "")
    )
    cleanup_try = finalize_fn.body[collected_index + 1]
    assert isinstance(cleanup_try, ast.Try)
    assert cleanup_try.finalbody
    assert finalize_fn.body[collected_index + 2 :] == []
    finally_source = "\n".join(
        ast.get_source_segment(text, stmt) or "" for stmt in cleanup_try.finalbody
    )
    assert 'getattr(review_rows, "cleanup", None)' in finally_source
    assert "cleanup_review_rows()" in finally_source
    assert _line_count(path) <= 700


def test_import_review_metadata_safety_stays_nested_by_default() -> None:
    path = "server/services/import_review_metadata_safety.py"
    text = _read(path)
    functions = _function_names(path)
    projection_source = ast.get_source_segment(text, _fn(path, "project_review_metadata")) or ""

    assert functions == {
        "non_shadowing_review_metadata",
        "project_review_metadata",
    }
    assert "PROMOTED_REVIEW_METADATA_KEYS: frozenset[str] = frozenset()" in text
    assert "projected.update(safe_metadata)" not in projection_source
    assert "projected |= safe_metadata" not in projection_source
    assert "for key, value in safe_metadata.items()" not in projection_source
    assert 'projected["metadata"] = existing_metadata' in projection_source
    assert "for key in PROMOTED_REVIEW_METADATA_KEYS" in projection_source


def test_import_status_payload_stays_projection_only() -> None:
    path = "server/services/import_status_payload.py"
    imports = _imported_modules(path)
    text = _read(path)
    functions = _function_names(path)

    assert "server.services.import_follow_up" in imports
    assert "server.services.import_status_contracts" in imports
    assert "server.services.import_status_policy" in imports
    assert "server.services.import_status_summary" in imports
    assert "server.services.import_finalize_service" not in imports
    assert functions == {"_dict_copy", "_items", "build_import_status_payload"}
    assert "def status_poll_after_ms(" not in text
    assert "def queue_poll_after_ms(" not in text
    assert "def cached_agency_queue_depth(" not in text
    assert "def live_agency_queue_depth(" not in text
    assert "def optional_int(" not in text
    assert "def coerce_progress_int(" not in text
    assert "def coerce_summary_mapping(" not in text
    assert "Callable[..., Any]" not in text
    assert _line_count(path) <= 320


def test_import_status_summary_owns_derived_status_summary() -> None:
    path = "server/services/import_status_summary.py"
    imports = _imported_modules(path)
    functions = _function_names(path)
    text = _read(path)

    assert "server.services.import_status_contracts" in imports
    assert "server.services.import_status_payload" not in imports
    assert "class ImportStatusSummary" in text
    assert functions == {"_dict_copy", "_items", "_rows", "build_import_status_summary"}
    assert _line_count(path) <= 220


def test_import_follow_up_owns_follow_up_state_and_legacy_bridge() -> None:
    path = "server/services/import_follow_up.py"
    imports = _imported_modules(path)
    functions = _function_names(path)
    text = _read(path)

    assert "server.services.import_finalize_service" not in imports
    assert "normalize_follow_up_outcome" in functions
    assert "merge_follow_up_outcomes" in functions
    assert "run_post_import_follow_up" in functions
    assert "persist_post_import_follow_up" in functions
    assert "_resolve_follow_up_job" in functions
    assert "_merge_follow_up_payload" in functions
    assert "_resolve_workflow_follow_up_payload" in functions
    assert "_apply_follow_up_to_result_summary" in functions
    assert "_save_follow_up_state" in functions
    assert "class FollowUpPersistenceTarget" in text
    assert "dashboard_invalidation" not in text
    assert _line_count(path) <= 500


def test_import_load_service_stays_transactional_load_owner() -> None:
    path = "server/services/import_load_service.py"
    imports = _imported_modules(path)
    functions = _function_names(path)
    text = _read(path)

    assert "server.services.import_load_shared" in imports
    assert "server.services.import_load_conflict_isolation" in imports
    assert "server.services.import_rebuild_handoff" in imports
    assert "server.services.import_finalize_service" not in imports
    assert "class ImportLoadConsistencyError" in text
    assert "class PlannedInsertEntry" not in text
    assert "class ChildAnchorErrorRow" not in text
    assert "class ImportLoadProgressSnapshot" not in text
    assert "def _flush_insert_entries(" not in text
    assert "def _persist_load_progress(" not in text
    assert "def _finalize_successful_load(" not in text
    assert "def _exception_sqlstate(" not in text
    assert "def _flush_bundle_root_entries_with_conflict_isolation(" not in text
    assert "def _is_unique_violation(" not in text
    assert functions == {
        "load_child_only_import",
        "load_same_side_bundle_import",
        "load_single_entity_import",
    }
    assert "write_session: Any" not in text
    assert _line_count(path) <= 540


def test_import_load_conflict_isolation_owns_direct_bundle_root_conflict_adapter() -> None:
    path = "server/services/import_load_conflict_isolation.py"
    imports = _imported_modules(path)
    functions = _function_names(path)
    text = _read(path)

    assert "server.services.import_load_policy" in imports
    assert "server.services.import_batch_write_refs" in imports
    assert "server.services.import_load_shared" not in imports
    assert "server.services.import_rebuild_handoff" not in imports
    assert "persist_job_progress" not in text
    assert "schedule_single_entity_after_commit" not in text
    assert "schedule_bundle_after_commit" not in text
    assert functions == {"_flush_bundle_root_entries_with_conflict_isolation"}
    assert _line_count(path) <= 150


def test_import_load_shared_owns_progress_and_success_tail() -> None:
    path = "server/services/import_load_shared.py"
    imports = _imported_modules(path)
    functions = _function_names(path)
    text = _read(path)

    assert "server.services.import_progress_runtime" in imports
    assert "server.services.import_execution_runtime" not in imports
    assert "server.services.import_executor_helpers" in imports
    assert "server.services.import_load_service" not in imports
    assert "class PlannedInsertEntry" in text
    assert "class ChildAnchorErrorRow" in text
    assert "class ImportLoadProgressSnapshot" in text
    assert functions == {
        "finalize_successful_load",
        "flush_insert_entries",
        "persist_load_progress_snapshot",
    }
    assert _line_count(path) <= 150


def test_import_review_resolution_stays_apply_orchestrator() -> None:
    path = "server/services/import_review_resolution.py"
    imports = _imported_modules(path)
    functions = _function_names(path)
    text = _read(path)
    action_imports = _imported_names_from(path, "server.services.import_review_row_actions")
    conflict_imports = _imported_names_from(path, "server.services.import_review_conflicts")
    create_imports = _imported_names_from(path, "server.services.import_review_resolution_creates")

    assert "server.services.import_review_row_actions" in imports
    assert "server.services.import_review_conflicts" in imports
    assert "server.services.import_review_resolution_creates" in imports
    assert "server.services.import_review_resolution_errors" in imports
    assert action_imports <= {
        "AppliedReviewRow",
        "ReviewResolutionState",
        "collect_review_actions",
        "normalize_resolution_inputs",
    }
    assert conflict_imports <= {"RowConflict"}
    assert create_imports == {"apply_pending_creates"}
    assert "_apply_pending_creates" not in functions
    assert "_apply_pending_updates" in functions
    assert "update_dispatchers =" in text
    assert "fail-fast first-conflict semantics" in text
    assert "elif update_entity_type ==" not in text
    assert "def insert_review_correction_batches_impl(" not in text
    assert "def insert_review_corrections_impl(" not in text
    assert "class PendingUpdateRow" not in text
    assert "class AppliedReviewRow" not in text
    assert "_review_entry_fields" not in functions
    assert "_review_entry_remarks" not in functions
    assert "def collect_review_actions(" not in text
    assert "def normalize_resolution_inputs(" not in text
    assert _line_count(path) <= 260


def test_import_review_resolution_creates_owns_atomic_create_batches() -> None:
    path = "server/services/import_review_resolution_creates.py"
    imports = _imported_modules(path)
    functions = _function_names(path)
    text = _read(path)

    assert "server.services.import_review_created_rows" in imports
    assert "server.services.import_review_resolution_errors" in imports
    assert "server.services.import_review_conflicts" in imports
    assert {
        "apply_pending_creates",
        "insert_review_correction_batches_impl",
        "insert_review_corrections_impl",
    }.issubset(functions)
    assert "get_uow().transaction" in text
    assert "require_created_rows_match_pending" in text
    assert "schedule_review_corrections_after_commit" in text
    assert "CreatedRowRef" in text
    assert _line_count(path) <= 380


def test_import_review_row_actions_owns_row_action_collection() -> None:
    path = "server/services/import_review_row_actions.py"
    imports = _imported_modules(path)
    functions = _function_names(path)
    text = _read(path)

    assert "server.services.import_review_conflicts" in imports
    assert "server.services.import_review_shapes" in imports
    assert "class ReviewResolutionInputs" in text
    assert "class ReviewResolutionState" in text
    assert "class PendingUpdateRow" in text
    assert "class AppliedReviewRow" in text
    assert "_PROTECTED_REVIEW_ROW_KEYS" in text
    assert {
        "_as_dict",
        "_as_list",
        "_coerce_int",
        "_normalized_review_fields",
        "_review_entry_fields",
        "_review_entry_remarks",
        "_still_review_row",
        "collect_review_actions",
        "normalize_resolution_inputs",
    }.issubset(functions)
    assert _line_count(path) <= 650


def test_import_prepare_single_flow_names_review_handling_phases() -> None:
    path = "server/services/import_prepare_single_flow.py"
    functions = _function_names(path)

    assert {
        "_append_single_entity_review_row",
        "_handle_initial_review_requirement",
        "_handle_post_dedup_review_requirement",
    }.issubset(functions)


def test_import_review_conflicts_owns_preflight_conflict_detection() -> None:
    path = "server/services/import_review_conflicts.py"
    functions = _function_names(path)
    imports = _imported_modules(path)
    text = _read(path)

    assert "server.services.import_review_phone_conflicts" in imports
    assert "detect_create_conflicts" in functions
    assert "load_job_field_price_metadata" in functions
    assert "conflict_detail" in functions
    assert "conflict_type_for_entity" in functions
    assert "_detect_create_conflicts" not in functions
    assert "_find_existing_phone_match" not in functions
    assert "_existing_summary" not in functions
    assert "_existing_phone_matches" not in functions
    assert "_job_field_price_metadata" not in functions
    assert "class PendingCreateRow" in text
    assert "class RowConflict" in text
    assert _line_count(path) <= 220


def test_import_review_phone_conflicts_owns_phone_match_lookup() -> None:
    path = "server/services/import_review_phone_conflicts.py"
    functions = _function_names(path)
    text = _read(path)

    assert "existing_phone_matches" in functions
    assert "existing_summary" in functions
    assert "get_uow().session" in text
    assert "candidate_summaries" in text
    assert _line_count(path) <= 120


def test_import_review_shapes_owns_review_row_and_audit_projection() -> None:
    path = "server/services/import_review_shapes.py"
    functions = _function_names(path)
    type_imports = _imported_names_from(path, "server.services.import_types")

    assert "ReviewAuditEntryPayload" in type_imports
    assert {
        "_coerce_float",
        "_coerce_int",
        "_dict_of_objects",
        "_list_of_objects",
        "_selected_candidate_snapshot",
        "build_review_audit_entry",
        "build_review_row",
        "normalize_review_key_token",
        "promote_plain_row_mapping_keys",
        "promote_plain_skip_row_tokens",
        "review_candidate_matches",
        "review_entry_metadata",
        "review_row_key",
        "review_row_key_from_payload",
        "review_row_lookup_keys",
    } == functions
    assert "_build_review_row" not in functions
    assert "_review_entry_metadata" not in functions
    assert "_normalize_review_key_token" not in functions
    assert "_build_review_audit_entry" not in functions
    assert _line_count(path) <= 240


def test_import_review_compatibility_owns_legacy_row_projection_and_enrichment() -> None:
    path = "server/services/import_review_compatibility.py"
    functions = _function_names(path)

    assert {
        "_as_list",
        "build_compatibility_review_row",
        "enrich_review_items",
    } == functions
    assert _line_count(path) <= 220


def test_import_types_owns_typed_review_row_contract() -> None:
    path = "server/services/import_types.py"
    text = _read(path)

    assert "class ReviewFieldPayload(TypedDict" in text
    assert "class ReviewCandidatePayload(TypedDict" in text
    assert "class ReviewFieldDiffPayload(TypedDict" in text
    assert "class ReviewRowPayload(TypedDict" in text
    assert "class ReviewResolutionPayload(TypedDict" in text
    assert "class ReviewGroupPayload(TypedDict" in text
    assert "class ReviewPagePayload(TypedDict" in text
    assert "ReviewRows: TypeAlias = ReviewRowBuffer | list[ReviewRowPayload]" in text
    assert "ReviewRows: TypeAlias = ReviewRowBuffer | list[dict[str, Any]]" not in text


def test_import_rebuild_handoff_owns_post_commit_rebuild_scheduling() -> None:
    path = "server/services/import_rebuild_handoff.py"
    imports = _imported_modules(path)
    functions = _function_names(path)
    text = _read(path)

    assert "server.services.import_follow_up" in imports
    assert "server.services.import_finalize_service" not in imports
    assert "OnCommitRegistrar" in text
    assert {
        "enqueue_post_import_rebuilds",
        "enqueue_post_import_rebuilds_for_entities",
        "schedule_single_entity_after_commit",
        "schedule_bundle_after_commit",
        "schedule_review_corrections_after_commit",
    }.issubset(functions)
    assert _line_count(path) <= 240


def test_import_job_topology_owns_bundle_inference() -> None:
    path = "server/services/import_job_topology.py"
    text = _read(path)
    functions = _function_names(path)

    assert "class ImportJobTopology" in text
    assert functions == {"job_topology"}
    assert "job_bundle_mode" not in text
    assert "job_topology_side" not in text
    assert "bundle_entities" not in text
    assert _line_count(path) <= 80
