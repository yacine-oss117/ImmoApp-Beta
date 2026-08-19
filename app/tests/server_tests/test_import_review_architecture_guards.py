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


def _class_names(path: str) -> set[str]:
    return {node.name for node in _module(path).body if isinstance(node, ast.ClassDef)}


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


def _cross_module_private_review_imports(path: str) -> dict[str, set[str]]:
    private_imports: dict[str, set[str]] = {}
    for node in ast.walk(_module(path)):
        if not isinstance(node, ast.ImportFrom) or not node.module:
            continue
        if not node.module.startswith("server.services.import_review_"):
            continue
        names = {alias.name for alias in node.names if alias.name.startswith("_")}
        if names:
            private_imports[node.module] = names
    return private_imports


def _line_count(path: str) -> int:
    return len(_read(path).splitlines())


def test_step_review_stays_split_by_ui_ownership() -> None:
    path = "app/views/imports/step_review.py"
    imports = _imported_modules(path)

    assert "app.views.imports.review_row_card" in imports
    assert "app.views.imports.review_api_adapter" in imports
    assert "app.views.imports.review_actions" in imports
    assert "app.views.imports.review_page_controller" in imports
    assert "_ReviewRowCard" not in _class_names(path)
    assert _line_count(path) <= 1150


def test_views_import_review_stays_thin() -> None:
    path = "server/api/views_import_review.py"
    text = _read(path)
    compatibility_imports = _imported_names_from(
        path, "server.services.import_review_compatibility"
    )
    execution_imports = _imported_names_from(
        path, "server.services.import_review_execution_service"
    )
    payload_imports = _imported_names_from(path, "server.services.import_review_payloads")
    service_imports = _imported_names_from(path, "server.services.import_service")

    assert "server.services.import_review_payloads" in _imported_modules(path)
    assert payload_imports == {
        "allowed_review_entity_types",
        "build_import_review_response",
        "build_review_capacity_exceeded_response",
        "build_review_duplicate_conflict_response",
        "normalize_review_submit_request",
        "query_bool_param",
        "query_int_param",
    }
    assert compatibility_imports == {"enrich_review_items"}
    assert execution_imports == {"ImportReviewSubmitConflictError"}
    assert service_imports == {"ImportPermissionError", "ImportService", "get_active_schema"}
    assert "def _allowed_review_entity_types(" not in text
    assert "def _query_int(" not in text
    assert "def _query_bool(" not in text
    assert "def _normalize_submit_action(" not in text
    assert "def _as_dict(" not in text
    assert "def _as_list(" not in text
    assert "def _normalize_review_token(" not in text
    assert "def _review_row_key_from_payload(" not in text
    assert "def _promote_plain_row_keys(" not in text
    assert "def _promote_plain_skip_rows(" not in text
    assert "def _validate_decision_entity_types(" not in text
    assert "def _row_decision_payload(" not in text
    assert "def _enrich_review_items(" not in text
    assert "apply_review_resolutions(" not in text
    assert "finalize_review_submission(" not in text
    assert _line_count(path) <= 350


def test_import_review_store_stays_facade() -> None:
    path = "server/services/import_review_store.py"
    imports = _imported_modules(path)
    functions = _function_names(path)

    assert "server.services.import_review_db_state" in imports
    assert "server.services.import_review_queries" in imports
    assert "server.services.import_review_mutations" in imports
    assert "server.services.import_review_payloads" not in imports
    assert "persist_review_rows" not in functions
    assert "paged_review_groups" not in functions
    assert "paged_review_items" not in functions
    assert "apply_item_resolutions" not in functions
    assert "build_compatibility_review_row" not in functions
    assert _line_count(path) <= 320


def test_import_review_db_state_owns_db_persistence_and_backfill() -> None:
    path = "server/services/import_review_db_state.py"
    imports = _imported_modules(path)
    functions = _function_names(path)
    text = _read(path)

    assert "server.services.import_review_grouping" in imports
    assert "server.services.import_review_queries" in imports
    assert {
        "backfill_legacy_review_state",
        "clear_db_review_state",
        "ensure_review_state",
        "persist_review_rows",
        "persist_review_state_with_compatibility_sample",
    }.issubset(functions)
    assert "apply_item_resolutions" not in functions
    assert "build_effective_submit_payload" not in functions
    assert "review_row_key(" not in text
    assert _line_count(path) <= 700


def test_review_cluster_avoids_cross_module_private_imports() -> None:
    paths = [
        "server/api/views_import_review.py",
        "server/services/import_review_compatibility.py",
        "server/services/import_review_db_state.py",
        "server/services/import_review_submit_dispatch.py",
        "server/services/import_review_execution_service.py",
        "server/services/import_review_mutations.py",
        "server/services/import_review_payloads.py",
        "server/services/import_review_queries.py",
        "server/services/import_review_resolution.py",
        "server/services/import_review_store.py",
    ]

    offenders = {
        path: _cross_module_private_review_imports(path)
        for path in paths
        if _cross_module_private_review_imports(path)
    }

    assert offenders == {}


