"""
CRUD actions and form management for ClientsTabV2.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, cast

from PySide6.QtWidgets import QDialog, QMessageBox, QPushButton, QVBoxLayout, QWidget

from app.models import Client, Demande
from app.services.client_repository import (
    delete_client,
    get_client_by_id,
    upsert_client,
)
from app.services.demande_repository import (
    create_demande,
    delete_demande,
    get_demande_by_id,
    get_demandes_for_client,
    update_demande,
)
from app.utils.i18n import tr_factory
from app.utils.time import utc_now_iso
from app.widgets.demande_panel import DemandePanel

_TR = tr_factory("ClientsTabV2")
logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from app.views.clients_v2_ui import ClientFormWidgets
    from app.widgets.collapsible_section import CollapsibleSection


class ClientsTabActionsMixin:
    """Behavior mixin for CRUD actions and form updates."""

    _client_section: CollapsibleSection
    _form: ClientFormWidgets
    _demande_panels: list[DemandePanel]
    _demandes_layout: QVBoxLayout
    save_btn: QPushButton
    editing_id: int | None
    editing_row_version: int | None
    editing_created_at: str
    editing_created_loc: str
    refresh_match_counts_cb: Callable[[], None] | None

    if TYPE_CHECKING:

        def refresh_table(self, force_reload: bool = True) -> None: ...
        def _get_cached_location(self) -> str: ...
        def _remove_demande_panel(self, panel: DemandePanel) -> None: ...
        def _add_demande_panel(self, data: Demande | None = None) -> DemandePanel | None: ...
        def _sync_demande_summary_state(self) -> None: ...

    def _show_auth_required_warning(self) -> None:
        dialog = QMessageBox(
            QMessageBox.Icon.Warning,
            _TR("Session needs attention"),
            _TR(
                "Your session or permissions changed while this page was open. "
                "Sign in again and try again."
            ),
            QMessageBox.StandardButton.Ok,
            cast(QWidget, self),
        )
        dialog.setObjectName("clientsAuthRequiredMessageBox")
        dialog.setAccessibleName(_TR("Session needs attention"))
        dialog.exec()

    def _get_client_for_edit(self, client_id: int) -> Client | None:
        return get_client_by_id(client_id)

    def _load_client_for_edit(self, client: Client) -> None:
        """Load client data into form for editing."""
        self.editing_id = client.id
        self.editing_row_version = client.row_version
        self.editing_created_at = client.created_at
        self.editing_created_loc = client.created_loc
        self._client_section.set_title(_TR("Edit Client #{id}").format(id=client.id))
        self._form.family_name.setText(client.family_name or "")
        self._form.phone.setText(client.phone or "")
        self._form.is_vip.setChecked(client.is_vip or False)

        for panel in self._demande_panels[:]:
            self._demandes_layout.removeWidget(panel)
            panel.deleteLater()
        self._demande_panels.clear()

        demandes = get_demandes_for_client(client.id)
        for dem in demandes:
            self._add_demande_panel(dem)
        self._sync_demande_summary_state()

        self._client_section.set_collapsed(False)
        self.save_btn.setText(_TR("Update Client"))

    def _edit_demande(self, demande_id: int, _client_id: int) -> None:
        """Edit a specific demande using the new V2 dialog with Wilaya/Location."""
        demande = get_demande_by_id(demande_id)
        if not demande:
            QMessageBox.warning(
                cast(QWidget, self),
                _TR("Error"),
                _TR("Request #{id} not found.").format(id=demande_id),
            )
            return

        from app.widgets.demande_edit_dialog_v2 import DemandeEditDialogV2

        dialog = DemandeEditDialogV2(demande, parent=cast(QWidget, self))
        if dialog.exec() == QDialog.DialogCode.Accepted:
            data = dialog.get_data()
            try:
                update_demande(demande_id, data)
            except ValueError as exc:
                QMessageBox.warning(cast(QWidget, self), _TR("Validation Error"), str(exc))
                return
            self.refresh_table()

    def _delete_client(self, client_id: int) -> None:
        """Delete a client."""
        client = get_client_by_id(client_id)
        display_name = (
            client.family_name or client.phone or _TR("this client")
            if client
            else _TR("this client")
        )

        if (
            QMessageBox.question(
                cast(QWidget, self),
                _TR("Confirm"),
                _TR("Delete {name}?").format(name=display_name),
            )
            == QMessageBox.StandardButton.Yes
        ):
            delete_client(client_id)
            self.refresh_table()
            if self.editing_id == client_id:
                self.clear_form()
            if self.refresh_match_counts_cb:
                self.refresh_match_counts_cb()

    def _delete_demande_row(self, demande_id: int, _client_id: int) -> None:
        """Delete a demande from tree."""
        if (
            QMessageBox.question(cast(QWidget, self), _TR("Confirm"), _TR("Delete this request?"))
            == QMessageBox.StandardButton.Yes
        ):
            delete_demande(demande_id)
            self.refresh_table()

    def save_client(self) -> None:
        """Validate and persist the current client and all its demande panels to the database."""
        if bool(getattr(self, "_saving_client", False)):
            logger.warning("Ignoring re-entrant client save request")
            return
        self._saving_client = True
        save_btn = getattr(self, "save_btn", None)
        if save_btn is not None:
            save_btn.setEnabled(False)
        try:
            self._save_client_once()
        finally:
            if save_btn is not None:
                save_btn.setEnabled(True)
            self._saving_client = False

    def _save_client_once(self) -> None:
        """Persist the current client and demande panels once."""
        phone = self._form.phone.text().strip()

        d = {
            "family_name": self._form.family_name.text().strip(),
            "phone": phone,
            "remarks": "",
            "tags": "",
            "is_vip": 1 if self._form.is_vip.isChecked() else 0,
            "updated_at": utc_now_iso(),
        }

        if self.editing_id is not None:
            d["id"] = self.editing_id
            if self.editing_row_version is not None:
                d["row_version"] = self.editing_row_version
            d["created_at"] = self.editing_created_at or utc_now_iso()
            d["created_loc"] = self.editing_created_loc or self._get_cached_location()
        else:
            d["created_at"] = utc_now_iso()
            d["created_loc"] = self._get_cached_location()

        try:
            client_id = upsert_client(d)
        except PermissionError:
            self._show_auth_required_warning()
            return
        except ValueError as exc:
            QMessageBox.warning(cast(QWidget, self), _TR("Validation Error"), str(exc))
            return

        panels_to_save: list[DemandePanel] = []
        seen_panels: set[int] = set()
        for panel in self._demande_panels:
            panel_key = id(panel)
            if panel_key in seen_panels:
                logger.warning("Skipping duplicate demande panel during client save")
                continue
            seen_panels.add(panel_key)
            panels_to_save.append(panel)

        saved_demande_ids: set[int] = set()
        for panel in panels_to_save:
            data = panel.get_data()
            current_demande_id = panel.demande_id
            if current_demande_id > 0 and current_demande_id in saved_demande_ids:
                logger.warning(
                    "Skipping duplicate persisted demande during client save demande_id=%s",
                    current_demande_id,
                )
                continue
            try:
                if current_demande_id > 0:
                    if not panel.is_dirty():
                        saved_demande_ids.add(current_demande_id)
                        continue
                    update_demande(current_demande_id, data)
                    saved_demande_ids.add(current_demande_id)
                    panel.mark_saved()
                else:
                    new_id = create_demande(client_id, data)
                    panel.set_demande_id(new_id)
                    saved_demande_ids.add(new_id)
                    panel.mark_saved(row_version=1)
            except PermissionError:
                self._show_auth_required_warning()
                return
            except ValueError as exc:
                logger.warning(
                    "Client demande save failed client_id=%s demande_id=%s payload=%s",
                    client_id,
                    current_demande_id if current_demande_id > 0 else None,
                    data,
                    exc_info=True,
                )
                QMessageBox.warning(cast(QWidget, self), _TR("Validation Error"), str(exc))
                return

        saved_demande_count = len(panels_to_save)
        self.refresh_table()
        display_name = (
            self._form.family_name.text().strip()
            or self._form.phone.text().strip()
            or _TR("Client")
        )
        self.clear_form()
        if self.refresh_match_counts_cb:
            self.refresh_match_counts_cb()
        QMessageBox.information(
            cast(QWidget, self),
            _TR("Success"),
            _TR("{name} saved with {count} request(s).").format(
                name=display_name, count=saved_demande_count
            ),
        )

    def clear_form(self) -> None:
        """Clear the form."""
        self._form.family_name.clear()
        self._form.phone.clear()
        self._form.is_vip.setChecked(False)

        for panel in self._demande_panels[:]:
            self._demandes_layout.removeWidget(panel)
            panel.deleteLater()
        self._demande_panels.clear()
        self._sync_demande_summary_state()

        self.editing_id = None
        self.editing_row_version = None
        self.editing_created_at = ""
        self.editing_created_loc = ""
        self.save_btn.setText(_TR("Save Client"))
        self._client_section.set_title(_TR("Add Client"))
