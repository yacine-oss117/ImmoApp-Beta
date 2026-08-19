from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any


@dataclass(frozen=True)
class BundleFile:
    path: str
    bytes: int
    sha256: str


@dataclass(frozen=True)
class ParsedManifest:
    raw: dict[str, Any]
    source_bucket: str
    mirror_root: str
    files: tuple[BundleFile, ...]
    files_by_path: dict[str, BundleFile]


class ManifestError(RuntimeError):
    pass


_DRIVE_PREFIX = re.compile(r"^[A-Za-z]:")
_SAFE_BUCKET = re.compile(r"^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$")


def _safe_manifest_path(raw: object) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise ManifestError(f"Invalid manifest file path: {raw!r}")
    path = raw.replace("\\", "/")
    pure = PurePosixPath(path)
    if pure.is_absolute() or _DRIVE_PREFIX.match(path):
        raise ManifestError(f"Unsafe absolute manifest path: {raw}")
    if any(part in {"", ".", ".."} for part in pure.parts):
        raise ManifestError(f"Unsafe traversal manifest path: {raw}")
    return pure.as_posix()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_bucket_name(raw: object) -> str:
    bucket = str(raw or "").strip()
    if not _SAFE_BUCKET.fullmatch(bucket):
        raise ManifestError(f"Invalid object storage bucket name: {bucket!r}")
    return bucket


def _load_manifest_bytes(data: bytes) -> dict[str, Any]:
    try:
        manifest = json.loads(data.decode("utf-8-sig"))
    except Exception as exc:
        raise ManifestError(f"Invalid manifest.json: {exc}") from exc
    if not isinstance(manifest, dict):
        raise ManifestError("manifest.json must contain a JSON object")
    return manifest


def _load_manifest_from_zip(bundle: Path) -> tuple[dict[str, Any], zipfile.ZipFile]:
    archive = zipfile.ZipFile(bundle)
    names = archive.namelist()
    if len(names) != len(set(names)):
        archive.close()
        raise ManifestError("Release bundle zip contains duplicate member names")
    safe_names: set[str] = set()
    for name in names:
        safe_names.add(_safe_manifest_path(name))
    if "manifest.json" not in safe_names:
        archive.close()
        raise ManifestError("Release bundle manifest missing: manifest.json")
    try:
        manifest = _load_manifest_bytes(archive.read("manifest.json"))
    except Exception:
        archive.close()
        raise
    return manifest, archive


def _load_manifest_from_dir(bundle: Path) -> dict[str, Any]:
    manifest_path = bundle / "manifest.json"
    if not manifest_path.is_file():
        raise ManifestError("Release bundle manifest missing: manifest.json")
    return _load_manifest_bytes(manifest_path.read_bytes())


def _manifest_files(manifest: dict[str, Any]) -> list[BundleFile]:
    raw_files = manifest.get("files")
    if not isinstance(raw_files, list):
        raise ManifestError("manifest.files must be a list")
    files: list[BundleFile] = []
    seen: set[str] = set()
    for item in raw_files:
        if not isinstance(item, dict):
            raise ManifestError("manifest.files contains a non-object entry")
        path = _safe_manifest_path(item.get("path"))
        if path == "manifest.json":
            raise ManifestError("manifest.json must not be listed as a payload file")
        if path in seen:
            raise ManifestError(f"Duplicate manifest file path: {path}")
        seen.add(path)
        raw_bytes = item.get("bytes")
        if not isinstance(raw_bytes, int | str):
            raise ManifestError(f"Invalid byte size for {path}")
        try:
            byte_count = int(raw_bytes)
        except ValueError as exc:
            raise ManifestError(f"Invalid byte size for {path}") from exc
        if byte_count < 0:
            raise ManifestError(f"Invalid negative byte size for {path}")
        sha = str(item.get("sha256") or "").strip().lower()
        if not re.fullmatch(r"[0-9a-f]{64}", sha):
            raise ManifestError(f"Invalid SHA-256 for {path}")
        files.append(BundleFile(path=path, bytes=byte_count, sha256=sha))
    return files


def _required_paths(manifest: dict[str, Any]) -> tuple[str, str]:
    if manifest.get("kind") != "immoapp_release_backup_bundle":
        raise ManifestError(f"Unsupported release bundle kind: {manifest.get('kind')!r}")
    database = manifest.get("database")
    if not isinstance(database, dict):
        raise ManifestError("manifest.database must be an object")
    dump_path = _safe_manifest_path(database.get("dump") or "database/immoapp.dump")
    if dump_path != "database/immoapp.dump":
        raise ManifestError("Release bundle database dump must be database/immoapp.dump")
    integrity_info = manifest.get("integrity")
    if not isinstance(integrity_info, dict):
        raise ManifestError("manifest.integrity must be an object")
    integrity_path = _safe_manifest_path(
        integrity_info.get("report") or "integrity/release_backup_integrity.json"
    )
    if integrity_path != "integrity/release_backup_integrity.json":
        raise ManifestError(
            "Release bundle integrity report must be integrity/release_backup_integrity.json"
        )
    object_storage = manifest.get("object_storage")
    if not isinstance(object_storage, dict):
        raise ManifestError("manifest.object_storage must be an object")
    mirror_root = _safe_manifest_path(object_storage.get("mirror_root"))
    bucket = _safe_bucket_name(object_storage.get("bucket"))
    if mirror_root != f"minio/{bucket}":
        raise ManifestError("manifest.object_storage.mirror_root must match minio/<bucket>")
    return integrity_path, mirror_root


