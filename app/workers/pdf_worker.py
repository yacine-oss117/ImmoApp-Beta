"""
PDF Worker - Async PDF generation to prevent UI freeze.

Generates contract PDFs in a background thread so the UI
remains responsive during the guilloche pattern rendering,
encryption, and other heavy operations.

Usage:
    from app.workers.pdf_worker import PDFWorker
    from PySide6.QtCore import QThreadPool

    worker = PDFWorker(contract_data, articles, signatures, output_path)
    worker.signals.finished.connect(lambda path: open_pdf(path))
    worker.signals.error.connect(lambda msg: show_error(msg))
    QThreadPool.globalInstance().start(worker)
"""

import logging
from collections.abc import Callable, Mapping, Sequence

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

logger = logging.getLogger(__name__)


class PDFSignals(QObject):
    """Signals for PDFWorker communication."""

    # Emits path to generated PDF on success
    finished = Signal(str)

    # Emits error message if generation fails
    error = Signal(str)

    # Emits progress percentage (0-100)
    progress = Signal(int)


class PDFWorker(QRunnable):
    """
    Background worker for PDF generation.

    Runs PDF generation in background thread so UI remains responsive
    during heavy operations like guilloche pattern rendering.

    Performance: Prevents UI freeze during PDF generation.
    """

    def __init__(
        self,
        contract_data: Mapping[str, object],
        articles: Sequence[Mapping[str, object]],
        signatures: Mapping[str, Mapping[str, object]],
        output_path: str,
        agency_logo_path: str | None = None,
        agency_name: str = "",
        encrypt: bool = True,
        password: str = "",
    ) -> None:
        super().__init__()
        self.signals = PDFSignals()

        self._contract_data = dict(contract_data)
        self._articles = [dict(article) for article in articles]
        self._signatures = {k: dict(v) for k, v in signatures.items()}
        self._output_path = output_path
        self._agency_logo_path = agency_logo_path
        self._agency_name = agency_name
        self._encrypt = encrypt
        self._password = password

    @Slot()
    def run(self) -> None:
        """Execute PDF generation in background thread."""
        try:
            self.signals.progress.emit(10)

            from app.utils.pdf_generator import generate_contract_pdf

            self.signals.progress.emit(30)

            path = generate_contract_pdf(
                contract_data=self._contract_data,
                articles=self._articles,
                signatures=self._signatures,
                output_path=self._output_path,
                agency_logo_path=self._agency_logo_path,
                agency_name=self._agency_name,
                encrypt=self._encrypt,
                password=self._password,
            )

            self.signals.progress.emit(100)
            self.signals.finished.emit(path)

            logger.info(f"PDF generated successfully: {path}")

        except (OSError, RuntimeError, ValueError) as exc:
            logger.error("PDF generation failed", exc_info=True)
            self.signals.error.emit(str(exc))


def generate_pdf_async(
    contract_data: Mapping[str, object],
    articles: Sequence[Mapping[str, object]],
    signatures: Mapping[str, Mapping[str, object]],
    output_path: str,
    on_finished: Callable[[str], None] | None = None,
    on_error: Callable[[str], None] | None = None,
    agency_logo_path: str | None = None,
    agency_name: str = "",
    encrypt: bool = True,
    password: str = "",
) -> PDFWorker:
    """
    Convenience function to generate PDF asynchronously.

    Args:
        contract_data: Contract information dict
        articles: List of articles with title/content
        signatures: Dict with agency/owner/tenant signatures
        output_path: Where to save the PDF
        on_finished: Callback(path) when done
        on_error: Callback(error_msg) on failure
        **kwargs: Additional args for PDFWorker

    Returns:
        The PDFWorker instance (already started)
    """
    worker = PDFWorker(
        contract_data=contract_data,
        articles=articles,
        signatures=signatures,
        output_path=output_path,
        agency_logo_path=agency_logo_path,
        agency_name=agency_name,
        encrypt=encrypt,
        password=password,
    )

    if on_finished:
        worker.signals.finished.connect(on_finished)
    if on_error:
        worker.signals.error.connect(on_error)

    QThreadPool.globalInstance().start(worker)

    return worker
