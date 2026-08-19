from __future__ import annotations

import uuid

import pytest
from django.contrib.auth import get_user_model
from django.db import connection

from app.tests.server_tests._integration_auth_helpers import (
    admin_conn,
    create_agency,
    create_manager_user,
    ensure_django,
)

ensure_django()

import server.services.import_review_finalize_service as import_review_finalize_module  # noqa: E402
from server.imports.models import (  # noqa: E402
    ImportJob,
    ImportReviewGroup,
    ImportReviewItem,
    ImportRowAudit,
)
from server.pg.schema import ensure_schema  # noqa: E402
from server.services.import_review_store import (  # noqa: E402
    active_review_items,
    apply_group_resolution_templates,
    apply_item_resolutions,
    build_effective_submit_payload,
    finalize_review_submission,
    persist_review_rows,
)


def _make_user_and_agency(prefix: str) -> tuple[int, int, object]:
    conn = admin_conn()
    try:
        agency_id = create_agency(conn, f"{prefix}{uuid.uuid4().hex[:6]}", f"{prefix} Agency")
        user_id = create_manager_user(
            conn,
            agency_id=agency_id,
            username=f"{prefix.lower()}_{uuid.uuid4().hex[:8]}",
            password="StrongTestPass_123!",
        )
        conn.commit()
    finally:
        conn.close()
    user = get_user_model().objects.get(id=user_id)
    return agency_id, user_id, user


def _cleanup_agency(*, agency_id: int, user_id: int) -> None:
    ImportJob.objects.filter(agency_id=agency_id).delete()
    cleanup = admin_conn()
    try:
        cleanup.execute(
            "DELETE FROM token_blacklist_outstandingtoken WHERE user_id = %s",
            (user_id,),
        )
        cleanup.execute("DELETE FROM accounts_user WHERE id = %s", (user_id,))
        cleanup.execute("DELETE FROM accounts_agency WHERE id = %s", (agency_id,))
        cleanup.commit()
    finally:
        cleanup.close()


def _bundle_review_rows() -> list[dict[str, object]]:
    return [
        {
            "row": 2,
            "entity_type": "client",
            "topology_side": "client_side",
            "data": {"family_name": "Yacine", "phone": "0555001001"},
            "original": {"family_name": "Yacine", "phone": "0555001001"},
            "candidate_matches": [
                {
                    "id": 42,
                    "family_name": "Yacine",
                    "phone": "0555001001",
                    "match_confidence": 0.98,
                }
            ],
            "suggested_action": "update_existing",
            "suggested_existing_id": 42,
            "remarks": ["Possible duplicate"],
        },
        {
            "row": 2,
            "entity_type": "demande",
            "topology_side": "client_side",
            "data": {
                "family_name": "Yacine",
                "phone": "0555001001",
                "action": "buy",
                "type": "apartment",
                "locations": "Hydra",
            },
            "original": {
                "family_name": "Yacine",
                "phone": "0555001001",
                "action": "buy",
                "type": "apartment",
                "locations": "Hydra",
            },
            "review_fields": [
                {
                    "field": "client_id",
                    "original": "",
                    "normalized": "",
                    "confidence": 0.0,
                    "remark": "Unable to resolve a same-agency client_id anchor.",
                }
            ],
            "remarks": ["Unable to resolve a same-agency client_id anchor."],
            "suggested_action": "",
        },
    ]


def _make_bundle_review_job() -> tuple[int, int, ImportJob]:
    ensure_schema()
    agency_id, user_id, user = _make_user_and_agency("IMRGS")
    job = ImportJob.objects.create(
        user=user,
        agency_id=agency_id,
        filename="review.csv",
        file_type="csv",
        source_path="fixture://review",
        status=ImportJob.Status.READY,
        stage=ImportJob.Stage.REVIEW,
        detected_entity="client",
        inference_summary={
            "final_inference": {
                "bundle_mode": "same_side_bundle",
                "topology_side_hint": "client_side",
            }
        },
        result_summary={"row_count": 2},
    )
    persist_review_rows(job=job, review_rows=_bundle_review_rows())
    return agency_id, user_id, job


