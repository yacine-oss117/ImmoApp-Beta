from __future__ import annotations

import os
from decimal import Decimal
from typing import Any, cast

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "server.immoapp_server.settings")
django.setup()

from server.services.import_review_runtime_state import persist_review_state  # noqa: E402
from server.services.import_types import ReviewRowPayload  # noqa: E402


class _Job:
    def __init__(self) -> None:
        self.review_rows: list[dict[str, object]] = []
        self.stage = "execution"
        self.saved_update_fields: list[str] | None = None

    def save(self, update_fields: list[str] | None = None) -> None:
        self.saved_update_fields = update_fields


def test_persist_review_state_normalizes_nested_decimal_review_payloads() -> None:
    job = _Job()
    review_rows: list[ReviewRowPayload] = [
        {
            "row": 17,
            "candidate_matches": [
                {
                    "field_diff": {
                        "changed_mutable": [
                            {
                                "field": "budget_max",
                                "existing": Decimal("2500000.00"),
                                "incoming": Decimal("2700000.50"),
                            }
                        ],
                        "changed_immutable": [],
                        "unchanged": [],
                    }
                }
            ],
        }
    ]

    persist_review_state(
        job=cast(Any, job),
        review_rows=review_rows,
        progress_detail={"phase": "review", "rows_review": 1},
    )

    assert job.review_rows == [
        {
            "row": 17,
            "candidate_matches": [
                {
                    "field_diff": {
                        "changed_mutable": [
                            {
                                "field": "budget_max",
                                "existing": 2500000,
                                "incoming": 2700000.5,
                            }
                        ],
                        "changed_immutable": [],
                        "unchanged": [],
                    }
                }
            ],
        }
    ]
    assert job.saved_update_fields == ["review_rows", "stage", "progress_detail", "updated_at"]
