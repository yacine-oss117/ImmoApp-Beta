from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Any, cast

import django
import pytest
from psycopg_pool import PoolTimeout

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "server.immoapp_server.settings")
django.setup()

from server.services.import_progress_runtime import persist_job_progress  # noqa: E402


class _Job:
    def __init__(self) -> None:
        self.id = "job-123"
        self.progress = 0
        self.progress_detail: dict[str, object] = {}


class _PoolTimeoutUow:
    @contextmanager
    def transaction(self, **_kwargs: object) -> Any:
        raise PoolTimeout("simulated saturation")
        yield


def test_persist_job_progress_tolerates_detached_pool_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "server.services.import_progress_runtime.get_uow",
        lambda: _PoolTimeoutUow(),
    )

    job = _Job()
    progress_detail = persist_job_progress(
        write_session=None,
        job=cast(Any, job),
        rows_total=100,
        rows_processed=25,
        rows_created=0,
        rows_updated=0,
        rows_skipped=0,
        rows_review=0,
        current_chunk=1,
        chunks_total=4,
        phase="planning",
        bundle_mode="same_side_bundle",
    )

    assert job.progress == 25
    assert job.progress_detail == progress_detail
    assert progress_detail["rows_processed"] == 25