def _zip_payload_member_map(archive: zipfile.ZipFile) -> dict[str, str]:
    actual: dict[str, str] = {}
    for info in archive.infolist():
        path = _safe_manifest_path(info.filename)
        if info.is_dir():
            continue
        if path == "manifest.json":
            continue
        if path in actual:
            raise ManifestError(f"Release bundle zip contains duplicate payload path: {path}")
        actual[path] = info.filename
    return actual


def _actual_dir_payload_files(root: Path) -> set[str]:
    actual: set[str] = set()
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.is_symlink():
            raise ManifestError(f"Unsafe symlink payload file: {path}")
        rel = path.relative_to(root).as_posix()
        safe = _safe_manifest_path(rel)
        if safe == "manifest.json":
            continue
        actual.add(safe)
    return actual


def _assert_exact_payload_set(actual: set[str], files: list[BundleFile]) -> None:
    expected = {item.path for item in files}
    missing = sorted(expected - actual)
    unlisted = sorted(actual - expected)
    if missing:
        raise ManifestError(f"Manifest-listed file missing from bundle: {missing[0]}")
    if unlisted:
        raise ManifestError(f"Bundle contains unlisted payload file: {unlisted[0]}")


def _validate_files_from_zip(
    archive: zipfile.ZipFile,
    files: list[BundleFile],
    required_integrity: str,
    mirror_root: str,
) -> None:
    raw_names = set(archive.namelist())
    by_path = {item.path: item for item in files}
    for required in ("database/immoapp.dump", required_integrity):
        if required not in by_path:
            raise ManifestError(f"Required file missing from manifest: {required}")
    if not any(item.path.startswith(f"{mirror_root}/") for item in files):
        raise ManifestError(f"MinIO mirror root is missing or empty: {mirror_root}")
    member_map = _zip_payload_member_map(archive)
    _assert_exact_payload_set(set(member_map), files)
    for item in files:
        raw_name = member_map.get(item.path)
        if raw_name is None or raw_name not in raw_names:
            raise ManifestError(f"Manifest file missing from zip: {item.path}")
        data = archive.read(raw_name)
        if len(data) != item.bytes:
            raise ManifestError(f"Manifest byte size mismatch for {item.path}")
        if _sha256(data) != item.sha256:
            raise ManifestError(f"Manifest SHA-256 mismatch for {item.path}")


def _validate_files_from_dir(
    root: Path,
    files: list[BundleFile],
    required_integrity: str,
    mirror_root: str,
) -> None:
    by_path = {item.path: item for item in files}
    for required in ("database/immoapp.dump", required_integrity):
        if required not in by_path:
            raise ManifestError(f"Required file missing from manifest: {required}")
    if not any(item.path.startswith(f"{mirror_root}/") for item in files):
        raise ManifestError(f"MinIO mirror root is missing or empty: {mirror_root}")
    actual_payload = _actual_dir_payload_files(root)
    _assert_exact_payload_set(actual_payload, files)
    for item in files:
        path = root / Path(*PurePosixPath(item.path).parts)
        if not path.is_file():
            raise ManifestError(f"Manifest file missing from directory: {item.path}")
        data = path.read_bytes()
        if len(data) != item.bytes:
            raise ManifestError(f"Manifest byte size mismatch for {item.path}")
        if _hash_file(path) != item.sha256:
            raise ManifestError(f"Manifest SHA-256 mismatch for {item.path}")


def verify_bundle_manifest(bundle_path: Path) -> ParsedManifest:
    bundle = bundle_path.resolve()
    if not bundle.exists():
        raise ManifestError(f"Release bundle not found: {bundle_path}")
    if bundle.is_file():
        manifest, archive = _load_manifest_from_zip(bundle)
        try:
            files = _manifest_files(manifest)
            required_integrity, mirror_root = _required_paths(manifest)
            _validate_files_from_zip(archive, files, required_integrity, mirror_root)
        finally:
            archive.close()
    elif bundle.is_dir():
        manifest = _load_manifest_from_dir(bundle)
        files = _manifest_files(manifest)
        required_integrity, mirror_root = _required_paths(manifest)
        _validate_files_from_dir(bundle, files, required_integrity, mirror_root)
    else:
        raise ManifestError(f"Release bundle path is neither file nor directory: {bundle_path}")
    object_storage = manifest["object_storage"]
    source_bucket = _safe_bucket_name(object_storage["bucket"])
    files_tuple = tuple(files)
    return ParsedManifest(
        raw=manifest,
        source_bucket=source_bucket,
        mirror_root=mirror_root,
        files=files_tuple,
        files_by_path={item.path: item for item in files_tuple},
    )


def verify_bundle(bundle_path: Path) -> dict[str, Any]:
    return verify_bundle_manifest(bundle_path).raw