def test_persist_review_rows_allows_root_group_resolution_for_parent_match_children() -> None:
    agency_id, user_id, job = _make_bundle_review_job()
    try:
        group = ImportReviewGroup.objects.get(job=job)
        child_item = ImportReviewItem.objects.get(job=job, entity_type="demande")

        assert group.apply_to_all_allowed is True
        assert group.apply_to_all_count == 2
        assert child_item.group_resolvable is True
        assert list(child_item.group_resolution_blockers or []) == []
    finally:
        _cleanup_agency(agency_id=agency_id, user_id=user_id)


def test_apply_group_resolution_templates_preserves_existing_item_override() -> None:
    agency_id, user_id, job = _make_bundle_review_job()
    try:
        group = ImportReviewGroup.objects.get(job=job)
        root_item = ImportReviewItem.objects.get(job=job, entity_type="client")

        apply_item_resolutions(
            job=job,
            item_decisions={
                str(root_item.id): {
                    "action": "update_existing",
                    "entity_type": "client",
                    "existing_id": 99,
                }
            },
        )
        apply_group_resolution_templates(
            job=job,
            group_decisions={
                group.group_key: {
                    "scope": "apply_to_all_pending_items",
                    "action": "update_existing",
                    "entity_type": "client",
                    "existing_id": 42,
                }
            },
        )

        root_item.refresh_from_db()
        child_item = ImportReviewItem.objects.get(job=job, entity_type="demande")
        assert int((root_item.resolution or {}).get("existing_id", 0) or 0) == 99
        assert str(root_item.resolution_source or "") == "item"
        assert dict(child_item.resolution or {}) == {}
    finally:
        _cleanup_agency(agency_id=agency_id, user_id=user_id)


def test_persist_review_rows_keeps_unchanged_group_and_item_identity() -> None:
    agency_id, user_id, job = _make_bundle_review_job()
    try:
        group_before = ImportReviewGroup.objects.get(job=job)
        items_before = {
            (int(item.row_ordinal or 0), str(item.entity_type or "")): (
                int(item.id),
                item.updated_at,
            )
            for item in ImportReviewItem.objects.filter(job=job)
        }

        persist_review_rows(job=job, review_rows=_bundle_review_rows())

        group_after = ImportReviewGroup.objects.get(job=job)
        items_after = {
            (int(item.row_ordinal or 0), str(item.entity_type or "")): (
                int(item.id),
                item.updated_at,
            )
            for item in ImportReviewItem.objects.filter(job=job)
        }

        assert int(group_after.id) == int(group_before.id)
        assert group_after.updated_at == group_before.updated_at
        assert items_after == items_before
    finally:
        _cleanup_agency(agency_id=agency_id, user_id=user_id)


def test_build_effective_submit_payload_derives_child_create_from_root_group_resolution() -> None:
    agency_id, user_id, job = _make_bundle_review_job()
    try:
        group = ImportReviewGroup.objects.get(job=job)
        apply_group_resolution_templates(
            job=job,
            group_decisions={
                group.group_key: {
                    "scope": "apply_to_all_pending_items",
                    "action": "update_existing",
                    "entity_type": "client",
                    "existing_id": 42,
                }
            },
        )

        _corrections, decisions, skip_rows = build_effective_submit_payload(job)

        assert decisions["2:client"] == {
            "action": "update_existing",
            "entity_type": "client",
            "existing_id": 42,
        }
        assert decisions["2:demande"] == {
            "action": "create_new",
            "entity_type": "demande",
        }
        assert skip_rows == []
    finally:
        _cleanup_agency(agency_id=agency_id, user_id=user_id)


def test_build_effective_submit_payload_includes_item_level_resolutions_in_submit_snapshot() -> (
    None
):
    agency_id, user_id, job = _make_bundle_review_job()
    try:
        root_item = ImportReviewItem.objects.get(job=job, entity_type="client")

        apply_item_resolutions(
            job=job,
            item_decisions={
                str(root_item.id): {
                    "action": "update_existing",
                    "entity_type": "client",
                    "existing_id": 99,
                }
            },
        )

        default_items = active_review_items(job)
        submit_items = active_review_items(job, include_item_resolutions=True)
        _corrections, decisions, skip_rows = build_effective_submit_payload(
            job,
            active_items=submit_items,
        )

        assert all(int(item.id) != int(root_item.id) for item in default_items)
        assert any(int(item.id) == int(root_item.id) for item in submit_items)
        assert decisions["2:client"] == {
            "action": "update_existing",
            "entity_type": "client",
            "existing_id": 99,
        }
        assert skip_rows == []
    finally:
        _cleanup_agency(agency_id=agency_id, user_id=user_id)


