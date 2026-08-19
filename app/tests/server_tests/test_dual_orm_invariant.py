from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

READ_METHODS = {
    "all",
    "aget",
    "annotate",
    "count",
    "distinct",
    "exclude",
    "exists",
    "filter",
    "first",
    "get",
    "last",
    "order_by",
    "prefetch_related",
    "select_for_update",
    "select_related",
    "values",
    "values_list",
}

WRITE_METHODS = {
    "acreate",
    "aupdate",
    "bulk_create",
    "bulk_update",
    "create",
    "delete",
    "get_or_create",
    "update",
    "update_or_create",
}

ALIAS_QUERY_METHODS = {
    "all",
    "annotate",
    "exclude",
    "filter",
    "order_by",
    "prefetch_related",
    "distinct",
    "select_for_update",
    "select_related",
}

READ_ALLOWLIST = {
    "server/api/auth_session_jwt.py",
    "server/api/auth_views.py",
    "server/api/tasks_maintenance.py",
    "server/api/views_import_execute.py",
    "server/api/views_import_review.py",
    "server/services/import_finalize_service.py",
    "server/services/import_admission_service.py",
    "server/services/import_execution_health.py",
    "server/services/import_job_queue.py",
    "server/services/import_runtime_maintenance.py",
    "server/api/views_user_permissions.py",
    "server/services/auth_sessions.py",
    "server/services/hub_manager_access.py",
    "server/api/tasks_import_helpers.py",
    "server/api/tasks_import_failures.py",
    "server/api/ws_auth.py",
    "server/services/import_executor.py",
    "server/services/import_jobs.py",
    "server/services/import_review_db_state.py",
    "server/services/import_review_mutations.py",
    "server/services/import_review_queries.py",
    "server/services/import_phase_attempts.py",
    "server/services/import_review_submit_attempts.py",
    "server/services/import_review_submit_dispatch.py",
    "server/services/import_review_submit_service.py",
    "server/services/import_review_store.py",
    "server/services/local_dev_seed.py",
    "server/services/oidc_auth.py",
    "server/services/permission_elevation.py",
    "server/services/permission_grant_queries.py",
    "server/services/permission_grant_workflow.py",
    "server/services/record_acl.py",
    "server/services/registration_approval.py",
    "server/services/registration_invites.py",
    "server/services/users_helpers.py",
    "server/services/users_mutations.py",
    "server/services/users_queries.py",
    "server/services/session_lifecycle.py",
    "server/services/session_revocation.py",
    "server/services/auth_token_actions.py",
}

WRITE_ALLOWLIST = {
    "server/services/auth_sessions.py",
    "server/services/compliance_jobs.py",
    "server/services/diagnostics_keys.py",
    "server/services/email_sender.py",
    "server/api/tasks_import.py",
    "server/api/tasks_import_failures.py",
    "server/api/tasks_maintenance.py",
    "server/services/import_chunk_workflow.py",
    "server/services/import_executor.py",
    "server/services/import_jobs.py",
    "server/services/import_job_queue.py",
    "server/services/import_review_db_state.py",
    "server/services/import_workflow_leases.py",
    "server/services/import_workflow_manifests.py",
    "server/services/import_workflow_storage.py",
    "server/services/import_review_mutations.py",
    "server/services/import_review_store.py",
    "server/services/local_dev_seed.py",
    "server/services/oidc_auth.py",
    "server/services/permission_elevation.py",
    "server/services/permission_grant_workflow.py",
    "server/services/registration_lifecycle.py",
    "server/services/registration_approval.py",
    "server/services/registration_invites.py",
    "server/services/session_lifecycle.py",
    "server/services/session_revocation.py",
    "server/services/auth_token_actions.py",
    "server/services/user_auth_lifecycle.py",
    "server/services/users_mutations.py",
}


def _iter_runtime_files() -> list[Path]:
    files: list[Path] = []
    for root_name in ("server/api", "server/services"):
        root = REPO_ROOT / root_name
        for path in sorted(root.rglob("*.py")):
            rel = path.relative_to(REPO_ROOT).as_posix()
            if "/migrations/" in rel or "/tests/" in rel:
                continue
            files.append(path)
    return files


