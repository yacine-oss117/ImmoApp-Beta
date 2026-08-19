from __future__ import annotations

from pathlib import Path
from zipfile import ZipFile

import pytest

from server.services.import_file_security import validate_import_file
from server.services.storage_errors import StorageError


def test_validate_import_file_rejects_binary_csv(tmp_path: Path) -> None:
    path = tmp_path / "malicious.csv"
    path.write_bytes(b"\x00\x01\x02binary")

    with pytest.raises(StorageError):
        validate_import_file(path, path.name)


def test_validate_import_file_accepts_minimal_xlsx_signature(tmp_path: Path) -> None:
    path = tmp_path / "sample.xlsx"
    with ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("xl/workbook.xml", "<workbook/>")

    assert validate_import_file(path, path.name) == "excel"


def test_validate_import_file_rejects_invalid_xlsx_archive(tmp_path: Path) -> None:
    path = tmp_path / "sample.xlsx"
    with ZipFile(path, "w") as archive:
        archive.writestr("not_excel.txt", "nope")

    with pytest.raises(StorageError):
        validate_import_file(path, path.name)


def test_validate_import_file_accepts_minimal_ods_signature(tmp_path: Path) -> None:
    path = tmp_path / "sample.ods"
    with ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/vnd.oasis.opendocument.spreadsheet")
        archive.writestr("content.xml", "<office:document-content/>")

    assert validate_import_file(path, path.name) == "ods"


def test_validate_import_file_rejects_legacy_excel_extensions(tmp_path: Path) -> None:
    path = tmp_path / "legacy.xls"
    path.write_bytes(b"placeholder")

    with pytest.raises(StorageError):
        validate_import_file(path, path.name)
