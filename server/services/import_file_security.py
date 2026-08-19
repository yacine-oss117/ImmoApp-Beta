"""Import file admission and signature validation helpers."""

from __future__ import annotations

from pathlib import Path
from zipfile import ZipFile

from core.importer.security import import_security_limits

from .storage_errors import StorageError

_TEXT_EXTENSIONS = {".csv", ".tsv", ".txt"}


def validate_import_file(path: Path, filename: str) -> str:
    ext = Path(filename or path.name).suffix.lower()
    if ext in _TEXT_EXTENSIONS:
        _validate_text_file(path)
        return "csv"
    if ext == ".xlsx":
        _validate_excel_file(path)
        return "excel"
    if ext == ".ods":
        _validate_ods_file(path)
        return "ods"
    raise StorageError(f"Unsupported import file type: {ext or '<none>'}")


def _validate_text_file(path: Path) -> None:
    with path.open("rb") as handle:
        sample = handle.read(import_security_limits().sniff_bytes)
    if b"\x00" in sample:
        raise StorageError("Import file appears binary or corrupted.")
    if not sample:
        raise StorageError("Import file is empty.")
    suspicious = 0
    for byte in sample:
        if byte in (9, 10, 13):
            continue
        if byte < 32:
            suspicious += 1
    if suspicious > max(8, len(sample) // 20):
        raise StorageError("Import file contains unsupported binary control bytes.")


def _validate_excel_file(path: Path) -> None:
    _validate_archive(
        path,
        required_entries={"[Content_Types].xml"},
        required_prefixes=("xl/",),
        invalid_message="Import workbook is invalid or corrupted.",
    )


def _validate_ods_file(path: Path) -> None:
    _validate_archive(
        path,
        required_entries={"content.xml", "mimetype"},
        required_prefixes=(),
        invalid_message="Import spreadsheet is invalid or corrupted.",
    )
    with ZipFile(path) as archive:
        try:
            mimetype_value = archive.read("mimetype").decode("utf-8", errors="replace").strip()
        except KeyError as exc:
            raise StorageError("Import spreadsheet is missing ODS metadata.") from exc
    if mimetype_value != "application/vnd.oasis.opendocument.spreadsheet":
        raise StorageError("Import spreadsheet has an unexpected ODS mimetype.")


def _validate_archive(
    path: Path,
    *,
    required_entries: set[str],
    required_prefixes: tuple[str, ...],
    invalid_message: str,
) -> None:
    limits = import_security_limits()
    try:
        with ZipFile(path) as archive:
            infos = archive.infolist()
            if not infos:
                raise StorageError(invalid_message)
            if len(infos) > limits.max_archive_entries:
                raise StorageError(
                    f"Import archive exceeds the maximum entry count ({limits.max_archive_entries})."
                )
            total_uncompressed = sum(max(0, int(info.file_size or 0)) for info in infos)
            if total_uncompressed > limits.max_archive_uncompressed_bytes:
                raise StorageError("Import archive expands beyond the maximum supported size.")
            total_compressed = sum(max(0, int(info.compress_size or 0)) for info in infos)
            if total_uncompressed > 0 and total_uncompressed / max(1, total_compressed) > float(
                limits.max_archive_compression_ratio
            ):
                raise StorageError("Import archive compression ratio is suspiciously high.")
            names = {info.filename for info in infos}
            missing_entries = sorted(required_entries - names)
            if missing_entries:
                raise StorageError(invalid_message)
            if required_prefixes and not any(
                info.filename.startswith(prefix) for info in infos for prefix in required_prefixes
            ):
                raise StorageError(invalid_message)
    except StorageError:
        raise
    except Exception as exc:
        raise StorageError(invalid_message) from exc


__all__ = ["validate_import_file"]
