"""Modern importer test harness (test-only).

This keeps legacy importer tests running against the current architecture
without requiring compatibility modules inside core/importer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

from core.importer.detection.column_detector import ColumnDetector
from core.importer.normalize_pipeline import NormalizationPipeline
from core.importer.parsers.csv_parser import CsvParser
from core.importer.parsers.excel import ExcelParser
from core.importer.parsers.ods_parser import OdsParser


@dataclass(frozen=True)
class ImportContext:
    agency_id: int
    user_id: int
    entity_type: str
    dry_run: bool = False
    batch_id: str = field(default_factory=lambda: uuid4().hex)

    def __post_init__(self) -> None:
        if self.agency_id <= 0:
            raise ValueError("agency_id must be a positive integer")
        if self.user_id <= 0:
            raise ValueError("user_id must be a positive integer")
        if self.entity_type not in {"client", "listing"}:
            raise ValueError("entity_type must be 'client' or 'listing'")


@dataclass
class ImportStats:
    total_rows: int = 0
    processed: int = 0
    needs_review: int = 0
    failed: int = 0

    @property
    def success_rate(self) -> float:
        if self.total_rows <= 0:
            return 100.0
        return (self.processed / self.total_rows) * 100.0


@dataclass
class ImportResult:
    context: ImportContext
    stats: ImportStats
    rows: list[dict[str, object]] = field(default_factory=list)
    review_rows: list[dict[str, object]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[object] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return not self.errors

    @property
    def has_review_items(self) -> bool:
        return bool(self.review_rows)


@dataclass
class TransformRowResult:
    data: dict[str, object]
    confidence: float
    needs_review: bool = False
    warnings: list[str] = field(default_factory=list)


class RowTransformer:
    """Header-aware transformer using modern normalizers."""

    def __init__(self, entity_type: str = "client") -> None:
        self._entity_type = entity_type
        self._detector = ColumnDetector()

    def transform_row(self, row: dict[str, object]) -> TransformRowResult:
        column_types: dict[str, str] = {}
        for column_name, value in row.items():
            detected = self._detector.detect_column_type(column_name, [str(value)])
            column_types[column_name] = detected.detected_type

        pipeline = NormalizationPipeline(
            entity_type=self._entity_type,
            column_types=column_types,
        )
        normalized = pipeline.normalize_row(row)
        data = dict(normalized.data)

        if "beds" in data:
            for column_name, detected_type in column_types.items():
                if detected_type == "type":
                    data.setdefault(f"{column_name}_beds", data["beds"])

        return TransformRowResult(
            data=data,
            confidence=normalized.confidence,
            needs_review=normalized.needs_review,
            warnings=normalized.remarks,
        )


class ImportEngine:
    def __init__(self, context: ImportContext, skip_rows: int = 0) -> None:
        self._context = context
        self._skip_rows = max(0, int(skip_rows))
        self._transformer = RowTransformer(entity_type=context.entity_type)

    def import_file(self, file_path: str | Path) -> ImportResult:
        path = Path(file_path)
        if not path.exists():
            return ImportResult(
                context=self._context,
                stats=ImportStats(total_rows=0, processed=0, failed=1),
                errors=[f"File not found: {path}"],
            )

        try:
            parser = _select_parser(path, self._skip_rows)
        except ValueError as exc:
            return ImportResult(
                context=self._context,
                stats=ImportStats(total_rows=0, processed=0, failed=1),
                errors=[str(exc)],
            )

        try:
            parsed = parser.parse(path)
            warnings = list(parsed.warnings)
            rows: list[dict[str, object]] = []
            review_rows: list[dict[str, object]] = []

            for idx, raw in enumerate(parser.iter_dicts(path), start=1):
                transformed = self._transformer.transform_row(raw)
                payload = dict(transformed.data)
                payload.pop("agency_id", None)
                payload["_import_batch_id"] = self._context.batch_id
                payload["_import_user_id"] = self._context.user_id
                payload["_import_row_index"] = idx
                payload["_import_confidence"] = transformed.confidence

                if transformed.needs_review:
                    review_rows.append(payload)
                else:
                    rows.append(payload)
                warnings.extend(transformed.warnings)

            total_rows = len(rows) + len(review_rows)
            stats = ImportStats(
                total_rows=total_rows,
                processed=len(rows),
                needs_review=len(review_rows),
                failed=0,
            )
            return ImportResult(
                context=self._context,
                stats=stats,
                rows=rows,
                review_rows=review_rows,
                warnings=warnings,
                errors=[],
            )
        except Exception as exc:
            return ImportResult(
                context=self._context,
                stats=ImportStats(total_rows=0, processed=0, failed=1),
                errors=[str(exc)],
            )


def import_file(
    file_path: str | Path,
    *,
    agency_id: int,
    user_id: int,
    entity_type: str,
    skip_rows: int = 0,
) -> ImportResult:
    context = ImportContext(
        agency_id=agency_id,
        user_id=user_id,
        entity_type=entity_type,
    )
    engine = ImportEngine(context, skip_rows=skip_rows)
    return engine.import_file(file_path)


def _select_parser(path: Path, skip_rows: int) -> CsvParser | ExcelParser | OdsParser:
    suffix = path.suffix.lower()
    if suffix in {".csv", ".tsv", ".txt"}:
        return CsvParser(skip_rows=skip_rows)
    if suffix == ".xlsx":
        return ExcelParser(skip_rows=skip_rows)
    if suffix == ".ods":
        return OdsParser(skip_rows=skip_rows)
    raise ValueError(f"Unsupported file type: {suffix or '<none>'}")
