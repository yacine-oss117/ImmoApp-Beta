from __future__ import annotations

from pathlib import Path


def _read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def test_importer_docs_contract_mentions_current_importer_truth() -> None:
    architecture = _read("docs/architecture/IMPORTER_ARCHITECTURE.md")
    operations = _read("ops/runbooks/IMPORTER_OPERATIONS.md")
    expensive = _read("docs/guides/OPERATING_EXPENSIVE_WORK.md")
    repo_state = _read("docs/reference/REPO_STATE.md")

    assert "import/<session_id>/cancel/" in architecture
    assert "waiting_for_worker" in architecture
    assert "mapping_palette_mode" in architecture
    assert "recovery_union" in architecture
    assert "ImportReviewGroup" in architecture
    assert "ImportReviewItem" in architecture

    assert "wait_state" in operations
    assert "stalled_reason" in operations
    assert "terminal_reason" in operations
    assert "mapping_palette_mode" in operations

    assert "waiting_for_worker" in expensive
    assert "stalled" in expensive
    assert "mapping_palette_mode" in expensive

    assert "cancel support exists" in repo_state or "cancel route" in repo_state
    assert "pipeline trace fixtures exist" in repo_state
    assert "replay corpus fixtures exist" in repo_state

    checked_docs = "\n".join([architecture, operations, expensive, repo_state])
    assert "reads and writes `ImportJob.review_rows`" not in checked_docs