def test_same_row_bundle_group_uses_root_entity_type_for_group_resolution() -> None:
    ensure_schema()
    agency_id, user_id, user = _make_user_and_agency("IMRGR")
    job = ImportJob.objects.create(
        user=user,
        agency_id=agency_id,
        filename="same-row-review.csv",
        file_type="csv",
        source_path="fixture://same-row-review",
        status=ImportJob.Status.READY,
        stage=ImportJob.Stage.REVIEW,
        detected_entity="client",
        inference_summary={
            "final_inference": {
                "bundle_mode": "same_side_bundle",
                "topology_side_hint": "client_side",
            }
        },
        result_summary={"row_count": 1},
    )
    try:
        persist_review_rows(
            job=job,
            review_rows=[
                {
                    "row": 1,
                    "entity_type": "demande",
                    "topology_side": "client_side",
                    "data": {
                        "family_name": "Yacine",
                        "phone": "0555001001",
                        "action": "buy",
                        "type": "apartment",
                        "locations": "Hydra",
                    },
                    "original": {
                        "family_name": "Yacine",
                        "phone": "0555001001",
                        "action": "buy",
                        "type": "apartment",
                        "locations": "Hydra",
                    },
                    "review_fields": [
                        {
                            "field": "client_id",
                            "original": "",
                            "normalized": "",
                            "confidence": 0.0,
                            "remark": "Unable to resolve a same-agency client_id anchor.",
                        }
                    ],
                    "remarks": ["Unable to resolve a same-agency client_id anchor."],
                    "issue_group": "parent_match_needed",
                    "suggested_action": "create_new",
                }
            ],
        )
        group = ImportReviewGroup.objects.get(job=job)

        assert group.entity_type == "client"
        assert group.apply_to_all_allowed is True

        apply_group_resolution_templates(
            job=job,
            group_decisions={
                group.group_key: {
                    "scope": "apply_to_all_pending_items",
                    "action": "update_existing",
                    "entity_type": "client",
                    "existing_id": 42,
                }
            },
        )

        _corrections, decisions, skip_rows = build_effective_submit_payload(job)

        assert decisions["1:demande"] == {
            "action": "create_new",
            "entity_type": "demande",
        }
        assert skip_rows == []
    finally:
        _cleanup_agency(agency_id=agency_id, user_id=user_id)


def test_bundle_group_prefers_root_row_metadata_when_child_row_appears_first() -> None:
    ensure_schema()
    agency_id, user_id, user = _make_user_and_agency("IMRGM")
    job = ImportJob.objects.create(
        user=user,
        agency_id=agency_id,
        filename="bundle-root-metadata.csv",
        file_type="csv",
        source_path="fixture://bundle-root-metadata",
        status=ImportJob.Status.READY,
        stage=ImportJob.Stage.REVIEW,
        detected_entity="client",
        inference_summary={
            "final_inference": {
                "bundle_mode": "same_side_bundle",
                "topology_side_hint": "client_side",
            }
        },
        result_summary={"row_count": 2},
    )
    try:
        persist_review_rows(
            job=job,
            review_rows=[
                {
                    "row": 1,
                    "entity_type": "demande",
                    "topology_side": "client_side",
                    "data": {
                        "family_name": "Yacine",
                        "phone": "0555001001",
                        "action": "buy",
                        "type": "apartment",
                    },
                    "original": {
                        "family_name": "Yacine",
                        "phone": "0555001001",
                        "action": "buy",
                        "type": "apartment",
                    },
                    "root_identity_snapshot": {
                        "family_name": "Yacine",
                        "phone": "0555001001",
                    },
                    "issue_group": "parent_match_needed",
                    "issue_title": "Parent match needed",
                    "issue_summary": "Needs a client match.",
                },
                {
                    "row": 2,
                    "entity_type": "client",
                    "topology_side": "client_side",
                    "data": {"family_name": "Yacine", "phone": "0555001001"},
                    "original": {"family_name": "Yacine", "phone": "0555001001"},
                    "root_identity_snapshot": {
                        "family_name": "Yacine",
                        "phone": "0555001001",
                    },
                    "candidate_matches": [
                        {
                            "id": 42,
                            "family_name": "Yacine",
                            "phone": "0555001001",
                            "match_confidence": 0.98,
                        }
                    ],
                    "suggested_action": "update_existing",
                    "suggested_existing_id": 42,
                    "issue_group": "possible_duplicate",
                    "issue_title": "Possible duplicate",
                    "issue_summary": "Looks very close to an existing client.",
                },
            ],
        )
        group = ImportReviewGroup.objects.get(job=job)

        assert group.entity_type == "client"
        assert group.root_row_ordinal == 2
        assert group.root_label == "Yacine"
    finally:
        _cleanup_agency(agency_id=agency_id, user_id=user_id)