def test_import_review_execution_service_stays_facade() -> None:
    path = "server/services/import_review_execution_service.py"
    imports = _imported_modules(path)
    functions = _function_names(path)
    conflict_imports = _imported_names_from(path, "server.services.import_review_conflicts")
    text = _read(path)

    assert "server.services.import_review_resolution" in imports
    assert "server.services.import_review_conflicts" in imports
    assert conflict_imports == {"detect_create_conflicts"}
    assert "apply_review_resolutions" in functions
    assert "insert_review_corrections" in functions
    assert "submit_review" in functions
    assert "_detect_create_conflicts" not in text
    assert "_find_existing_phone_match" not in functions
    assert "_existing_summary" not in functions
    assert "_build_review_audit_entry" not in functions
    assert "review_row_key" not in text
    assert "review_row_lookup_keys" not in text
    assert _line_count(path) <= 320


def test_import_review_submit_service_owns_async_submit_orchestration() -> None:
    path = "server/services/import_review_submit_service.py"
    imports = _imported_modules(path)
    functions = _function_names(path)
    classes = _class_names(path)
    text = _read(path)

    assert "kickoff_review_submission" in functions
    assert "run_review_submit_task" in functions
    assert "ImportReviewSubmitConflictError" in classes
    assert "server.services.import_review_submit_dispatch" in imports
    assert "server.services.import_review_finalize_service" in imports
    assert "server.services.import_review_payloads" in imports
    assert "server.services.import_review_store" in imports
    assert "build_review_submit_success_response" not in text
    assert "transaction.on_commit(" in text
    assert "logger.exception(" in text
    assert "run_review_submit_terminal_section" in text
    assert "run_with_review_submit_attempt_fence" in text
    assert "assert_review_submit_attempt_current" in text
    assert "apply_review_resolutions(" in text
    assert "finalize_review_submission(" in text
    assert "clear_review_submit_workflow" not in text
    assert "mark_review_submit_dispatch_terminal" not in text
    assert _line_count(path) <= 660


def test_import_review_submit_dispatch_owns_workflow_backed_dispatch_state() -> None:
    path = "server/services/import_review_submit_dispatch.py"
    imports = _imported_modules(path)
    functions = _function_names(path)
    text = _read(path)

    assert "server.services.import_workflow_storage" in imports
    assert "server.services.import_review_submit_attempts" in imports
    assert "server.services.import_review_submit_service" not in imports
    assert {
        "begin_review_submit_dispatch",
        "claim_review_submit_dispatch_start",
        "finish_review_submit_dispatch_fresh",
        "generate_review_submit_task_id",
        "load_review_submit_workflow",
        "mark_review_submit_dispatch_publish_failed_fresh",
        "mark_review_submit_dispatch_published_fresh",
        "persist_review_submit_workflow",
        "publish_review_submit_dispatch",
        "review_submit_dispatch_payload",
    }.issubset(functions)
    assert "clear_review_submit_workflow" not in functions
    assert "mark_review_submit_dispatch_terminal" not in functions
    assert "mark_review_submit_dispatch_published" not in functions
    assert "mark_review_submit_dispatch_publish_failed" not in functions
    assert "_mark_review_submit_dispatch_published" in functions
    assert "_mark_review_submit_dispatch_publish_failed" in functions
    assert '"clear_review_submit_workflow"' not in text
    assert '"mark_review_submit_dispatch_terminal"' not in text
    assert '"mark_review_submit_dispatch_published"' not in text
    assert '"mark_review_submit_dispatch_publish_failed"' not in text
    assert "select_for_update()" in text
    assert "begin_review_submit_attempt(" in text
    assert "claim_review_submit_attempt_started(" in text
    assert "finish_review_submit_attempt_fresh(" in text
    assert "mark_review_submit_dispatch_published_fresh(job, task_id=task_id)" in text
    assert "mark_review_submit_dispatch_publish_failed_fresh(job, task_id=task_id)" in text
    assert "kickoff_review_submission" not in text
    assert "run_review_submit_task" not in text
    assert _line_count(path) <= 430


