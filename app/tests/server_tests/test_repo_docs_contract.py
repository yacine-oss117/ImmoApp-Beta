from __future__ import annotations

from pathlib import Path


def _read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def test_repo_docs_describe_current_sync_seams_and_runtime_surfaces() -> None:
    readme = _read("README.md")
    docs_index = _read("docs/README.md")
    codebase = _read("docs/architecture/CODEBASE_MAP.md")
    runtime = _read("docs/architecture/RUNTIME_AND_DATA_FLOWS.md")
    repo_state = _read("docs/reference/REPO_STATE.md")
    matrix = _read("docs/reference/DOMAIN_INTEGRATION_MATRIX.md")

    assert "Contract Seams" in readme
    assert "API_ROUTE_REFERENCE.md" in readme
    assert "SCHEMA_AUTHORITY.md" in readme

    assert "Exact current surfaces" in docs_index
    assert "DOMAIN_INTEGRATION_MATRIX.md" in docs_index

    assert "server/api/route_registry.py" in codebase
    assert "server/api/request_schemas*.py" in codebase
    assert "server/api/response_schemas.py" in codebase
    assert "app/widgets/notification_hub.py" in codebase

    assert "Desktop request path" in runtime
    assert "Desktop realtime notifications path" in runtime
    assert "ImportDecision" in runtime
    assert "ImportReviewGroup" in runtime
    assert "ImportReviewItem" in runtime
    assert "demande" in runtime
    assert "negotiation margin" in runtime

    assert "UI, API, and service sync surface" in repo_state
    assert "route_registry.py" in repo_state
    assert "request_schemas*.py" in repo_state
    assert "response_schemas.py" in repo_state
    assert "/ws/notifications/" in repo_state
    assert "DOMAIN_INTEGRATION_MATRIX.md" in repo_state

    assert "### Matching" in matrix
    assert "test_match_artifact_pipeline_integration.py" in matrix
    assert "test_match_query_cte_postgres_integration.py" in matrix