def test_group_default_review_decision_clears_prior_group_applied_resolution() -> None:
    agency_id, user_id, job = _make_bundle_review_job()
    try:
        group = ImportReviewGroup.objects.get(job=job)

        apply_group_resolution_templates(
            job=job,
            group_decisions={
                group.group_key: {
                    "scope": "apply_to_all_pending_items",
                    "action": "update_existing",
                    "entity_type": "client",
                    "existing_id": 42,
                }
            },
        )
        _corrections, first_decisions, _skip_rows = build_effective_submit_payload(job)
        assert first_decisions["2:client"]["action"] == "update_existing"

        apply_group_resolution_templates(
            job=job,
            group_decisions={
                group.group_key: {
                    "scope": "group_default",
                    "action": "review_ambiguous",
                    "entity_type": "client",
                }
            },
        )

        _corrections, decisions, skip_rows = build_effective_submit_payload(job)

        assert decisions["2:client"] == {
            "action": "review_ambiguous",
            "entity_type": "client",
        }
        assert decisions["2:demande"] == {
            "action": "review_ambiguous",
            "entity_type": "demande",
        }
        assert skip_rows == []
    finally:
        _cleanup_agency(agency_id=agency_id, user_id=user_id)


def test_finalize_review_submission_bounds_review_history_window() -> None:
    agency_id, user_id, job = _make_bundle_review_job()
    try:
        job.result_summary = {
            "row_count": 2,
            "review_history": [{"action": f"old-{index}"} for index in range(30)],
            "review_history_count": 30,
        }
        job.save(update_fields=["result_summary", "updated_at"])

        completion = finalize_review_submission(
            job=job,
            actor_user_id=user_id,
            review_result={
                "created_count": 0,
                "updated_count": 0,
                "still_review": [],
                "errors": [],
                "audit_entries": [
                    {"action": "new-1"},
                    {"action": "new-2"},
                ],
            },
        )
        job.refresh_from_db()

        review_history = list((job.result_summary or {}).get("review_history", []) or [])
        assert int((job.result_summary or {}).get("review_history_count", 0) or 0) == 32
        assert len(review_history) == 25
        assert review_history[0]["action"] == "old-7"
        assert review_history[-2]["action"] == "new-1"
        assert review_history[-1]["action"] == "new-2"
        assert ImportRowAudit.objects.filter(job=job).count() == 2
        assert int(completion.summary.get("review_history_count", 0) or 0) == 32
    finally:
        _cleanup_agency(agency_id=agency_id, user_id=user_id)


def test_finalize_review_submission_rolls_back_when_audit_persistence_fails(
    monkeypatch,
) -> None:
    agency_id, user_id, job = _make_bundle_review_job()
    try:
        monkeypatch.setattr(
            import_review_finalize_module,
            "record_row_audits",
            lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("audit boom")),
        )

        with pytest.raises(RuntimeError, match="audit boom"):
            finalize_review_submission(
                job=job,
                actor_user_id=user_id,
                review_result={
                    "created_count": 0,
                    "updated_count": 0,
                    "still_review": _bundle_review_rows(),
                    "errors": [],
                    "audit_entries": [{"row": 2, "entity_type": "client", "action": "review"}],
                },
            )

        job.refresh_from_db()
        assert ImportReviewGroup.objects.filter(job=job).count() == 1
        assert ImportReviewItem.objects.filter(job=job).count() == 2
        assert ImportRowAudit.objects.filter(job=job).count() == 0
        assert dict(job.result_summary or {}) == {"row_count": 2}
    finally:
        _cleanup_agency(agency_id=agency_id, user_id=user_id)


