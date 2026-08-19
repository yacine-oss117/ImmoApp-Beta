"""Direct same-side bundle root conflict-isolation adapter."""

from __future__ import annotations

from typing import Any, cast

from core.contracts.import_batch_refs import CreatedRowRef
from server.pg.uow import PgSession
from server.services.import_batch_write_refs import insert_batch_refs
from server.services.import_load_policy import (
    build_root_conflict_error,
    flush_root_entries_with_conflict_isolation,
    remember_created_anchor_keys,
)
from server.services.import_types import ImportLoadOutcome


def _flush_bundle_root_entries_with_conflict_isolation(
    *,
    write_session: PgSession,
    entity_type: str,
    batch_entries: list[dict[str, object]],
    imported_ids: list[int],
    load_outcome: ImportLoadOutcome,
    created_anchor_map: dict[str, int],
    load_errors: list[dict[str, object]],
) -> tuple[list[int], float]:
    def _on_rows_inserted(
        created_rows: list[CreatedRowRef],
        inserted_entries: list[dict[str, object]],
    ) -> None:
        imported_ids.extend(int(created_row.created_id) for created_row in created_rows)
        remember_created_anchor_keys(
            created_anchor_map=created_anchor_map,
            batch_entries=cast(list[dict[str, Any]], inserted_entries),
            created_rows=created_rows,
        )

    def _append_leaf_error(entry: dict[str, object]) -> None:
        load_errors.append(
            build_root_conflict_error(
                entry=cast(dict[str, Any], entry),
                message="A planned root row no longer loads safely. Restart the import.",
            )
        )

    result = flush_root_entries_with_conflict_isolation(
        write_session=write_session,
        entity_type=entity_type,
        batch_entries=cast(list[dict[str, Any]], batch_entries),
        load_outcome=load_outcome,
        on_rows_inserted=_on_rows_inserted,
        append_leaf_error=_append_leaf_error,
        insert_batch_fn=insert_batch_refs,
    )
    return result.created_ids, result.db_duration


__all__ = ["_flush_bundle_root_entries_with_conflict_isolation"]