def test_task_attempt_lifecycle_core_stays_domain_neutral() -> None:
    path = "server/services/task_attempt_lifecycle.py"
    imports = _imported_modules(path)
    functions = _function_names(path)
    text = _read(path)

    assert Path(path).exists()
    assert {
        "cancel_payload",
        "claim_started_payload",
        "finish_payload",
        "heartbeat_payload",
        "is_attempt_current",
        "new_attempt_payload",
    }.issubset(functions)
    forbidden_tokens = {
        "ImportJob",
        "ImportChunkPhase",
        "workflow_payload",
        "save_workflow_payload",
        "import_review_submit",
        "import_distributed",
        "tasks_import",
        "celery",
        "match_cache",
    }
    assert imports.isdisjoint(
        {
            "django.db",
            "django.utils",
            "server.imports.models",
            "server.services.import_workflow_storage",
            "server.services.import_review_submit_dispatch",
            "server.services.import_phase_attempts",
            "server.services.import_distributed_execution",
        }
    )
    assert not any(token in text for token in forbidden_tokens)
    assert _line_count(path) <= 280


def test_review_submit_attempt_adapter_owns_workflow_persistence() -> None:
    path = "server/services/import_review_submit_attempts.py"
    imports = _imported_modules(path)
    functions = _function_names(path)
    text = _read(path)

    assert "server.services.task_attempt_lifecycle" in imports
    assert "server.imports.models" in imports
    assert "server.services.import_workflow_storage" in imports
    assert "ImportChunkPhase" not in text
    assert "apply_review_resolutions" not in text
    assert "finalize_review_submission" not in text
    assert {
        "begin_review_submit_attempt",
        "claim_review_submit_attempt_started",
        "finish_review_submit_attempt_fresh",
        "request_review_submit_attempt_cancel",
        "review_submit_attempt_payload",
        "run_review_submit_terminal_section",
        "run_with_review_submit_attempt_fence",
    }.issubset(functions)
    assert "select_for_update()" in text
    assert _line_count(path) <= 520


def test_phase_attempt_adapter_owns_phase_lease_persistence() -> None:
    path = "server/services/import_phase_attempts.py"
    imports = _imported_modules(path)
    functions = _function_names(path)
    text = _read(path)

    assert "server.services.task_attempt_lifecycle" in imports
    assert "server.imports.models" in imports
    assert "server.services.import_workflow_leases" in imports
    assert "review_submit" not in text
    assert {
        "cancel_phase_attempt",
        "claim_phase_attempt_started",
        "complete_phase_attempt",
        "fail_phase_attempt",
        "is_phase_attempt_current",
        "raise_phase_attempt_cancelled",
        "run_with_phase_attempt_fence",
    }.issubset(functions)
    assert "select_for_update()" in text
    assert _line_count(path) <= 280


def test_import_task_attempts_mixed_owner_stays_deleted() -> None:
    assert not Path("server/services/import_task_attempts.py").exists()


def test_review_submit_attempt_contract_tests_stay_focused() -> None:
    concierge_path = "app/tests/server_tests/test_import_concierge_contract.py"
    attempt_path = "app/tests/server_tests/test_import_review_submit_attempts_contract.py"
    concierge_text = _read(concierge_path)
    attempt_text = _read(attempt_path)
    moved_tests = {
        "test_review_submit_publish_success_preserves_started_dispatch_state",
        "test_review_submit_publish_success_preserves_completed_dispatch_state",
        "test_review_submit_publish_failure_preserves_started_or_terminal_dispatch_state",
        "test_finish_review_submit_dispatch_fresh_preserves_publish_metadata",
        "test_finish_review_submit_dispatch_fresh_keeps_terminal_status_monotonic",
        "test_cancelled_review_submit_attempt_cannot_apply_late_worker_success",
        "test_review_submit_cancellation_after_apply_begins_cannot_preempt_terminal_finish",
        "test_import_review_submit_logs_unexpected_background_failure_and_masks_user_payload",
    }

    assert Path(attempt_path).exists()
    assert _line_count(concierge_path) <= 2150
    assert _line_count(attempt_path) <= 900
    assert all(name not in concierge_text for name in moved_tests)
    assert all(name in attempt_text for name in moved_tests)


def test_started_review_submit_dispatch_is_health_and_repair_tracked() -> None:
    health_text = _read("server/services/import_execution_health.py")
    maintenance_text = _read("server/api/tasks_maintenance.py")

    assert "REVIEW_SUBMIT_DISPATCH_STARTED" in health_text
    assert 'wait_reason = "worker_running"' in health_text
    assert 'stalled_reason = "review_submit_worker_stalled"' in health_text
    assert '"review_submit_worker_stalled"' in maintenance_text
    assert "watchdog_cancel" in maintenance_text
    assert "request_review_submit_attempt_cancel(" in maintenance_text
    assert "persist_review_submit_ready_state(" in maintenance_text
    assert "review_submit_generic_error_payload()" in maintenance_text
    assert "finish_review_submit_dispatch_fresh" not in maintenance_text
    branch_start = maintenance_text.index('stalled_reason == "review_submit_worker_stalled"')
    branch_end = maintenance_text.index("continue", branch_start)
    branch_text = maintenance_text[branch_start:branch_end]
    assert "publish_review_submit_dispatch(" not in branch_text
    assert "release_execution_slot(" not in branch_text
    assert "request_review_submit_attempt_cancel(" in branch_text
    assert "_note_repair(" in branch_text
    assert "publish_review_submit_dispatch(" in maintenance_text


