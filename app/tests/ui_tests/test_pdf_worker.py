"""Tests for PDFWorker."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.utils import pdf_generator
from app.workers.pdf_worker import PDFWorker

pytestmark = pytest.mark.ui


def test_pdf_worker_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, qapp) -> None:
    assert qapp is not None
    output_path = tmp_path / "contract.pdf"

    def fake_generate_contract_pdf(
        contract_data: dict[str, object],
        articles: list[dict[str, object]],
        signatures: dict[str, dict[str, object]],
        output_path: str,
        agency_logo_path: str | None = None,
        agency_name: str = "",
        encrypt: bool = True,
        password: str = "",
    ) -> str:
        Path(output_path).write_text("pdf")
        return output_path

    monkeypatch.setattr(pdf_generator, "generate_contract_pdf", fake_generate_contract_pdf)

    worker = PDFWorker(
        contract_data={"serial_number": "S1"},
        articles=[],
        signatures={"agency": {}, "owner": {}, "tenant": {}},
        output_path=str(output_path),
    )

    finished: list[str] = []
    errors: list[str] = []
    progress: list[int] = []

    worker.signals.finished.connect(finished.append)
    worker.signals.error.connect(errors.append)
    worker.signals.progress.connect(progress.append)

    worker.run()

    assert finished == [str(output_path)]
    assert errors == []
    assert progress[0] == 10
    assert progress[-1] == 100