def test_finalize_review_submission_keeps_audits_inside_transaction_and_pages_after_commit(
    monkeypatch,
) -> None:
    agency_id, user_id, job = _make_bundle_review_job()
    try:
        call_states: list[tuple[str, bool]] = []

        def _record_row_audits(**_kwargs):
            call_states.append(("audit", connection.in_atomic_block))

        def _paged_review_groups(**_kwargs):
            call_states.append(("groups", connection.in_atomic_block))
            return ([{"group_key": "client:phone:0555001001"}], {"page": 1})

        def _paged_review_items(**_kwargs):
            call_states.append(("items", connection.in_atomic_block))
            return (
                [
                    {
                        "item_id": 1,
                        "group_key": "client:phone:0555001001",
                        "row": 2,
                        "entity_type": "client",
                        "normalized_data": {"family_name": "Yacine", "phone": "0555001001"},
                        "raw_data": {"family_name": "Yacine", "phone": "0555001001"},
                    }
                ],
                {"page": 1},
            )

        def _enrich_review_items(*, job, review_items):
            _ = job
            call_states.append(("enrich", connection.in_atomic_block))
            return list(review_items), [{"row": 2, "group_key": "client:phone:0555001001"}]

        monkeypatch.setattr(import_review_finalize_module, "record_row_audits", _record_row_audits)
        monkeypatch.setattr(
            import_review_finalize_module,
            "paged_review_groups",
            _paged_review_groups,
        )
        monkeypatch.setattr(
            import_review_finalize_module,
            "paged_review_items",
            _paged_review_items,
        )
        monkeypatch.setattr(
            import_review_finalize_module,
            "enrich_review_items",
            _enrich_review_items,
        )

        completion = finalize_review_submission(
            job=job,
            actor_user_id=user_id,
            review_result={
                "created_count": 0,
                "updated_count": 0,
                "still_review": _bundle_review_rows(),
                "errors": [],
                "audit_entries": [{"row": 2, "entity_type": "client", "action": "review"}],
            },
        )

        assert call_states == [
            ("audit", True),
            ("groups", False),
            ("items", False),
            ("enrich", False),
        ]
        assert completion.review_pending_group_count == 1
        assert completion.still_review_count == 2
        assert completion.review_groups[0]["group_key"] == "client:phone:0555001001"
        assert completion.review_items[0]["group_key"] == "client:phone:0555001001"
    finally:
        _cleanup_agency(agency_id=agency_id, user_id=user_id)


def test_finalize_review_submission_rolls_back_partial_review_state_on_save_failure(
    monkeypatch,
) -> None:
    ensure_schema()
    agency_id, user_id, user = _make_user_and_agency("IMRAT")
    original_save = ImportJob.save
    job = ImportJob.objects.create(
        user=user,
        agency_id=agency_id,
        filename="atomic-review.csv",
        file_type="csv",
        source_path="fixture://atomic-review",
        status=ImportJob.Status.READY,
        stage=ImportJob.Stage.REVIEW,
        detected_entity="client",
        inference_summary={
            "final_inference": {
                "bundle_mode": "same_side_bundle",
                "topology_side_hint": "client_side",
            }
        },
        result_summary={"row_count": 2},
    )
    try:

        def _failing_save(self, *args, **kwargs):
            _ = (args, kwargs)
            raise RuntimeError("boom")

        monkeypatch.setattr(ImportJob, "save", _failing_save)

        with pytest.raises(RuntimeError, match="boom"):
            finalize_review_submission(
                job=job,
                actor_user_id=user_id,
                review_result={
                    "created_count": 0,
                    "updated_count": 0,
                    "still_review": _bundle_review_rows(),
                    "errors": [],
                    "audit_entries": [],
                },
            )

        monkeypatch.setattr(ImportJob, "save", original_save)
        job.refresh_from_db()

        assert ImportReviewGroup.objects.filter(job=job).count() == 0
        assert ImportReviewItem.objects.filter(job=job).count() == 0
        assert job.review_rows == []
        assert dict(job.result_summary or {}) == {"row_count": 2}
    finally:
        monkeypatch.setattr(ImportJob, "save", original_save)
        _cleanup_agency(agency_id=agency_id, user_id=user_id)
