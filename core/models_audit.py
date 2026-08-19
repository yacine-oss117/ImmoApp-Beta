"""
Audit log domain model.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from core.models_cast import as_int, as_str, row_value


@dataclass
class AuditLog:
    """Audit log entry for data changes."""

    id: int = 0
    ts: str = ""
    actor: str = ""
    action: str = ""
    table_name: str = ""
    record_id: str = ""

    @classmethod
    def from_row(cls, row: Mapping[str, object]) -> AuditLog:
        """Create an AuditLog from a database row."""
        keys = row.keys()
        return cls(
            id=as_int(row["id"]),
            ts=as_str(row_value(row, "ts")),
            actor=as_str(row_value(row, "actor")) if "actor" in keys else "",
            action=as_str(row_value(row, "action")),
            table_name=as_str(row_value(row, "table_name")),
            record_id=as_str(row_value(row, "record_id")) if "record_id" in keys else "",
        )
