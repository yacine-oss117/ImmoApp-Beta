"""Public planning-phase facades for importer execution."""

from __future__ import annotations

from typing import Any, cast

from server.imports.models import ImportJob
from server.services.import_agency_memory import AgencyAliasMemory
from server.services.import_identity_resolution import (
    ResolutionResult,
)
from server.services.import_identity_resolution import (
    prefetch_child_match_cache as _prefetch_child_match_cache_impl,
)
from server.services.import_identity_resolution import (
    prefetch_root_match_cache as _prefetch_root_match_cache_impl,
)
from server.services.import_identity_resolution import (
    resolve_child_anchor as _resolve_child_anchor_impl,
)
from server.services.import_identity_resolution import (
    resolve_existing_matches as _resolve_existing_matches_impl,
)
from server.services.import_plan_flows import (
    _apply_planning_recovery as _apply_planning_recovery_impl,
)
from server.services.import_plan_flows import (
    _blocked_duplicate_resolution_error as _blocked_duplicate_resolution_error_impl,
)
from server.services.import_plan_flows import (
    plan_child_only_import as _plan_child_only_import_impl,
)
from server.services.import_plan_flows import (
    plan_same_side_bundle_import as _plan_same_side_bundle_import_impl,
)
from server.services.import_plan_flows import (
    plan_single_entity_import as _plan_single_entity_import_impl,
)
from server.services.import_rows import validate_row as _validate_row_impl
from server.services.import_types import ImportResult, PreparedImportArtifact, ReviewRows


def _blocked_duplicate_resolution_error(*, row_num: int, resolution: object) -> dict[str, object]:
    return _blocked_duplicate_resolution_error_impl(row_num=row_num, resolution=resolution)


def _apply_planning_recovery(
    *,
    row_data: dict[str, object],
    original: dict[str, object],
    entity_type: str,
    column_types: dict[str, str],
    agency_memory: AgencyAliasMemory | None,
    bundle_context: dict[str, object] | None = None,
) -> dict[str, object]:
    return _apply_planning_recovery_impl(
        row_data=row_data,
        original=original,
        entity_type=entity_type,
        column_types=column_types,
        agency_memory=agency_memory,
        bundle_context=bundle_context,
    )


def prefetch_root_match_cache(**kwargs: Any) -> None:
    _prefetch_root_match_cache_impl(**kwargs)


def prefetch_child_match_cache(**kwargs: Any) -> None:
    _prefetch_child_match_cache_impl(**kwargs)


def resolve_child_anchor(**kwargs: Any) -> int:
    return int(_resolve_child_anchor_impl(**kwargs))


def validate_row(
    row_data: dict[str, object],
    entity_type: str,
) -> tuple[dict[str, object], list[str]]:
    return _validate_row_impl(row_data, entity_type)


def resolve_existing_matches(**kwargs: Any) -> ResolutionResult:
    return cast(ResolutionResult, _resolve_existing_matches_impl(**kwargs))


def plan_single_entity_import(
    *,
    job: ImportJob,
    entity_type: str,
    duplicate_strategy: str,
    skip_review_rows: bool,
    review_rows: ReviewRows,
    errors: list[dict[str, object]],
    result: ImportResult,
    artifact: PreparedImportArtifact,
) -> PreparedImportArtifact:
    return _plan_single_entity_import_impl(
        job=job,
        entity_type=entity_type,
        duplicate_strategy=duplicate_strategy,
        skip_review_rows=skip_review_rows,
        review_rows=review_rows,
        errors=errors,
        result=result,
        artifact=artifact,
    )


def plan_child_only_import(
    *,
    job: ImportJob,
    user_id: int,
    entity_type: str,
    duplicate_strategy: str,
    skip_review_rows: bool,
    review_rows: ReviewRows,
    errors: list[dict[str, object]],
    result: ImportResult,
    artifact: PreparedImportArtifact,
) -> PreparedImportArtifact:
    return _plan_child_only_import_impl(
        job=job,
        user_id=user_id,
        entity_type=entity_type,
        duplicate_strategy=duplicate_strategy,
        skip_review_rows=skip_review_rows,
        review_rows=review_rows,
        errors=errors,
        result=result,
        artifact=artifact,
        apply_planning_recovery_fn=_apply_planning_recovery,
        blocked_duplicate_resolution_error_fn=_blocked_duplicate_resolution_error,
        prefetch_root_match_cache_fn=prefetch_root_match_cache,
        prefetch_child_match_cache_fn=prefetch_child_match_cache,
        resolve_child_anchor_fn=resolve_child_anchor,
        validate_row_fn=validate_row,
        resolve_existing_matches_fn=resolve_existing_matches,
    )


def plan_same_side_bundle_import(
    *,
    job: ImportJob,
    user_id: int,
    duplicate_strategy: str,
    skip_review_rows: bool,
    review_rows: ReviewRows,
    errors: list[dict[str, object]],
    result: ImportResult,
    artifact: PreparedImportArtifact,
) -> PreparedImportArtifact:
    return _plan_same_side_bundle_import_impl(
        job=job,
        user_id=user_id,
        duplicate_strategy=duplicate_strategy,
        skip_review_rows=skip_review_rows,
        review_rows=review_rows,
        errors=errors,
        result=result,
        artifact=artifact,
        apply_planning_recovery_fn=_apply_planning_recovery,
        blocked_duplicate_resolution_error_fn=_blocked_duplicate_resolution_error,
        prefetch_root_match_cache_fn=prefetch_root_match_cache,
        prefetch_child_match_cache_fn=prefetch_child_match_cache,
        resolve_child_anchor_fn=resolve_child_anchor,
        validate_row_fn=validate_row,
        resolve_existing_matches_fn=resolve_existing_matches,
    )


__all__ = [
    "_apply_planning_recovery",
    "prefetch_root_match_cache",
    "prefetch_child_match_cache",
    "resolve_child_anchor",
    "resolve_existing_matches",
    "validate_row",
    "plan_child_only_import",
    "plan_same_side_bundle_import",
    "plan_single_entity_import",
]
