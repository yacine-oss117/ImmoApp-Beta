"""
CRUD actions and form management for ListingsTabV2.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, cast

from PySide6.QtWidgets import QDialog, QMessageBox, QPushButton, QWidget

from app.services.listing_repository import (
    delete_listing,
    get_listing_by_id,
    upsert_listing,
)
from app.services.offer_repository import (
    create_offer,
    delete_offer,
    get_offer_by_id,
    get_offers_for_listing,
    update_offer,
)
from app.utils.i18n import tr_factory
from app.utils.time import utc_now_iso

_TR = tr_factory("ListingsTabV2")
logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from app.views.listings_v2_ui import ListingFormWidgets
    from app.widgets.collapsible_section import CollapsibleSection
    from app.widgets.offer_panel import OfferPanel
    from core.models import Offer


class ListingsTabActionsMixin:
    """Behavior mixin for CRUD actions and form updates."""

    _listing_section: CollapsibleSection
    _offers_container: QWidget
    _form: ListingFormWidgets
    _offer_panels: list[OfferPanel]
    save_btn: QPushButton
    editing_id: int | None
    editing_row_version: int | None
    refresh_match_counts_cb: Callable[[], None] | None

    if TYPE_CHECKING:

        def refresh_table(self, force_reload: bool = True) -> None: ...
        def _add_offer_panel(
            self, data: Offer | Mapping[str, object] | None = None
        ) -> OfferPanel: ...
        def _remove_offer_panel(
            self, panel: OfferPanel, *, delete_persisted: bool = True
        ) -> None: ...

    def _edit_listing(self, listing_id: int) -> None:
        """Load listing into form for editing."""
        listing = get_listing_by_id(listing_id)
        if not listing:
            return

        self._listing_section.expand()
        self._offers_container.setVisible(True)

        self.editing_id = listing_id
        self.editing_row_version = listing.row_version
        self._form.owner_name.setText(listing.family_name or "")
        self._form.phone.setText(listing.phone or "")
        self._form.is_vip.setCurrentIndex(1 if listing.is_vip else 0)
        self._form.remarks.setText(listing.remarks or "")

        for panel in self._offer_panels[:]:
            self._remove_offer_panel(panel, delete_persisted=False)

        offers = get_offers_for_listing(listing_id)
        for offer in offers:
            self._add_offer_panel(offer)

        self._listing_section.set_title(_TR("Edit Listing #{id}").format(id=listing_id))

    def _delete_listing(self, listing_id: int) -> None:
        """Delete a listing."""
        reply = QMessageBox.question(
            cast(QWidget, self),
            _TR("Confirm Delete"),
            _TR("Delete listing #{id} and all its offers?").format(id=listing_id),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            delete_listing(listing_id)
            self.refresh_table()
            if self.refresh_match_counts_cb:
                self.refresh_match_counts_cb()

    def _edit_offer_dialog(self, _listing_id: int, offer_id: int) -> None:
        """Open dialog to edit a specific offer."""
        offer = get_offer_by_id(offer_id)
        if not offer:
            QMessageBox.warning(
                cast(QWidget, self),
                _TR("Error"),
                _TR("Offer #{id} not found.").format(id=offer_id),
            )
            return

        from app.widgets.offer_edit_dialog import OfferEditDialog

        dialog = OfferEditDialog(offer, parent=cast(QWidget, self))
        if dialog.exec() == QDialog.DialogCode.Accepted:
            data = dialog.get_data()
            try:
                update_offer(offer_id, data)
            except ValueError as exc:
                QMessageBox.warning(cast(QWidget, self), _TR("Validation Error"), str(exc))
                return
            self.refresh_table()
            if self.refresh_match_counts_cb:
                self.refresh_match_counts_cb()

    def _delete_offer(self, _listing_id: int, offer_id: int) -> None:
        """Delete a specific offer."""
        reply = QMessageBox.question(
            cast(QWidget, self),
            _TR("Confirm Delete"),
            _TR("Delete this offer?"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            delete_offer(offer_id)
            self.refresh_table()
            if self.refresh_match_counts_cb:
                self.refresh_match_counts_cb()

    def save_listing(self) -> None:
        """Save the listing and all its offers."""
        if bool(getattr(self, "_saving_listing", False)):
            logger.warning("Ignoring re-entrant listing save request")
            return
        self._saving_listing = True
        self.save_btn.setEnabled(False)
        try:
            self._save_listing_once()
        finally:
            self.save_btn.setEnabled(True)
            self._saving_listing = False

    def _save_listing_once(self) -> None:
        """Persist the current listing and offer panels once."""
        owner_name = self._form.owner_name.text().strip()
        phone = self._form.phone.text().strip()

        now = utc_now_iso()

        listing_data = {
            "id": self.editing_id,
            "family_name": owner_name,
            "phone": phone,
            "is_vip": 1 if self._form.is_vip.currentIndex() == 1 else 0,
            "remarks": self._form.remarks.text().strip(),
            "created_at": now if not self.editing_id else "",
            "updated_at": now,
        }
        if self.editing_id is not None and self.editing_row_version is not None:
            listing_data["row_version"] = self.editing_row_version

        try:
            listing_id = upsert_listing(listing_data)
        except ValueError as exc:
            QMessageBox.warning(cast(QWidget, self), _TR("Validation Error"), str(exc))
            return

        panels_to_save: list[OfferPanel] = []
        seen_panels: set[int] = set()
        for panel in self._offer_panels:
            panel_key = id(panel)
            if panel_key in seen_panels:
                logger.warning("Skipping duplicate offer panel during listing save")
                continue
            seen_panels.add(panel_key)
            panels_to_save.append(panel)

        saved_offer_ids: set[int] = set()
        for panel in panels_to_save:
            offer_data = panel.get_data()
            offer_id_obj = offer_data.pop("id", None)
            offer_id = offer_id_obj if isinstance(offer_id_obj, int) and offer_id_obj > 0 else None
            if offer_id is not None and offer_id in saved_offer_ids:
                logger.warning(
                    "Skipping duplicate persisted offer during listing save offer_id=%s",
                    offer_id,
                )
                continue
            offer_data["listing_id"] = listing_id
            try:
                if offer_id is not None:
                    if not panel.is_dirty():
                        saved_offer_ids.add(offer_id)
                        continue
                    update_offer(offer_id, offer_data)
                    saved_offer_ids.add(offer_id)
                    panel.mark_saved()
                else:
                    new_offer_id = create_offer(listing_id, offer_data)
                    saved_offer_ids.add(new_offer_id)
                    panel.mark_saved(row_version=1)
            except ValueError as exc:
                logger.warning(
                    "Listing offer save failed listing_id=%s offer_id=%s payload=%s",
                    listing_id,
                    offer_id,
                    offer_data,
                    exc_info=True,
                )
                QMessageBox.warning(cast(QWidget, self), _TR("Validation Error"), str(exc))
                return
            if offer_id is None:
                try:
                    panel.set_offer_id(new_offer_id)
                except (RuntimeError, ValueError):
                    logger.warning(
                        "Offer panel refresh failed after offer create listing_id=%s offer_id=%s",
                        listing_id,
                        new_offer_id,
                        exc_info=True,
                    )

        saved_offer_count = len(panels_to_save)
        self.clear_form()
        self.refresh_table()

        if self.refresh_match_counts_cb:
            self.refresh_match_counts_cb()

        display_name = owner_name or phone or _TR("Property")
        QMessageBox.information(
            cast(QWidget, self),
            _TR("Success"),
            _TR("{name} saved with {count} offer(s).").format(
                name=display_name,
                count=saved_offer_count,
            ),
        )

    def clear_form(self) -> None:
        """Clear the form."""
        self.editing_id = None
        self.editing_row_version = None
        self._form.owner_name.clear()
        self._form.phone.clear()
        self._form.is_vip.setCurrentIndex(0)
        self._form.remarks.clear()

        for panel in self._offer_panels[:]:
            self._remove_offer_panel(panel, delete_persisted=False)

        self._listing_section.collapse()
        self._listing_section.set_title(_TR("Add Listing"))
        self._offers_container.setVisible(False)