def _objects_call_chain(call: ast.Call) -> list[str] | None:
    methods: list[str] = []
    node: ast.Call | None = call

    while node is not None:
        func = node.func
        if not isinstance(func, ast.Attribute):
            return None
        methods.append(func.attr)
        value = func.value
        if isinstance(value, ast.Attribute) and value.attr == "objects":
            return methods
        if isinstance(value, ast.Call):
            node = value
            continue
        return None
    return None


def _alias_call_chain(call: ast.Call, aliases: set[str]) -> list[str] | None:
    methods: list[str] = []
    node: ast.Call | None = call

    while node is not None:
        func = node.func
        if not isinstance(func, ast.Attribute):
            return None
        methods.append(func.attr)
        value = func.value
        if isinstance(value, ast.Name) and value.id in aliases:
            return methods
        if isinstance(value, ast.Call):
            node = value
            continue
        return None
    return None


def _assign_target_names(target: ast.expr) -> set[str]:
    if isinstance(target, ast.Name):
        return {target.id}
    if isinstance(target, (ast.Tuple, ast.List)):
        names: set[str] = set()
        for item in target.elts:
            names.update(_assign_target_names(item))
        return names
    return set()


def _infer_object_aliases(tree: ast.AST) -> set[str]:
    aliases: set[str] = set()
    changed = True
    while changed:
        changed = False
        for node in ast.walk(tree):
            value: ast.expr | None = None
            target_names: set[str] = set()
            if isinstance(node, ast.Assign) and node.targets:
                value = node.value
                for target in node.targets:
                    target_names.update(_assign_target_names(target))
            elif isinstance(node, ast.AnnAssign):
                value = node.value
                target_names.update(_assign_target_names(node.target))
            if value is None or not target_names:
                continue

            derived = False
            if isinstance(value, ast.Name) and value.id in aliases:
                derived = True
            elif isinstance(value, ast.Attribute) and value.attr == "objects":
                derived = True
            elif isinstance(value, ast.Call):
                methods = _objects_call_chain(value) or _alias_call_chain(value, aliases)
                derived = bool(methods and methods[0] in ALIAS_QUERY_METHODS)

            if not derived:
                continue
            before = len(aliases)
            aliases.update(target_names)
            if len(aliases) != before:
                changed = True
    return aliases


def _collect_call_methods(source: str) -> set[str]:
    tree = ast.parse(source)
    aliases = _infer_object_aliases(tree)
    methods: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        chain = _objects_call_chain(node) or _alias_call_chain(node, aliases)
        if not chain:
            continue
        methods.add(chain[0])
    return methods


def test_dual_orm_guardrail_write_methods_cover_create_and_update() -> None:
    assert {"create", "update"}.issubset(WRITE_METHODS)


def test_dual_orm_guardrail_detects_alias_create_and_update_calls() -> None:
    methods = _collect_call_methods("""
mgr = User.objects
mgr.create(username="u")
qs = User.objects.filter(is_active=True)
qs.update(is_active=False)
""")
    assert "create" in methods
    assert "update" in methods


def test_dual_orm_guardrail_objects_methods_are_allowlisted() -> None:
    read_violations: set[str] = set()
    write_violations: set[str] = set()
    unknown_violations: set[str] = set()

    for path in _iter_runtime_files():
        rel = path.relative_to(REPO_ROOT).as_posix()
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=rel)
        aliases = _infer_object_aliases(tree)

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            methods = _objects_call_chain(node) or _alias_call_chain(node, aliases)
            if not methods:
                continue
            outer_method = methods[0]
            if outer_method in READ_METHODS:
                if rel not in READ_ALLOWLIST and rel not in WRITE_ALLOWLIST:
                    read_violations.add(f"{rel}: objects.{outer_method}(...)")
                continue
            if outer_method in WRITE_METHODS:
                if rel not in WRITE_ALLOWLIST:
                    write_violations.add(f"{rel}: objects.{outer_method}(...)")
                continue
            unknown_violations.add(f"{rel}: objects.{outer_method}(...)")

    assert (
        not read_violations
    ), "Dual-ORM invariant violation: ORM read usage outside read allowlist.\n" + "\n".join(
        sorted(read_violations)
    )
    assert (
        not write_violations
    ), "Dual-ORM invariant violation: ORM write usage outside write allowlist.\n" + "\n".join(
        sorted(write_violations)
    )
    assert (
        not unknown_violations
    ), "Dual-ORM invariant violation: unknown .objects method usage.\n" + "\n".join(
        sorted(unknown_violations)
    )