def _assert_no_symlink_ancestors(path: Path) -> None:
    current = path
    while True:
        if current.exists() and current.is_symlink():
            raise ManifestError(f"Extraction target parent is a symlink: {current}")
        parent = current.parent
        if parent == current:
            break
        current = parent


def _resolve_extract_request(extract_to: Path) -> tuple[Path, bool]:
    requested = extract_to if extract_to.is_absolute() else Path.cwd() / extract_to
    _assert_no_symlink_ancestors(requested.parent)
    if requested.exists():
        if requested.is_symlink():
            raise ManifestError(f"Extraction target must not be a symlink: {extract_to}")
        if not requested.is_dir():
            raise ManifestError(f"Extraction target is not a directory: {extract_to}")
        if any(requested.iterdir()):
            raise ManifestError(f"Extraction target must be empty: {extract_to}")
        return requested.resolve(), True
    else:
        requested.parent.mkdir(parents=True, exist_ok=True)
        _assert_no_symlink_ancestors(requested.parent)
        return requested.absolute(), False


def _make_staging_root(final_root: Path) -> Path:
    parent = final_root.parent
    _assert_no_symlink_ancestors(parent)
    staging = parent / f".{final_root.name}.extracting-{uuid.uuid4().hex[:12]}"
    if staging.exists():
        raise ManifestError(f"Extraction staging target already exists: {staging}")
    staging.mkdir(parents=False, exist_ok=False)
    return staging.resolve()


def _safe_extract_target(root: Path, relative_path: str) -> Path:
    target = root / Path(*PurePosixPath(relative_path).parts)
    _assert_no_symlink_ancestors(target.parent)
    target.parent.mkdir(parents=True, exist_ok=True)
    _assert_no_symlink_ancestors(target.parent)
    resolved_parent = target.parent.resolve()
    try:
        resolved_parent.relative_to(root.resolve())
    except ValueError as exc:
        raise ManifestError(f"Extraction target escapes root: {relative_path}") from exc
    final_target = resolved_parent / target.name
    if final_target.exists():
        raise ManifestError(f"Extraction would overwrite an existing file: {relative_path}")
    return final_target


def _write_extracted_file(root: Path, relative_path: str, data: bytes) -> None:
    target = _safe_extract_target(root, relative_path)
    target.write_bytes(data)


def _copy_validated_dir(bundle: Path, extract_to: Path, files: list[BundleFile]) -> None:
    _write_extracted_file(extract_to, "manifest.json", (bundle / "manifest.json").read_bytes())
    for item in files:
        source = bundle / Path(*PurePosixPath(item.path).parts)
        target = _safe_extract_target(extract_to, item.path)
        shutil.copy2(source, target)


def _promote_staging(staging: Path, final_root: Path, final_existed_empty: bool) -> None:
    if final_existed_empty:
        empty_backup = final_root.parent / f".{final_root.name}.empty-{uuid.uuid4().hex[:12]}"
        if empty_backup.exists():
            raise ManifestError(f"Extraction empty-target backup already exists: {empty_backup}")
        final_root.rename(empty_backup)
        try:
            staging.rename(final_root)
        except Exception:
            if not final_root.exists() and empty_backup.exists():
                empty_backup.rename(final_root)
            raise
        else:
            empty_backup.rmdir()
    else:
        if final_root.exists():
            raise ManifestError(f"Extraction target appeared before promotion: {final_root}")
        staging.rename(final_root)


def safe_extract(bundle_path: Path, extract_to: Path) -> None:
    bundle = bundle_path.resolve()
    parsed = verify_bundle_manifest(bundle)
    files = list(parsed.files)
    final_root, final_existed_empty = _resolve_extract_request(extract_to)
    staging_root = _make_staging_root(final_root)
    promoted = False
    try:
        if bundle.is_file():
            with zipfile.ZipFile(bundle) as archive:
                member_map = _zip_payload_member_map(archive)
                _write_extracted_file(staging_root, "manifest.json", archive.read("manifest.json"))
                for item in files:
                    _write_extracted_file(
                        staging_root,
                        item.path,
                        archive.read(member_map[item.path]),
                    )
        else:
            _copy_validated_dir(bundle, staging_root, files)
        _promote_staging(staging_root, final_root, final_existed_empty)
        promoted = True
    finally:
        if not promoted and staging_root.exists():
            shutil.rmtree(staging_root)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify ImmoApp release backup manifest.")
    parser.add_argument("--bundle-path", type=Path, required=True)
    parser.add_argument("--extract-to", type=Path, default=None)
    args = parser.parse_args(argv)

    try:
        if args.extract_to is not None:
            safe_extract(args.bundle_path, args.extract_to)
            manifest = _load_manifest_from_dir(args.extract_to)
        else:
            manifest = verify_bundle(args.bundle_path)
    except ManifestError as exc:
        print(f"release_bundle_manifest=failed: {exc}", file=sys.stderr)
        return 1
    print("release_bundle_manifest=ok")
    print(f"kind={manifest.get('kind')}")
    print(f"bucket={(manifest.get('object_storage') or {}).get('bucket')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
