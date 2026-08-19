from __future__ import annotations

from pathlib import Path

_EXPECTED_FILES = (
    "app/tests/server_tests/test_import_asymmetric_entities_integration.py",
    "app/tests/server_tests/test_import_parser_messy_files.py",
    "app/tests/server_tests/test_import_large_messy_integration.py",
    "app/tests/server_tests/test_import_pipeline.py",
    "app/tests/server_tests/test_match_artifact_pipeline_integration.py",
    "app/tests/server_tests/test_match_query_cte_postgres_integration.py",
    "app/tests/server_tests/test_matches_all_async_contract_ast.py",
    "app/tests/server_tests/test_matches_count_contract_ast.py",
    "app/tests/server_tests/test_storage_lifecycle_integration.py",
    "app/tests/server_tests/test_storage_and_matching_constraints.py",
    "app/tests/server_tests/test_storage_quota_atomic_ast.py",
    "app/tests/server_tests/test_agency_media_contract.py",
    "app/tests/server_tests/test_crm_contract_lifecycle_integration.py",
    "app/tests/server_tests/test_row_version_cas_runtime.py",
    "app/tests/server_tests/test_row_version_required_ast.py",
    "app/tests/server_tests/test_api_cross_tenant_breach.py",
    "app/tests/server_tests/test_rls_breach_matrix.py",
    "app/tests/server_tests/test_auth_event_logging.py",
)

_RUNTIME_DOMAIN_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "Importer": (
        "app/tests/server_tests/test_import_asymmetric_entities_integration.py",
        "app/tests/server_tests/test_import_parser_messy_files.py",
        "app/tests/server_tests/test_import_large_messy_integration.py",
    ),
    "Matching": (
        "app/tests/server_tests/test_match_artifact_pipeline_integration.py",
        "app/tests/server_tests/test_match_query_cte_postgres_integration.py",
    ),
    "Storage": (
        "app/tests/server_tests/test_storage_lifecycle_integration.py",
        "app/tests/server_tests/test_agency_media_contract.py",
    ),
    "CRM Lifecycle": (
        "app/tests/server_tests/test_crm_contract_lifecycle_integration.py",
        "app/tests/server_tests/test_row_version_cas_runtime.py",
    ),
    "Security/RLS/Auth": (
        "app/tests/server_tests/test_rls_breach_matrix.py",
        "app/tests/server_tests/test_api_cross_tenant_breach.py",
        "app/tests/server_tests/test_auth_event_logging.py",
    ),
}


def main() -> None:
    matrix = Path("docs/reference/DOMAIN_INTEGRATION_MATRIX.md")
    if not matrix.exists():
        raise SystemExit(
            "verify_domain_integration_matrix: missing docs/reference/DOMAIN_INTEGRATION_MATRIX.md"
        )
    missing = [path for path in _EXPECTED_FILES if not Path(path).exists()]
    if missing:
        raise SystemExit(
            "verify_domain_integration_matrix: missing critical integration tests: "
            + ", ".join(missing)
        )
    text = matrix.read_text(encoding="utf-8")
    for path in _EXPECTED_FILES:
        if path not in text:
            raise SystemExit(
                "verify_domain_integration_matrix: matrix missing test path entry: " + path
            )
    for domain, paths in _RUNTIME_DOMAIN_REQUIREMENTS.items():
        if f"### {domain}" not in text:
            raise SystemExit(
                f"verify_domain_integration_matrix: missing domain heading in matrix: {domain}"
            )
        listed = [path for path in paths if path in text]
        if not listed:
            raise SystemExit(
                "verify_domain_integration_matrix: runtime long-path coverage missing for domain: "
                + domain
            )
    print("verify_domain_integration_matrix: OK")


if __name__ == "__main__":
    main()
