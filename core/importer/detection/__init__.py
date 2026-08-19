"""
Detection module for column, header, and entity type inference.

Handles: Column type detection, header row detection, entity type detection.
"""

from core.importer.detection.column_detector import ColumnDetector, ColumnTypeResult
from core.importer.detection.entity_detector import (
    EntityTypeDetector,
    EntityTypeResult,
    detect_entity_type_from_columns,
)
from core.importer.detection.header_detector import HeaderDetectionResult, HeaderDetector

__all__ = [
    "ColumnDetector",
    "ColumnTypeResult",
    "EntityTypeDetector",
    "EntityTypeResult",
    "HeaderDetectionResult",
    "HeaderDetector",
    "detect_entity_type_from_columns",
]
