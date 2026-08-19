"""Public prepare-phase facades for importer execution."""

from __future__ import annotations

from typing import Any

from server.imports.models import ImportJob
from server.services.import_prepare_flows import DownloadToTemp, InferRowEntityFn
from server.services.import_prepare_flows import (
    prepare_child_only_import as _prepare_child_only_import_impl,
)
from server.services.import_prepare_flows import (
    prepare_same_side_bundle_import as _prepare_same_side_bundle_import_impl,
)
from server.services.import_prepare_flows import (
    prepare_single_entity_import as _prepare_single_entity_import_impl,
)
from server.services.import_type_inference import infer_row_entity
from server.services.import_types import ImportResult, PreparedImportArtifact, ReviewRows
from server.services.storage import download_to_temp


def prepare_child_only_import(
    *,
    job: ImportJob,
    entity_type: str,
    skip_rows: int,
    skip_review_rows: bool,
    corrections: dict[str, dict[str, Any]] | None,
    review_rows: ReviewRows,
    result: ImportResult,
    download_to_temp_fn: DownloadToTemp = download_to_temp,
) -> PreparedImportArtifact:
    return _prepare_child_only_import_impl(
        job=job,
        entity_type=entity_type,
        skip_rows=skip_rows,
        skip_review_rows=skip_review_rows,
        corrections=corrections,
        review_rows=review_rows,
        result=result,
        download_to_temp_fn=download_to_temp_fn,
    )


def prepare_same_side_bundle_import(
    *,
    job: ImportJob,
    root_entity: str,
    child_entity: str,
    topology_side: str,
    skip_rows: int,
    skip_review_rows: bool,
    duplicate_strategy: str,
    corrections: dict[str, dict[str, Any]] | None,
    review_rows: ReviewRows,
    result: ImportResult,
    download_to_temp_fn: DownloadToTemp = download_to_temp,
) -> PreparedImportArtifact:
    return _prepare_same_side_bundle_import_impl(
        job=job,
        root_entity=root_entity,
        child_entity=child_entity,
        topology_side=topology_side,
        skip_rows=skip_rows,
        skip_review_rows=skip_review_rows,
        duplicate_strategy=duplicate_strategy,
        corrections=corrections,
        review_rows=review_rows,
        result=result,
        download_to_temp_fn=download_to_temp_fn,
        infer_row_entity_fn=infer_row_entity,
    )


def prepare_single_entity_import(
    *,
    job: ImportJob,
    user_id: int,
    entity_type: str,
    skip_rows: int,
    skip_review_rows: bool,
    duplicate_strategy: str,
    corrections: dict[str, dict[str, Any]] | None,
    review_rows: ReviewRows,
    result: ImportResult,
    download_to_temp_fn: DownloadToTemp = download_to_temp,
) -> PreparedImportArtifact:
    return _prepare_single_entity_import_impl(
        job=job,
        user_id=user_id,
        entity_type=entity_type,
        skip_rows=skip_rows,
        skip_review_rows=skip_review_rows,
        duplicate_strategy=duplicate_strategy,
        corrections=corrections,
        review_rows=review_rows,
        result=result,
        download_to_temp_fn=download_to_temp_fn,
    )


__all__ = [
    "DownloadToTemp",
    "InferRowEntityFn",
    "infer_row_entity",
    "prepare_child_only_import",
    "prepare_same_side_bundle_import",
    "prepare_single_entity_import",
]
