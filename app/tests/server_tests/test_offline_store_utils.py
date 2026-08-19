from __future__ import annotations

from pathlib import Path

from app.services.offline_store_utils import write_json_atomic


def test_write_json_atomic_retries_transient_permission_error(
    monkeypatch,
    tmp_path: Path,
) -> None:
    target = tmp_path / "meta.json"
    attempts = {"count": 0}
    original_replace = Path.replace

    def _flaky_replace(self: Path, target_path: Path | str):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise PermissionError("locked")
        return original_replace(self, target_path)

    monkeypatch.setattr(Path, "replace", _flaky_replace)

    write_json_atomic(target, {"ok": True})

    assert attempts["count"] == 2
    assert target.read_text(encoding="utf-8").strip()
