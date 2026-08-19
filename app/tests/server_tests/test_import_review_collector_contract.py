from __future__ import annotations

from pathlib import Path

import pytest

from server.services.import_review_collector import ImportReviewCollector


def test_cleanup_preserves_metrics_and_releases_spool_resources(tmp_path: Path) -> None:
    del tmp_path
    collector = ImportReviewCollector(max_items_emergency=5, diagnostic_limit=2)
    collector.append({"row": 1, "entity_type": "client", "remarks": "first"})
    collector.append({"row": 2, "entity_type": "client", "remarks": "second"})
    collector.remember_artifact_manifest_id(91)
    spool_path = collector.spool_path

    collector.cleanup()

    assert len(collector) == 2
    assert collector.item_count() == 2
    assert bool(collector) is True
    assert collector.emergency_overflowed() is False
    assert collector.emergency_overflow_count() == 0
    assert collector.diagnostic_sample() == [
        {"row": 1, "entity_type": "client", "remarks": "first"},
        {"row": 2, "entity_type": "client", "remarks": "second"},
    ]
    assert collector.artifact_manifest_ids() == [91]
    assert spool_path.exists() is False


def test_cleanup_is_idempotent() -> None:
    collector = ImportReviewCollector(max_items_emergency=2)
    collector.append({"row": 1})

    collector.cleanup()
    collector.cleanup()

    assert len(collector) == 1


@pytest.mark.parametrize(
    "operation",
    [
        lambda collector: collector.add_review_item(
            row_ordinal=1,
            entity_type="client",
            topology_side="client_side",
            root_identity_snapshot=None,
            payload={"row": 1},
        ),
        lambda collector: collector.append({"row": 1}),
        lambda collector: collector.extend([{"row": 1}]),
        lambda collector: collector.remember_artifact_manifest_id(10),
        lambda collector: collector.flush(),
        lambda collector: collector.to_list(),
        lambda collector: list(iter(collector)),
        lambda collector: collector[0],
    ],
)
def test_cleanup_rejects_spool_backed_access_and_mutation(operation) -> None:
    collector = ImportReviewCollector(max_items_emergency=2)
    collector.append({"row": 1, "entity_type": "client"})
    collector.cleanup()

    with pytest.raises(RuntimeError, match="after cleanup"):
        operation(collector)
