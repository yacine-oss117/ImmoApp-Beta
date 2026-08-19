"""
PDF generation actions for the contract builder.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import TYPE_CHECKING, cast

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QDateEdit, QFileDialog, QLineEdit, QMessageBox, QSpinBox, QWidget

from app.services.agency_settings_repository import (
    generate_contract_serial,
    get_agency_logo_path,
    get_agency_name,
)
from app.utils.i18n import tr_factory
from app.views.dialogs.contract_builder_article import ArticleWidget

logger = logging.getLogger(__name__)
_TR = tr_factory("ContractBuilderDialog")

if TYPE_CHECKING:
    from app.models import Client, Listing


class ContractBuilderPdfMixin:
    """Behavior mixin for preview and final PDF generation."""

    _articles: list[ArticleWidget]
    _owner_name: QLineEdit
    _tenant_name: QLineEdit
    _start_date: QDateEdit
    _end_date: QDateEdit
    _monthly_rent: QSpinBox
    _deposit: QSpinBox
    _client: Client | None
    _listing: Listing | None

    if TYPE_CHECKING:

        def _get_articles_data(self) -> list[dict[str, object]]: ...
        def accept(self) -> None: ...

    def _preview_pdf(self) -> None:
        """Generate and open a preview PDF asynchronously."""
        parent = cast(QWidget, self)
        if not self._articles:
            QMessageBox.warning(
                parent, _TR("Erreur"), _TR("Veuillez d'abord ajouter des articles.")
            )
            return

        try:
            serial = generate_contract_serial()

            contract_data = {
                "serial_number": serial,
                "date": datetime.now().strftime("%d/%m/%Y"),
            }

            articles = self._get_articles_data()

            signatures = {
                "agency": {"name": get_agency_name()},
                "owner": {"name": self._owner_name.text() or "________"},
                "tenant": {"name": self._tenant_name.text() or "________"},
            }

            import tempfile

            output_path = os.path.join(
                tempfile.gettempdir(),
                f"contract_preview_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf",
            )

            from app.workers.pdf_worker import generate_pdf_async

            def on_finished(pdf_path: str) -> None:
                if not QDesktopServices.openUrl(QUrl.fromLocalFile(pdf_path)):
                    QMessageBox.warning(
                        parent,
                        _TR("Erreur"),
                        _TR("Impossible d'ouvrir le PDF."),
                    )

            def on_error(msg: str) -> None:
                QMessageBox.critical(
                    parent,
                    _TR("Erreur"),
                    _TR("Echec de la generation: {error}").format(error=msg),
                )

            generate_pdf_async(
                contract_data=contract_data,
                articles=articles,
                signatures=signatures,
                output_path=output_path,
                on_finished=on_finished,
                on_error=on_error,
                agency_logo_path=get_agency_logo_path(),
                agency_name=get_agency_name(),
                encrypt=False,
            )

        except (OSError, RuntimeError, ValueError) as exc:
            logger.error("PDF preview generation failed", exc_info=True)
            QMessageBox.critical(
                parent,
                _TR("Erreur"),
                _TR("Echec de la generation: {error}").format(error=exc),
            )

    def _generate_pdf(self) -> None:
        """Generate and save the final PDF asynchronously."""
        parent = cast(QWidget, self)
        if not self._articles:
            QMessageBox.warning(
                parent, _TR("Erreur"), _TR("Veuillez d'abord ajouter des articles.")
            )
            return

        if not self._owner_name.text() or not self._tenant_name.text():
            QMessageBox.warning(
                parent,
                _TR("Erreur"),
                _TR("Les noms du bailleur et du locataire sont requis."),
            )
            return

        serial = generate_contract_serial()
        default_name = f"Contrat_{serial}_{datetime.now().strftime('%Y%m%d')}.pdf"

        file_path, _ = QFileDialog.getSaveFileName(
            parent,
            _TR("Enregistrer le contrat"),
            default_name,
            _TR("PDF Files (*.pdf)"),
        )

        if not file_path:
            return

        contract_data = {
            "serial_number": serial,
            "date": datetime.now().strftime("%d/%m/%Y"),
        }

        articles = self._get_articles_data()

        signatures = {
            "agency": {"name": get_agency_name()},
            "owner": {"name": self._owner_name.text()},
            "tenant": {"name": self._tenant_name.text()},
        }

        s_date = self._start_date.date().toString("yyyy-MM-dd")
        e_date = self._end_date.date().toString("yyyy-MM-dd")
        client_id = self._client.id if self._client else 0
        listing_id = self._listing.id if self._listing else 0
        monthly_rent = self._monthly_rent.value()
        deposit = self._deposit.value()

        from app.workers.pdf_worker import generate_pdf_async

        def on_finished(pdf_path: str) -> None:
            try:
                from app.services.crm_repository import create_contract

                if client_id and listing_id:
                    create_contract(
                        {
                            "client_id": client_id,
                            "listing_id": listing_id,
                            "contract_type": "rent",
                            "start_date": s_date,
                            "end_date": e_date,
                            "amount": monthly_rent,
                            "deposit": deposit,
                            "terms": f"Serial: {serial}",
                            "notes": f"PDF: {pdf_path}",
                        }
                    )
            except Exception as db_err:
                logger.error("Contract DB save failed", exc_info=True)
                QMessageBox.warning(
                    parent,
                    _TR("Avertissement"),
                    _TR("Contrat genere mais sauvegarde DB impossible: {error}").format(
                        error=db_err
                    ),
                )

            QMessageBox.information(
                parent,
                _TR("Succes"),
                _TR(
                    "Contrat genere avec succes!\n\nNumero: {serial}\nFichier: {path}\n\n"
                    "Contrat enregistre (Brouillon)\n"
                    "Allez dans CRM > Contrats pour le marquer comme signe"
                ).format(serial=serial, path=pdf_path),
            )

            self.accept()

        def on_error(msg: str) -> None:
            QMessageBox.critical(
                parent,
                _TR("Erreur"),
                _TR("Echec de la generation: {error}").format(error=msg),
            )

        generate_pdf_async(
            contract_data=contract_data,
            articles=articles,
            signatures=signatures,
            output_path=file_path,
            on_finished=on_finished,
            on_error=on_error,
            agency_logo_path=get_agency_logo_path(),
            agency_name=get_agency_name(),
            encrypt=True,
        )
