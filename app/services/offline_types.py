"""Shared offline operation types for durable client-side mutation replay."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal

OfflineEntityType = Literal[
    "client",
    "demande",
    "listing",
    "offer",
    "offer_photo",
    "visit",
    "contract",
    "contract_article",
    "generic",
]
OfflineOpType = Literal["create", "update", "delete", "action"]
OfflineOpStatus = Literal[
    "pending",
    "syncing",
    "blocked",
    "needs_review",
    "applied",
    "cancelled",
]


@dataclass(frozen=True)
class OfflineEntityRef:
    entity_type: OfflineEntityType
    local_id: int

    def to_dict(self) -> dict[str, object]:
        return {"entity_type": self.entity_type, "local_id": int(self.local_id)}

    @classmethod
    def from_dict(cls, payload: object) -> OfflineEntityRef:
        if not isinstance(payload, dict):
            raise ValueError("invalid offline entity ref")
        return cls(
            entity_type=str(payload.get("entity_type") or "generic"),  # type: ignore[arg-type]
            local_id=int(payload.get("local_id") or 0),
        )


@dataclass
class OfflineOperation:
    op_id: str
    account_key: str
    entity_type: OfflineEntityType
    op_type: OfflineOpType
    local_id: int
    payload: dict[str, object]
    parent_refs: list[OfflineEntityRef] = field(default_factory=list)
    dedupe_key: str = ""
    status: OfflineOpStatus = "pending"
    attempts: int = 0
    last_error: str = ""
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["parent_refs"] = [ref.to_dict() for ref in self.parent_refs]
        return payload

    @classmethod
    def from_dict(cls, payload: object) -> OfflineOperation:
        if not isinstance(payload, dict):
            raise ValueError("invalid offline operation")
        parent_refs_raw = payload.get("parent_refs")
        parent_refs = (
            [OfflineEntityRef.from_dict(item) for item in parent_refs_raw]
            if isinstance(parent_refs_raw, list)
            else []
        )
        raw_payload = payload.get("payload")
        return cls(
            op_id=str(payload.get("op_id") or ""),
            account_key=str(payload.get("account_key") or ""),
            entity_type=str(payload.get("entity_type") or "generic"),  # type: ignore[arg-type]
            op_type=str(payload.get("op_type") or "action"),  # type: ignore[arg-type]
            local_id=int(payload.get("local_id") or 0),
            payload=dict(raw_payload) if isinstance(raw_payload, dict) else {},
            parent_refs=parent_refs,
            dedupe_key=str(payload.get("dedupe_key") or ""),
            status=str(payload.get("status") or "pending"),  # type: ignore[arg-type]
            attempts=int(payload.get("attempts") or 0),
            last_error=str(payload.get("last_error") or ""),
            created_at=str(payload.get("created_at") or ""),
            updated_at=str(payload.get("updated_at") or ""),
        )


@dataclass
class OfflineConflict:
    op_id: str
    entity_type: OfflineEntityType
    local_id: int
    reason_code: str
    message: str
    server_payload: dict[str, object] | None = None
    created_at: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "op_id": self.op_id,
            "entity_type": self.entity_type,
            "local_id": int(self.local_id),
            "reason_code": self.reason_code,
            "message": self.message,
            "server_payload": dict(self.server_payload or {}),
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, payload: object) -> OfflineConflict:
        if not isinstance(payload, dict):
            raise ValueError("invalid offline conflict")
        raw_server_payload = payload.get("server_payload")
        return cls(
            op_id=str(payload.get("op_id") or ""),
            entity_type=str(payload.get("entity_type") or "generic"),  # type: ignore[arg-type]
            local_id=int(payload.get("local_id") or 0),
            reason_code=str(payload.get("reason_code") or ""),
            message=str(payload.get("message") or ""),
            server_payload=(
                dict(raw_server_payload) if isinstance(raw_server_payload, dict) else None
            ),
            created_at=str(payload.get("created_at") or ""),
        )


@dataclass
class OfflineProjectionRecord:
    entity_type: OfflineEntityType
    local_id: int
    server_id: int | None
    data: dict[str, object]
    sync_status: str
    sync_error: str = ""
    is_local_only: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "entity_type": self.entity_type,
            "local_id": int(self.local_id),
            "server_id": self.server_id,
            "data": dict(self.data),
            "sync_status": self.sync_status,
            "sync_error": self.sync_error,
            "is_local_only": bool(self.is_local_only),
        }

    @classmethod
    def from_dict(cls, payload: object) -> OfflineProjectionRecord:
        if not isinstance(payload, dict):
            raise ValueError("invalid offline projection record")
        raw_data = payload.get("data")
        raw_server_id = payload.get("server_id")
        server_id = int(raw_server_id) if isinstance(raw_server_id, int) else None
        return cls(
            entity_type=str(payload.get("entity_type") or "generic"),  # type: ignore[arg-type]
            local_id=int(payload.get("local_id") or 0),
            server_id=server_id,
            data=dict(raw_data) if isinstance(raw_data, dict) else {},
            sync_status=str(payload.get("sync_status") or ""),
            sync_error=str(payload.get("sync_error") or ""),
            is_local_only=bool(payload.get("is_local_only")),
        )


__all__ = [
    "OfflineConflict",
    "OfflineEntityRef",
    "OfflineEntityType",
    "OfflineOpStatus",
    "OfflineOpType",
    "OfflineOperation",
    "OfflineProjectionRecord",
]
