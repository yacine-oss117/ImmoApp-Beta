from __future__ import annotations

from pathlib import Path


def test_matches_all_endpoints_are_admin_async_with_backpressure_and_coalescing() -> None:
    text = Path("server/api/views_matches.py").read_text(encoding="utf-8")
    assert '@route("matches/clients/all/"' in text
    assert '@route("matches/demandes/all/"' in text
    assert '@route("matches/listings/all/"' in text
    assert '@route("matches/offers/all/"' in text
    assert '@api_view(["POST"])' in text
    assert "_coalesced_or_backpressured_task" in text
    assert "match_all_scheduler.schedule_tenant_fair_task" in text
    assert 'queue="rebuild_batch"' in text
    assert "status.HTTP_202_ACCEPTED" in text
    assert "status.HTTP_429_TOO_MANY_REQUESTS" in text
    assert "is_superuser(request)" in text
    assert "admission_mode" in text
    assert "MatchAllTargetAgencySerializer" in text
    assert "build_request_async_task_identity" in text
    assert "int(agency or 0)" not in text
