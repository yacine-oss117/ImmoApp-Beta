"""
CRM actions for the Match tab.
"""

from __future__ import annotations

from collections.abc import Callable

from app.models import Offer
from app.services.client_repository import get_client_by_id
from app.services.crm_repository import create_contract, create_visit
from app.services.listing_repository import get_listing_by_id
from app.utils.i18n import tr_factory
from app.views.base import QMessageBox, QWidget
from app.views.dialogs.contract_builder_dialog import ContractBuilderDialog
from app.views.dialogs.contract_dialog import ContractDialog
from app.views.dialogs.visit_dialog import VisitDialog
from app.widgets.user_feedback import (
    UserFacingMessage,
    build_success_message,
    map_exception_to_user_message,
)

_TR = tr_factory("MatchActions")


def _coerce_int(value: object, field: str) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    raise ValueError(_TR("Invalid {field}: {value!r}").format(field=field, value=value))


def _emit_feedback(
    parent: QWidget,
    message: UserFacingMessage,
    *,
    feedback_cb: Callable[[UserFacingMessage, int | None], None] | None,
    auto_dismiss_ms: int | None = None,
) -> None:
    if feedback_cb is not None:
        feedback_cb(message, auto_dismiss_ms)
        return
    body = message.message
    if message.action_hint:
        body = f"{body} {message.action_hint}".strip()
    if message.severity in {"success", "info"}:
        QMessageBox.information(parent, message.title, body)
    else:
        QMessageBox.warning(parent, message.title, body)


def schedule_visit(
    *,
    parent: QWidget,
    client_id: object,
    listing_id: object,
    location: object,
    refresh_crm_cb: Callable[[], None] | None,
    feedback_cb: Callable[[UserFacingMessage, int | None], None] | None = None,
) -> None:
    """Open visit scheduling dialog and persist visit if saved."""
    try:
        client_id_int = _coerce_int(client_id, "client_id")
        listing_id_int = _coerce_int(listing_id, "listing_id")
    except ValueError as exc:
        _emit_feedback(
            parent,
            map_exception_to_user_message(exc, context="match.action.schedule_visit"),
            feedback_cb=feedback_cb,
        )
        return

    dialog = VisitDialog(client_id_int, listing_id_int, "", str(location or ""), parent)
    if dialog.exec():
        visit_data = dialog.get_visit_data()
        if visit_data:
            try:
                create_visit(visit_data)
            except (RuntimeError, ValueError) as exc:
                _emit_feedback(
                    parent,
                    map_exception_to_user_message(exc, context="match.action.schedule_visit"),
                    feedback_cb=feedback_cb,
                )
                return
            _emit_feedback(
                parent,
                build_success_message(
                    title=_TR("Visit scheduled"),
                    message=_TR("The visit was added to follow-up."),
                ),
                feedback_cb=feedback_cb,
                auto_dismiss_ms=5000,
            )
            if refresh_crm_cb:
                refresh_crm_cb()


def create_contract_action(
    *,
    parent: QWidget,
    client_id: object,
    listing_id: object,
    action: object,
    refresh_crm_cb: Callable[[], None] | None,
    feedback_cb: Callable[[UserFacingMessage, int | None], None] | None = None,
) -> None:
    """Open contract creation dialog and persist contract if saved."""
    try:
        client_id_int = _coerce_int(client_id, "client_id")
        listing_id_int = _coerce_int(listing_id, "listing_id")
    except ValueError as exc:
        _emit_feedback(
            parent,
            map_exception_to_user_message(exc, context="match.action.create_contract"),
            feedback_cb=feedback_cb,
        )
        return

    contract_type = "buy" if str(action or "sell") == "sell" else "rent"
    dialog = ContractDialog(client_id_int, listing_id_int, contract_type, "", "", parent)
    if dialog.exec():
        contract_data = dialog.get_contract_data()
        if contract_data:
            try:
                create_contract(contract_data)
            except (RuntimeError, ValueError) as exc:
                _emit_feedback(
                    parent,
                    map_exception_to_user_message(exc, context="match.action.create_contract"),
                    feedback_cb=feedback_cb,
                )
                return
            _emit_feedback(
                parent,
                build_success_message(
                    title=_TR("Contract created"),
                    message=_TR("{type} contract created.").format(type=contract_type.title()),
                ),
                feedback_cb=feedback_cb,
                auto_dismiss_ms=5000,
            )
            if refresh_crm_cb:
                refresh_crm_cb()


def generate_pdf_contract(
    *,
    parent: QWidget,
    client_id: object,
    listing_id: object,
    offer: object | None = None,
    refresh_crm_cb: Callable[[], None] | None,
    feedback_cb: Callable[[UserFacingMessage, int | None], None] | None = None,
) -> None:
    """Open the Contract Builder Dialog to generate a PDF contract."""
    try:
        client_id_int = _coerce_int(client_id, "client_id")
        listing_id_int = _coerce_int(listing_id, "listing_id")
    except ValueError as exc:
        _emit_feedback(
            parent,
            map_exception_to_user_message(exc, context="match.action.generate_contract"),
            feedback_cb=feedback_cb,
        )
        return

    client = get_client_by_id(client_id_int)
    listing = get_listing_by_id(listing_id_int)
    if client is None or listing is None:
        _emit_feedback(
            parent,
            map_exception_to_user_message(
                ValueError(_TR("Client or listing is no longer available.")),
                context="match.action.generate_contract",
            ),
            feedback_cb=feedback_cb,
        )
        return
    offer_obj = offer if isinstance(offer, Offer) else None

    dialog = ContractBuilderDialog(
        parent=parent,
        client=client,
        listing=listing,
        offer=offer_obj,
    )
    dialog.exec()

    if refresh_crm_cb:
        refresh_crm_cb()
