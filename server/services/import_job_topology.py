"""Typed importer topology owner for bundle mode and entity-side inference."""

from __future__ import annotations

from dataclasses import dataclass

from server.imports.models import ImportJob
from server.services.import_constants import (
    ENTITY_TYPE_CLIENT,
    ENTITY_TYPE_DEMANDE,
    ENTITY_TYPE_LISTING,
    ENTITY_TYPE_OFFER,
)


@dataclass(frozen=True)
class ImportJobTopology:
    bundle_mode: str
    topology_side: str
    root_entity: str
    child_entity: str


def job_topology(job: ImportJob) -> ImportJobTopology:
    inference = dict((job.inference_summary or {}).get("final_inference", {}) or {})
    bundle_mode = str(inference.get("bundle_mode", "single_entity") or "single_entity")
    topology_side = str(inference.get("topology_side_hint", "unknown") or "unknown")
    if topology_side == "client_side":
        root_entity = ENTITY_TYPE_CLIENT
        child_entity = ENTITY_TYPE_DEMANDE
    else:
        root_entity = ENTITY_TYPE_LISTING
        child_entity = ENTITY_TYPE_OFFER
    return ImportJobTopology(
        bundle_mode=bundle_mode,
        topology_side=topology_side,
        root_entity=root_entity,
        child_entity=child_entity,
    )


__all__ = ["ImportJobTopology", "job_topology"]
