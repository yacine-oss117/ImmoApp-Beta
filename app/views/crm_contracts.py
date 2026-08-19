"""
Contracts view for the CRM tab.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from app.models import Contract
from app.services.crm_repository import delete_contract, fetch_contracts, update_contract
from app.ui.theme_manager import current_theme
from app.ui.theme_tokens import get_theme_tokens
from app.utils.i18n import tr_factory
from app.views.base import (
    QColor,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    fmt_int_group,
)
from app.views.dialogs.contract_edit_dialog import ContractEditDialog
from app.widgets.user_feedback import (
    UserFacingMessage,
    build_success_message,
    map_exception_to_user_message,
)

logger = logging.getLogger(__name__)
_TR = tr_factory("CRMContracts")


class ContractsWidget(QWidget):
    """Widget for managing contracts with full lifecycle."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        feedback_cb: Callable[[UserFacingMessage, int | None], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self._feedback_cb = feedback_cb
        self._contracts_by_id: dict[int, Contract] = {}

        filter_layout = QHBoxLayout()
        filter_layout.setContentsMargins(10, 8, 10, 8)
        filter_layout.setSpacing(8)
        filter_layout.addWidget(QLabel(_TR("Status:"), self))
        self.status_filter = QComboBox(self)
        self.status_filter.setObjectName("contractStatusFilter")
        self.status_filter.addItem(_TR("All"), None)
        self.status_filter.addItem(_TR("Draft"), "draft")
        self.status_filter.addItem(_TR("Pending"), "pending_signature")
        self.status_filter.addItem(_TR("Signed"), "signed")
        self.status_filter.addItem(_TR("Completed"), "completed")
        self.status_filter.addItem(_TR("Cancelled"), "cancelled")
        self.status_filter.currentTextChanged.connect(self.refresh)
        filter_layout.addWidget(self.status_filter)
        self.status_filter.setAccessibleName(_TR("Contract status filter"))

        filter_layout.addWidget(QLabel(_TR("Type:"), self))
        self.type_filter = QComboBox(self)
        self.type_filter.setObjectName("contractTypeFilter")
        self.type_filter.addItem(_TR("All"), None)
        self.type_filter.addItem(_TR("Rent"), "rent")
        self.type_filter.addItem(_TR("Buy"), "buy")
        self.type_filter.currentTextChanged.connect(self.refresh)
        filter_layout.addWidget(self.type_filter)
        self.type_filter.setAccessibleName(_TR("Contract type filter"))

        filter_layout.addStretch()

        self.table = QTableWidget(0, 8, self)
        self.table.setObjectName("contractsTable")
        self.table.setAccessibleName(_TR("Contracts table"))
        self.table.setAccessibleDescription(_TR("Table of contracts and actions."))
        self.table.setHorizontalHeaderLabels(
            [
                _TR("#"),
                _TR("Client"),
                _TR("Listing"),
                _TR("Type"),
                _TR("Amount"),
                _TR("Status"),
                _TR("Start"),
                _TR("End"),
            ]
        )
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setDefaultSectionSize(40)

        filters_card = QFrame(self)
        filters_card.setObjectName("contractsFiltersCard")
        filters_card.setProperty("immoCard", True)
        filters_card.setProperty("immoRole", "crmFilters")
        filters_card.setLayout(filter_layout)

        table_card = QFrame(self)
        table_card.setObjectName("contractsTableCard")
        table_card.setProperty("immoCard", True)
        table_card.setProperty("immoRole", "crmTable")
        table_layout = QVBoxLayout(table_card)
        table_layout.setContentsMargins(10, 10, 10, 10)
        table_layout.setSpacing(8)

        self.actions_panel = QWidget(table_card)
        self.actions_panel.setObjectName("contractsActionsPanel")
        self.actions_panel.setAccessibleName(_TR("Contract actions"))
        self.actions_panel.setAccessibleDescription(_TR("Lifecycle actions for visible contracts."))
        self.actions_panel.setProperty("contractsActionsPanel", True)
        self.actions_layout = QVBoxLayout(self.actions_panel)
        self.actions_layout.setContentsMargins(0, 0, 0, 0)
        self.actions_layout.setSpacing(4)

        table_layout.addWidget(self.actions_panel)
        table_layout.addWidget(self.table)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)
        layout.addWidget(filters_card)
        layout.addWidget(table_card, 1)
        self.setLayout(layout)

        self.refresh()

    def _clear_action_rows(self) -> None:
        while self.actions_layout.count():
            item = self.actions_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def refresh(self) -> None:
        """Refresh the contracts table."""
        self.table.setRowCount(0)
        self._clear_action_rows()
        tokens = get_theme_tokens(current_theme())

        status_obj = self.status_filter.currentData()
        status = status_obj if isinstance(status_obj, str) else None
        type_obj = self.type_filter.currentData()
        contract_type = type_obj if isinstance(type_obj, str) else None

        try:
            contracts = fetch_contracts(status=status, contract_type=contract_type)
        except Exception as exc:
            logger.error("Failed to fetch contracts", exc_info=True)
            self._emit_feedback(map_exception_to_user_message(exc, context="crm.contracts.refresh"))
            return
        self._contracts_by_id = {int(contract.id): contract for contract in contracts}
        self.table.setRowCount(len(contracts))

        for i, c in enumerate(contracts):
            self.table.setItem(i, 0, QTableWidgetItem(str(c.id)))
            self.table.setItem(i, 1, QTableWidgetItem(c.client_name or str(c.client_id)))
            self.table.setItem(i, 2, QTableWidgetItem(c.listing_location or str(c.listing_id)))
            self.table.setItem(
                i,
                3,
                QTableWidgetItem(_TR("Rent") if c.contract_type == "rent" else _TR("Buy")),
            )
            self.table.setItem(i, 4, QTableWidgetItem(fmt_int_group(c.amount) + " DA"))

            status_display = {
                "draft": (_TR("Draft"), tokens["STATUS_DRAFT"]),
                "pending_signature": (_TR("Pending signature"), tokens["STATUS_PENDING"]),
                "signed": (_TR("Signed"), tokens["STATUS_SIGNED"]),
                "completed": (_TR("Completed"), tokens["STATUS_ARCHIVED"]),
                "cancelled": (_TR("Cancelled"), tokens["STATUS_CANCELLED"]),
            }
            display_text, color = status_display.get(c.status, (c.status, tokens["TEXT_MUTED"]))
            status_item = QTableWidgetItem(display_text)
            status_item.setForeground(QColor(color))
            self.table.setItem(i, 5, status_item)

            self.table.setItem(i, 6, QTableWidgetItem(c.start_date or "-"))
            self.table.setItem(i, 7, QTableWidgetItem(c.end_date or "-"))

            action_row = QWidget(self.actions_panel)
            action_row.setObjectName(f"contractActionRow_{c.id}")
            action_row.setProperty("contractActionRow", True)
            action_layout = QHBoxLayout(action_row)
            action_layout.setContentsMargins(0, 0, 0, 0)
            action_layout.setSpacing(8)

            action_label = QLabel(
                f"#{c.id} {display_text} {fmt_int_group(c.amount)} DA",
                action_row,
            )
            action_label.setObjectName(f"contractActionLabel_{c.id}")
            action_label.setProperty("immoMuted", True)
            action_layout.addWidget(action_label)
            action_layout.addStretch()
            action_layout.addWidget(self._build_action_buttons(c, action_row))
            self.actions_layout.addWidget(action_row)

        self.actions_panel.setVisible(bool(contracts))

    def _build_action_buttons(self, c: Contract, parent: QWidget) -> QWidget:
        actions = QWidget(parent)
        actions.setObjectName(f"contractActions_{c.id}")
        actions.setAccessibleName(_TR("Contract actions"))
        actions.setProperty("contractActions", True)
        h = QHBoxLayout(actions)
        h.setContentsMargins(4, 2, 4, 2)
        h.setSpacing(4)

        if c.status in ("draft", "pending_signature"):
            edit_btn = QPushButton(_TR("Edit"), actions)
            edit_btn.setObjectName(f"contractEditButton_{c.id}")
            edit_btn.setProperty("contract_id", c.id)
            edit_btn.setAccessibleName(_TR("Edit contract details"))
            edit_btn.clicked.connect(self._edit_contract)
            edit_btn.setProperty("immoVariant", "ghost")
            edit_btn.setMinimumWidth(48)
            h.addWidget(edit_btn)

        if c.status == "draft":
            print_btn = QPushButton(_TR("Print"), actions)
            print_btn.setObjectName(f"contractPrintButton_{c.id}")
            print_btn.setProperty("contract_id", c.id)
            print_btn.setAccessibleName(_TR("Print contract"))
            print_btn.clicked.connect(self._print_contract)
            print_btn.setProperty("immoVariant", "secondary")
            print_btn.setMinimumWidth(54)
            h.addWidget(print_btn)

        if c.status == "pending_signature":
            sign_btn = QPushButton(_TR("Sign"), actions)
            sign_btn.setObjectName(f"contractSignButton_{c.id}")
            sign_btn.setProperty("contract_id", c.id)
            sign_btn.setAccessibleName(_TR("Sign contract"))
            sign_btn.clicked.connect(self._sign_contract)
            sign_btn.setProperty("immoVariant", "success")
            sign_btn.setMinimumWidth(52)
            h.addWidget(sign_btn)

        if c.status in ("draft", "pending_signature", "signed"):
            cancel_btn = QPushButton(_TR("Cancel"), actions)
            cancel_btn.setObjectName(f"contractCancelLifecycleButton_{c.id}")
            cancel_btn.setProperty("contract_id", c.id)
            cancel_btn.setAccessibleName(_TR("Cancel contract"))
            cancel_btn.clicked.connect(self._cancel_contract)
            cancel_btn.setProperty("immoVariant", "danger")
            cancel_btn.setMinimumWidth(54)
            h.addWidget(cancel_btn)

        if c.status in ("draft", "cancelled"):
            del_btn = QPushButton(_TR("Delete"), actions)
            del_btn.setObjectName(f"contractDeleteButton_{c.id}")
            del_btn.setProperty("contract_id", c.id)
            del_btn.setAccessibleName(_TR("Delete contract"))
            del_btn.clicked.connect(self._delete_contract)
            del_btn.setProperty("immoVariant", "warning")
            del_btn.setMinimumWidth(50)
            h.addWidget(del_btn)

        h.addStretch()
        return actions

    def _sender_contract_id(self) -> int:
        sender = self.sender()
        if sender is None:
            return 0
        value = sender.property("contract_id")
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    def _edit_contract(self) -> None:
        """Open a details-only edit dialog for a draft or pending contract."""
        contract_id = self._sender_contract_id()
        contract = self._contracts_by_id.get(contract_id)
        if contract is None:
            self._emit_feedback(
                map_exception_to_user_message(
                    ValueError(_TR("Contract not found.")),
                    context="crm.contracts.edit",
                )
            )
            self.refresh()
            return

        dialog = ContractEditDialog(contract, self)
        if dialog.exec():
            contract_data = dialog.get_contract_data()
            if contract_data:
                try:
                    update_contract(contract_id, contract_data)
                    self._emit_feedback(
                        build_success_message(
                            title=_TR("Contract updated"),
                            message=_TR("Contract details were saved."),
                        ),
                        auto_dismiss_ms=5000,
                    )
                except (RuntimeError, ValueError) as exc:
                    logger.error("Update contract failed", exc_info=True)
                    self._emit_feedback(
                        map_exception_to_user_message(exc, context="crm.contracts.edit")
                    )
        self.refresh()

    def _print_contract(self) -> None:
        """Mark contract as pending signature (given to client)."""
        from app.services.crm_repository import print_contract

        contract_id = self._sender_contract_id()
        try:
            print_contract(contract_id)
            self._emit_feedback(
                build_success_message(
                    title=_TR("Contract updated"),
                    message=_TR("Contract marked as pending signature."),
                ),
                auto_dismiss_ms=5000,
            )
        except Exception as exc:
            logger.error("Print contract failed", exc_info=True)
            self._emit_feedback(map_exception_to_user_message(exc, context="crm.contracts.print"))
        self.refresh()

    def _sign_contract(self) -> None:
        """Mark contract as signed, archive client/listing."""
        from app.services.crm_repository import activate_contract

        contract_id = self._sender_contract_id()

        reply = QMessageBox.question(
            self,
            _TR("Confirm"),
            _TR(
                "Has the client signed this contract?\n\n"
                "This will:\n"
                "- Mark the contract as 'Signed'\n"
                "- Archive the client and listing\n"
                "- Create an end-of-contract reminder"
            ),
        )
        if reply == QMessageBox.StandardButton.Yes:
            try:
                activate_contract(contract_id)
                self._emit_feedback(
                    build_success_message(
                        title=_TR("Contract signed"),
                        message=_TR(
                            "The contract was signed and the related records were archived."
                        ),
                    ),
                    auto_dismiss_ms=5000,
                )
            except (RuntimeError, ValueError) as exc:
                logger.error("Activate contract failed", exc_info=True)
                self._emit_feedback(
                    map_exception_to_user_message(exc, context="crm.contracts.sign")
                )
            self.refresh()

    def _cancel_contract(self) -> None:
        """Cancel contract and optionally restore statuses."""
        from app.services.crm_repository import cancel_contract

        contract_id = self._sender_contract_id()

        reply = QMessageBox.question(
            self,
            _TR("Confirm"),
            _TR(
                "Cancel this contract?\n\n"
                "If the contract was signed, the client and listing will be restored to 'Active'."
            ),
        )
        if reply == QMessageBox.StandardButton.Yes:
            try:
                cancel_contract(contract_id, restore_status=True)
                self._emit_feedback(
                    build_success_message(
                        title=_TR("Contract cancelled"),
                        message=_TR("The contract was cancelled."),
                    ),
                    auto_dismiss_ms=5000,
                )
            except (RuntimeError, ValueError) as exc:
                logger.error("Cancel contract failed", exc_info=True)
                self._emit_feedback(
                    map_exception_to_user_message(exc, context="crm.contracts.cancel")
                )
            self.refresh()

    def _delete_contract(self) -> None:
        """Delete a draft or cancelled contract."""
        contract_id = self._sender_contract_id()
        if (
            QMessageBox.question(self, _TR("Confirm"), _TR("Delete this contract?"))
            == QMessageBox.StandardButton.Yes
        ):
            try:
                delete_contract(contract_id)
                self._emit_feedback(
                    build_success_message(
                        title=_TR("Contract removed"),
                        message=_TR("The contract was deleted."),
                    ),
                    auto_dismiss_ms=5000,
                )
            except Exception as exc:
                logger.error("Delete contract failed", exc_info=True)
                self._emit_feedback(
                    map_exception_to_user_message(exc, context="crm.contracts.delete")
                )
            self.refresh()

    def _emit_feedback(
        self, message: UserFacingMessage, auto_dismiss_ms: int | None = None
    ) -> None:
        if self._feedback_cb is not None:
            self._feedback_cb(message, auto_dismiss_ms)
            return
        body = message.message
        if message.action_hint:
            body = f"{body} {message.action_hint}".strip()
        if message.severity in {"success", "info"}:
            QMessageBox.information(self, message.title, body)
        else:
            QMessageBox.warning(self, message.title, body)
