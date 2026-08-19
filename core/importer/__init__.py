"""
Data Import Engine.

A deterministic, forgiving data ingestion system that converts agency data
(Excel, CSV, etc.) into normalized database records.

Submodules:
    parsers: File format parsers (Excel, CSV, JSON)
    detection: Column and template detection
    normalizers: Field normalization (phone, location, price, etc.)
    normalize_pipeline: Server-side normalization pipeline
    master_data: Reference data (wilayas, communes, aliases)
"""

from core.importer.normalize_pipeline import NormalizationPipeline, NormalizedRow

__all__ = [
    "NormalizationPipeline",
    "NormalizedRow",
]
