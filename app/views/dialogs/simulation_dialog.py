"""Dialog for controlling simulation mode."""

from __future__ import annotations

import logging

from PySide6.QtWidgets import QDialog, QLabel, QMessageBox, QPushButton, QSpinBox, QWidget

from app.services.simulation_service import (
    is_simulation_active,
    set_simulation_active,
    simulation_delete,
    simulation_save,
    simulation_start,
    simulation_status,
)
from app.utils.i18n import tr_factory
from app.views.dialogs.simulation_dialog_ui import setup_simulation_dialog_ui
from app.workers.simulation_worker import run_simulation_async

logger = logging.getLogger(__name__)
_TR = tr_factory("SimulationDialog")


class SimulationDialog(QDialog):
    """Dialog for simulation schema management."""

    _status_banner: QLabel
    _status_text: QLabel
    _counts_text: QLabel
    _client_count: QSpinBox
    _listing_count: QSpinBox
    _demandes_per_client: QSpinBox
    _offers_per_listing: QSpinBox
    _start_seed_btn: QPushButton
    _start_clone_btn: QPushButton
    _save_btn: QPushButton
    _delete_btn: QPushButton
    _close_btn: QPushButton

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        setup_simulation_dialog_ui(self)
        self._connect_actions()
        self._refresh_status()

    def _connect_actions(self) -> None:
        self._start_seed_btn.clicked.connect(self._start_seed)
        self._start_clone_btn.clicked.connect(self._start_clone)
        self._save_btn.clicked.connect(self._save_simulation)
        self._delete_btn.clicked.connect(self._delete_simulation)
        self._close_btn.clicked.connect(self.reject)

    def _refresh_status(self) -> None:
        run_simulation_async(
            simulation_status,
            on_finished=self._on_status_loaded,
            on_error=self._on_status_error,
        )

    def _on_status_loaded(self, payload: object) -> None:
        status: dict[str, object] = payload if isinstance(payload, dict) else {}
        exists = bool(status.get("exists"))
        counts_raw = status.get("counts")
        counts: dict[str, object] = counts_raw if isinstance(counts_raw, dict) else {}
        if exists:
            self._status_banner.setText(_TR("SIMULATION ACTIVE"))
            self._set_banner_state("success")
            self._status_text.setText(_TR("Simulation data is active."))
            self._counts_text.setText(
                _TR("Counts: clients={c}, listings={l}, demandes={d}, offers={o}").format(
                    c=counts.get("clients", 0),
                    l=counts.get("listings", 0),
                    d=counts.get("demandes", 0),
                    o=counts.get("offers", 0),
                )
            )
        else:
            self._status_banner.setText(_TR("No simulation active"))
            self._set_banner_state("muted")
            self._status_text.setText(_TR("Ready for simulation."))
            self._counts_text.setText(_TR("Counts: -"))
        self._update_buttons(exists)

    def _on_status_error(self, message: str) -> None:
        logger.error("Simulation status failed: %s", message)
        self._set_banner_state("error")
        QMessageBox.critical(self, _TR("Error"), _TR("Failed to load simulation status."))

    def _update_buttons(self, sim_exists: bool) -> None:
        self._start_seed_btn.setEnabled(True)
        self._start_clone_btn.setEnabled(True)
        self._save_btn.setEnabled(sim_exists)
        self._delete_btn.setEnabled(sim_exists)
        if sim_exists and not is_simulation_active():
            set_simulation_active(True)
        if not sim_exists and is_simulation_active():
            set_simulation_active(False)

    def _start_seed(self) -> None:
        self._set_busy(True)

        def _operation() -> dict[str, object]:
            return simulation_start(
                mode="seed",
                client_count=self._client_count.value(),
                listing_count=self._listing_count.value(),
                demandes_per_client=self._demandes_per_client.value(),
                offers_per_listing=self._offers_per_listing.value(),
            )

        run_simulation_async(
            _operation, on_finished=self._on_start_done, on_error=self._on_start_error
        )

    def _start_clone(self) -> None:
        if not self._confirm(
            _TR("Clone will copy all real data into the simulation schema. Continue?")
        ):
            return
        self._set_busy(True)
        run_simulation_async(
            lambda: simulation_start(mode="clone"),
            on_finished=self._on_start_done,
            on_error=self._on_start_error,
        )

    def _on_start_done(self, _payload: object) -> None:
        set_simulation_active(True)
        self._set_busy(False)
        QMessageBox.information(self, _TR("Success"), _TR("Simulation ready."))
        self._refresh_status()

    def _on_start_error(self, message: str) -> None:
        self._set_busy(False)
        logger.error("Simulation start failed: %s", message)
        QMessageBox.critical(self, _TR("Error"), _TR("Failed to create simulation data."))

    def _save_simulation(self) -> None:
        if not self._confirm(
            _TR(
                "This will PERMANENTLY OVERWRITE your real database with simulation data! "
                "Continue?"
            )
        ):
            return
        self._set_busy(True)
        run_simulation_async(
            simulation_save, on_finished=self._on_save_done, on_error=self._on_save_error
        )

    def _on_save_done(self, _payload: object) -> None:
        set_simulation_active(False)
        self._set_busy(False)
        QMessageBox.information(self, _TR("Success"), _TR("Simulation saved to real data."))
        self._refresh_status()

    def _on_save_error(self, message: str) -> None:
        self._set_busy(False)
        logger.error("Simulation save failed: %s", message)
        QMessageBox.critical(self, _TR("Error"), _TR("Failed to save simulation."))

    def _delete_simulation(self) -> None:
        if not self._confirm(_TR("Delete simulation data and restore real database?")):
            return
        self._set_busy(True)
        run_simulation_async(
            simulation_delete, on_finished=self._on_delete_done, on_error=self._on_delete_error
        )

    def _on_delete_done(self, _payload: object) -> None:
        set_simulation_active(False)
        self._set_busy(False)
        QMessageBox.information(self, _TR("Success"), _TR("Simulation deleted."))
        self._refresh_status()

    def _on_delete_error(self, message: str) -> None:
        self._set_busy(False)
        logger.error("Simulation delete failed: %s", message)
        QMessageBox.critical(self, _TR("Error"), _TR("Failed to delete simulation."))

    def _set_busy(self, busy: bool) -> None:
        self._start_seed_btn.setEnabled(not busy)
        self._start_clone_btn.setEnabled(not busy)
        self._save_btn.setEnabled(not busy)
        self._delete_btn.setEnabled(not busy)
        self._close_btn.setEnabled(not busy)
        if busy:
            self._status_text.setText(_TR("Working..."))

    def _confirm(self, message: str) -> bool:
        result = QMessageBox.question(
            self,
            _TR("Confirm"),
            message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        return bool(result == QMessageBox.StandardButton.Yes)

    def _set_banner_state(self, state: str) -> None:
        self._status_banner.setProperty("immoState", state)
        style = self._status_banner.style()
        style.unpolish(self._status_banner)
        style.polish(self._status_banner)
        self._status_banner.update()
