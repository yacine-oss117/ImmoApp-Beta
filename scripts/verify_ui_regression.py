from __future__ import annotations

import argparse
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtGui import QImage

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class DiffResult:
    rel_path: str
    ratio: float


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify UI screenshot regressions.")
    parser.add_argument(
        "--capture-dir",
        type=Path,
        default=ROOT / "artifacts" / "ui_capture",
        help="Directory with captured screenshots.",
    )
    parser.add_argument(
        "--baseline-dir",
        type=Path,
        default=ROOT / "app" / "tests" / "ui_visual" / "baseline",
        help="Directory with approved screenshot baselines.",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.01,
        help="Max per-image changed-pixel ratio before failure.",
    )
    parser.add_argument(
        "--update-baseline",
        action="store_true",
        help="Replace baseline images with current capture output.",
    )
    parser.add_argument(
        "--require-baseline",
        action="store_true",
        help="Fail when baseline files are missing.",
    )
    return parser.parse_args()


def _iter_pngs(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*.png") if path.is_file())


def _image_bytes(image: QImage) -> bytes:
    if image.isNull():
        return b""
    rgba = image.convertToFormat(QImage.Format.Format_RGBA8888)
    size = rgba.sizeInBytes()
    bits = rgba.constBits()
    try:
        bits.setsize(size)
    except AttributeError:
        pass
    data = bytes(bits)
    if len(data) >= size:
        return data[:size]
    return memoryview(bits)[:size].tobytes()


def _pixel_diff_ratio(current: Path, baseline: Path) -> float:
    lhs = QImage(str(current))
    rhs = QImage(str(baseline))
    if lhs.isNull() or rhs.isNull():
        return 1.0
    if lhs.size() != rhs.size():
        return 1.0

    lhs_bytes = _image_bytes(lhs)
    rhs_bytes = _image_bytes(rhs)
    if len(lhs_bytes) != len(rhs_bytes):
        return 1.0
    if lhs_bytes == rhs_bytes:
        return 0.0

    changed = 0
    total = len(lhs_bytes) // 4
    for index in range(0, len(lhs_bytes), 4):
        if lhs_bytes[index : index + 4] != rhs_bytes[index : index + 4]:
            changed += 1
    if total <= 0:
        return 1.0
    return changed / float(total)


def _update_baseline(capture_dir: Path, baseline_dir: Path) -> None:
    if baseline_dir.exists():
        shutil.rmtree(baseline_dir)
    shutil.copytree(capture_dir, baseline_dir)
    print(f"[ui-regression] baseline updated: {baseline_dir}")


def main() -> int:
    args = _parse_args()
    capture_dir: Path = args.capture_dir
    baseline_dir: Path = args.baseline_dir

    if not capture_dir.exists():
        print(f"[ui-regression] capture dir missing: {capture_dir}", file=sys.stderr)
        return 1

    if args.update_baseline:
        _update_baseline(capture_dir, baseline_dir)
        return 0

    captures = _iter_pngs(capture_dir)
    if not captures:
        print(f"[ui-regression] no PNG files found under {capture_dir}", file=sys.stderr)
        return 1

    failures: list[DiffResult] = []
    missing: list[str] = []

    for current in captures:
        rel = current.relative_to(capture_dir)
        baseline = baseline_dir / rel
        if not baseline.exists():
            missing.append(str(rel))
            continue
        ratio = _pixel_diff_ratio(current, baseline)
        if ratio > args.threshold:
            failures.append(DiffResult(rel_path=str(rel), ratio=ratio))

    if missing:
        print("[ui-regression] missing baseline files:")
        for rel in missing:
            print(f"  - {rel}")
        if args.require_baseline:
            return 1

    if failures:
        print(f"[ui-regression] {len(failures)} regression(s) above threshold {args.threshold:.4f}")
        for failure in failures:
            print(f"  - {failure.rel_path}: diff={failure.ratio:.4%}")
        return 1

    print("[ui-regression] PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
