# Domain Integration Matrix

## Goal

Keep at least one real runtime long-path test for each backend critical domain.
This file is intentionally small and is validated by
`scripts/verify_domain_integration_matrix.py`.

### Importer

Runtime long-path:

- `app/tests/server_tests/test_import_asymmetric_entities_integration.py`
- `app/tests/server_tests/test_import_parser_messy_files.py`
- `app/tests/server_tests/test_import_large_messy_integration.py`

Policy/static:

- `app/tests/server_tests/test_import_pipeline.py`

### Matching

Runtime long-path:

- `app/tests/server_tests/test_match_artifact_pipeline_integration.py`
- `app/tests/server_tests/test_match_query_cte_postgres_integration.py`

Policy/static:

- `app/tests/server_tests/test_matches_all_async_contract_ast.py`
- `app/tests/server_tests/test_matches_count_contract_ast.py`

### Storage

Runtime long-path:

- `app/tests/server_tests/test_storage_lifecycle_integration.py`
- `app/tests/server_tests/test_agency_media_contract.py`

Policy/static:

- `app/tests/server_tests/test_storage_and_matching_constraints.py`
- `app/tests/server_tests/test_storage_quota_atomic_ast.py`

### CRM Lifecycle

Runtime long-path:

- `app/tests/server_tests/test_crm_contract_lifecycle_integration.py`
- `app/tests/server_tests/test_row_version_cas_runtime.py`

Policy/static:

- `app/tests/server_tests/test_row_version_required_ast.py`

### Security/RLS/Auth

Runtime long-path:

- `app/tests/server_tests/test_rls_breach_matrix.py`
- `app/tests/server_tests/test_api_cross_tenant_breach.py`
- `app/tests/server_tests/test_auth_event_logging.py`

## Release rule

- any missing matrix file is a release blocker
- each domain must retain at least one runtime long-path test
- static-only coverage is not enough for these domains
