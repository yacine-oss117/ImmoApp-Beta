"""
Intelligence layer for data enrichment and conflict resolution.

Handles: Duplicate detection, phone anchor enrichment, cross-column validation.
"""

from core.importer.intelligence.conflict_resolver import (
    DuplicateDetectionResult,
    DuplicateDetector,
    DuplicateMatch,
)

__all__ = [
    "DuplicateDetectionResult",
    "DuplicateDetector",
    "DuplicateMatch",
]
