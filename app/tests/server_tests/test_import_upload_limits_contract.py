from __future__ import annotations

import ast
from pathlib import Path

from server.api import request_schemas_import as import_schemas

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_import_presign_serializer_rejects_oversize_payload(monkeypatch) -> None:
    class _Cfg:
        max_import_bytes = 10

    monkeypatch.setattr(import_schemas, "get_storage_config", lambda: _Cfg())
    serializer = import_schemas.ImportPresignSerializer(
        data={
            "filename": "sample.csv",
            "size_bytes": 11,
            "content_type": "text/csv",
        }
    )
    assert not serializer.is_valid()
    assert "size_bytes" in serializer.errors


def test_import_presign_serializer_accepts_in_limit_payload(monkeypatch) -> None:
    class _Cfg:
        max_import_bytes = 10

    monkeypatch.setattr(import_schemas, "get_storage_config", lambda: _Cfg())
    serializer = import_schemas.ImportPresignSerializer(
        data={
            "filename": "sample.csv",
            "size_bytes": 10,
            "content_type": "text/csv",
        }
    )
    assert serializer.is_valid(), serializer.errors


def test_import_upload_view_has_proxy_oversize_guard() -> None:
    source_path = REPO_ROOT / "server" / "api" / "views_import_upload.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    found_guard = False

    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        if not (isinstance(node.left, ast.Name) and node.left.id == "file_size"):
            continue
        if len(node.ops) != 1 or not isinstance(node.ops[0], ast.Gt):
            continue
        if len(node.comparators) != 1:
            continue
        comparator = node.comparators[0]
        if isinstance(comparator, ast.Name) and comparator.id == "max_import_bytes":
            found_guard = True
            break

    assert found_guard, "import_upload must reject proxy uploads larger than max_import_bytes"


def test_import_upload_views_use_import_parse_budget_gate() -> None:
    source = (REPO_ROOT / "server" / "api" / "views_import_upload.py").read_text(encoding="utf-8")
    assert "admit_import_parse(" in source
    assert "IMPORT_PARSE_BACKPRESSURE" in source


def test_step_upload_no_longer_advertises_legacy_xls() -> None:
    source = (REPO_ROOT / "app" / "views" / "imports" / "step_upload.py").read_text(
        encoding="utf-8"
    )
    assert "*.xlsx *.xls" not in source
    assert '".xls"' not in source


def test_import_storage_paths_validate_file_signatures() -> None:
    fileobj_source = (
        REPO_ROOT / "server" / "services" / "storage_ops_upload_fileobj.py"
    ).read_text(encoding="utf-8")
    presign_source = (
        REPO_ROOT / "server" / "services" / "storage_ops_upload_presign.py"
    ).read_text(encoding="utf-8")
    assert "validate_import_file(" in fileobj_source
    assert "validate_import_file(" in presign_source


def test_settings_base_defines_upload_size_caps() -> None:
    source_path = REPO_ROOT / "server" / "immoapp_server" / "settings_base.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    assigned: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    assigned.add(target.id)
    required = {
        "IMMOAPP_PROXY_UPLOAD_MAX_BYTES",
        "IMMOAPP_FILE_UPLOAD_MEMORY_THRESHOLD",
        "DATA_UPLOAD_MAX_MEMORY_SIZE",
        "FILE_UPLOAD_MAX_MEMORY_SIZE",
    }
    missing = sorted(required - assigned)
    assert not missing, f"Missing upload cap assignments in settings_base.py: {', '.join(missing)}"