def test_tasks_import_review_stays_thin() -> None:
    path = "server/api/tasks_import_review.py"
    imports = _imported_modules(path)
    functions = _function_names(path)
    task_core_imports = _imported_names_from(path, "tasks_core")
    text = _read(path)

    assert "import_review_submit_task" in functions
    assert imports >= {
        "server.services.import_review_submit_service",
        "tasks_core",
        "tasks_import_helpers",
    }
    assert task_core_imports == {"require_agency_id", "task_context", "task_decorator"}
    assert 'require_agency_id(agency_id, "import_review_submit_task")' in text
    assert 'task_id=str(getattr(getattr(_task, "request", None), "id", "") or "")' in text
    assert "int(agency_id or 0)" not in text
    assert _line_count(path) <= 120


def test_import_review_compatibility_owns_explicit_compatibility_adapter() -> None:
    path = "server/services/import_review_compatibility.py"
    functions = _function_names(path)
    text = _read(path)

    assert {"_as_list", "build_compatibility_review_row", "enrich_review_items"} == functions
    assert "build_review_capacity_exceeded_response" not in text
    assert "normalize_review_submit_request" not in text
    assert _line_count(path) <= 220


def test_import_review_payloads_keep_typed_payload_shaping_without_compatibility_blob() -> None:
    path = "server/services/import_review_payloads.py"
    text = _read(path)
    functions = _function_names(path)
    shape_imports = _imported_names_from(path, "server.services.import_review_shapes")

    assert shape_imports == {
        "normalize_review_key_token",
        "promote_plain_row_mapping_keys",
        "promote_plain_skip_row_tokens",
        "review_row_key_from_payload",
    }
    assert {
        "allowed_review_entity_types",
        "effective_resolution_payload",
        "build_import_review_response",
        "build_review_capacity_exceeded_response",
        "build_review_duplicate_conflict_response",
        "build_review_submit_success_response",
        "merge_review_submit_payloads",
        "normalize_review_submit_request",
        "prepare_effective_review_submit_payload",
        "query_bool_param",
        "query_int_param",
    }.issubset(functions)
    assert "build_compatibility_review_row" not in functions
    assert "enrich_review_items" not in functions
    assert "_serialize_compatibility_sample" not in functions
    assert "def _normalize_review_token(" not in text
    assert "def _review_row_key_from_payload(" not in text
    assert "def _promote_plain_row_keys(" not in text
    assert "def _promote_plain_skip_rows(" not in text
    assert "def legacy_review_row(" not in text


def test_import_review_queries_use_public_review_owner_apis_and_typed_payloads() -> None:
    path = "server/services/import_review_queries.py"
    text = _read(path)
    compatibility_imports = _imported_names_from(
        path, "server.services.import_review_compatibility"
    )
    payload_imports = _imported_names_from(path, "server.services.import_review_payloads")
    shape_imports = _imported_names_from(path, "server.services.import_review_shapes")

    assert compatibility_imports == {"build_compatibility_review_row"}
    assert payload_imports == {"effective_resolution_payload"}
    assert shape_imports == {"review_row_lookup_keys"}
    assert "ReviewGroupPayload" in text
    assert "ReviewPagePayload" in text
    assert "ReviewRowPayload" in text
    assert "list[dict[str, Any]]" not in text
    assert "tuple[list[dict[str, Any]], dict[str, Any]]" not in text


def test_import_review_mutations_use_canonical_row_key_owner_without_any_callback() -> None:
    path = "server/services/import_review_mutations.py"
    imports = _imported_modules(path)
    functions = _function_names(path)
    text = _read(path)
    shape_imports = _imported_names_from(path, "server.services.import_review_shapes")
    compatibility_imports = _imported_names_from(
        path, "server.services.import_review_compatibility"
    )

    assert "server.services.import_review_db_state" not in imports
    assert "server.services.import_review_queries" not in imports
    assert {
        "apply_group_resolution_templates",
        "apply_item_resolutions",
        "build_effective_submit_payload",
    }.issubset(functions)
    assert shape_imports == {"review_row_key"}
    assert compatibility_imports == set()
    assert "persist_review_rows" not in functions
    assert "ensure_review_state" not in functions
    assert "finalize_review_submission(" not in text
    assert "ReviewSubmitCompletion" not in text
    assert "review_row_key_fn: Any" not in text
    assert "review_row_key_fn=" not in text
    assert _line_count(path) <= 320
