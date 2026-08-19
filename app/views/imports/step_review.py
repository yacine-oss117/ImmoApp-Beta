from __future__ import annotations

import json
import logging
import os
from typing import Any

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QBrush
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.services.api_client_errors import ApiError
from app.utils.i18n import tr_factory
from app.utils.qt_async import run_background_result
from app.views.imports.import_experience import ImportReviewGroupRecord
from app.views.imports.review_actions import (
    allowed_entity_types_for_state,
    draft_to_submit_payload,
    normalize_review_action,
)
from app.views.imports.review_api_adapter import (
    fetch_import_status,
    fetch_review_page,
    submit_review,
)
from app.views.imports.review_page_controller import (
    build_refresh_review_model,
    format_conflict_message,
    hydrate_review_page_payload,
    map_review_conflicts_to_items,
)
from app.views.imports.review_row_card import _ReviewRowCard
from app.views.imports.review_submit_result import apply_final_review_submit_response
from app.views.imports.wizard_state import ImportWizardController

_TR = tr_factory("ImportWizardStepReview")
logger = logging.getLogger(__name__)
_E2E_MODE = str(os.environ.get("IMMOAPP_E2E_TEST_MODE", "") or "").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}


class StepReview(QWidget):
    finished = Signal()

    def __init__(self, controller: ImportWizardController) -> None:
        super().__init__()
        self.setObjectName("importStepReview")
        self.controller = controller
        self._row_cards: dict[int, _ReviewRowCard] = {}
        self._item_entries: dict[int, dict[str, Any]] = {}
        self._item_entry_cache: dict[int, dict[str, Any]] = {}
        self._item_drafts: dict[int, dict[str, Any]] = {}
        self._row_conflicts_by_item: dict[int, dict[str, Any]] = {}
        self._group_decisions: dict[str, dict[str, Any]] = {}
        self._group_records: list[ImportReviewGroupRecord] = []
        self._current_group_key: str | None = None
        self._current_item_id: int | None = None
        self._current_editor: _ReviewRowCard | None = None
        self._submit_task_id = ""
        self._submit_timer: QTimer | None = None
        self._submit_poll_inflight = False

        pane_state = self.controller.state.review_pane_state
        if pane_state.pending_bulk_operations is None:
            pane_state.pending_bulk_operations = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        title = QLabel(_TR("A few details need your attention"))
        title.setObjectName("StepTitle")
        layout.addWidget(title)

        self.subtitle = QLabel("")
        self.subtitle.setWordWrap(True)
        layout.addWidget(self.subtitle)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        toolbar = QFrame(self)
        toolbar.setProperty("immoRole", "workspaceToolbar")
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(0, 0, 0, 0)
        toolbar_layout.setSpacing(8)
        self._filter_buttons: dict[str, QPushButton] = {}
        for key, label in (
            ("all", _TR("All")),
            ("possible_duplicate", _TR("Duplicates")),
            ("missing_information", _TR("Missing info")),
            ("unclear_location", _TR("Location")),
            ("unclear_property_type", _TR("Property type")),
            ("field_conflict", _TR("Conflicts")),
        ):
            button = QPushButton(label, toolbar)
            button.setObjectName(f"importReviewFilter_{key}")
            button.setCheckable(True)
            button.setProperty("immoVariant", "ghost")
            button.clicked.connect(
                lambda checked, current=key: self._set_issue_filter(current, checked)
            )
            self._filter_buttons[key] = button
            toolbar_layout.addWidget(button)
        toolbar_layout.addStretch()
        self._search_input = QLineEdit(toolbar)
        self._search_input.setObjectName("importReviewSearchInput")
        self._search_input.setPlaceholderText(_TR("Search a group, line or issue"))
        self._search_input.setClearButtonEnabled(True)
        self._search_input.textChanged.connect(self._on_search_changed)
        toolbar_layout.addWidget(self._search_input, 1)
        self._prev_page_btn = QPushButton(_TR("Previous"), toolbar)
        self._prev_page_btn.setObjectName("importReviewPrevPageButton")
        self._prev_page_btn.clicked.connect(lambda: self._change_page(-1))
        toolbar_layout.addWidget(self._prev_page_btn)
        self._page_label = QLabel("", toolbar)
        self._page_label.setObjectName("importReviewPageLabel")
        toolbar_layout.addWidget(self._page_label)
        self._next_page_btn = QPushButton(_TR("Next"), toolbar)
        self._next_page_btn.setObjectName("importReviewNextPageButton")
        self._next_page_btn.clicked.connect(lambda: self._change_page(1))
        toolbar_layout.addWidget(self._next_page_btn)
        layout.addWidget(toolbar)

        splitter = QSplitter(self)
        splitter.setOrientation(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        self._splitter = splitter

        left_panel = QFrame(self)
        left_panel.setProperty("immoRole", "workspaceEditor")
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(10, 10, 10, 10)
        left_layout.setSpacing(8)
        left_header = QLabel(_TR("Groups to review"))
        left_header.setObjectName("StepDescription")
        left_layout.addWidget(left_header)
        self._group_table = QTableWidget(left_panel)
        self._group_table.setObjectName("importReviewGroupTable")
        self._group_table.setProperty("immoRole", "workspaceTable")
        self._group_table.setColumnCount(5)
        self._group_table.setHorizontalHeaderLabels(
            [
                _TR("Root"),
                _TR("Needs attention"),
                _TR("Items"),
                _TR("Suggested action"),
                _TR("Status"),
            ]
        )
        self._group_table.verticalHeader().setVisible(False)
        self._group_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._group_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._group_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._group_table.itemSelectionChanged.connect(self._on_group_selection_changed)
        self._review_table = self._group_table
        group_header = self._group_table.horizontalHeader()
        group_header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        group_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        group_header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        group_header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        group_header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        left_layout.addWidget(self._group_table, 1)
        splitter.addWidget(left_panel)

        right_panel = QFrame(self)
        right_panel.setProperty("immoRole", "workspaceEditor")
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(10, 10, 10, 10)
        right_layout.setSpacing(8)
        self._detail_title = QLabel(_TR("Review group"))
        self._detail_title.setObjectName("StepDescription")
        right_layout.addWidget(self._detail_title)
        self._group_summary = QLabel("")
        self._group_summary.setWordWrap(True)
        right_layout.addWidget(self._group_summary)
        group_action_row = QHBoxLayout()
        group_action_row.setSpacing(8)
        self._group_action_combo = QComboBox(right_panel)
        self._group_action_combo.setObjectName("importReviewGroupActionCombo")
        self._group_action_combo.currentIndexChanged.connect(self._persist_group_decision)
        group_action_row.addWidget(self._group_action_combo)
        self._group_action_buttons: dict[str, QPushButton] = {}
        for action, label, object_name in (
            ("create_new", _TR("Add as new"), "importReviewGroupActionCreateButton"),
            (
                "update_existing",
                _TR("Use existing"),
                "importReviewGroupActionUpdateButton",
            ),
            ("skip", _TR("Skip"), "importReviewGroupActionSkipButton"),
            ("", _TR("Review individually"), "importReviewGroupActionReviewButton"),
        ):
            button = QPushButton(label, right_panel)
            button.setObjectName(object_name)
            button.setProperty("immoVariant", "ghost")
            button.clicked.connect(
                lambda _checked=False, current=action: self._set_group_action(current)
            )
            self._group_action_buttons[action or "review_individually"] = button
            group_action_row.addWidget(button)
        right_layout.addLayout(group_action_row)
        self._group_action_hint = QLabel("")
        self._group_action_hint.setWordWrap(True)
        right_layout.addWidget(self._group_action_hint)
        items_header = QLabel(_TR("Lines in this group"))
        items_header.setObjectName("StepDescription")
        right_layout.addWidget(items_header)
        self._item_table = QTableWidget(right_panel)
        self._item_table.setObjectName("importReviewItemTable")
        self._item_table.setProperty("immoRole", "workspaceTable")
        self._item_table.setColumnCount(4)
        self._item_table.setHorizontalHeaderLabels(
            [_TR("Line"), _TR("Needs attention"), _TR("Action"), _TR("Status")]
        )
        self._item_table.verticalHeader().setVisible(False)
        self._item_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._item_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._item_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._item_table.itemSelectionChanged.connect(self._on_item_selection_changed)
        item_header = self._item_table.horizontalHeader()
        item_header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        item_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        item_header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        item_header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        right_layout.addWidget(self._item_table, 1)
        self._detail_scroll = QScrollArea(right_panel)
        self._detail_scroll.setObjectName("importReviewDetailScroll")
        self._detail_scroll.setWidgetResizable(True)
        self._detail_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._detail_container = QWidget(self._detail_scroll)
        self._detail_layout = QVBoxLayout(self._detail_container)
        self._detail_layout.setContentsMargins(0, 0, 0, 0)
        self._detail_layout.setSpacing(8)
        self._detail_empty = QLabel(_TR("Select a line to review its details."))
        self._detail_empty.setWordWrap(True)
        self._detail_layout.addWidget(self._detail_empty)
        self._detail_layout.addStretch()
        self._detail_scroll.setWidget(self._detail_container)
        right_layout.addWidget(self._detail_scroll, 1)
        splitter.addWidget(right_panel)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)
        layout.addWidget(splitter, 1)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self._footer_status = QLabel("")
        self._footer_status.setWordWrap(True)
        actions.addWidget(self._footer_status, 1)
        self.submit_btn = QPushButton(_TR("Continue with these choices"))
        self.submit_btn.setObjectName("importReviewSubmitButton")
        self.submit_btn.setProperty("immoVariant", "primary")
        self.submit_btn.clicked.connect(self._submit_review)
        actions.addWidget(self.submit_btn)
        layout.addLayout(actions)
        self.destroyed.connect(self._handle_destroyed)

    def refresh(self) -> None:
        pane_state = self.controller.state.review_pane_state
        if pane_state.pending_bulk_operations is None:
            pane_state.pending_bulk_operations = {}
        model = build_refresh_review_model(self.controller.state)
        self._item_entries = model.item_entries
        merged_item_entry_cache = dict(self._item_entry_cache)
        merged_item_entry_cache.update(model.item_entry_cache)
        self._item_entry_cache = merged_item_entry_cache
        self._current_editor = None
        self._current_item_id = None
        self._group_records = model.group_records
        self._row_cards = {}
        for item_id, entry in list(self._item_entries.items()):
            card = _ReviewRowCard(
                entry,
                allowed_entity_types=allowed_entity_types_for_state(self.controller.state),
            )
            card.bulkOperationQueued.connect(self._queue_bulk_operation)
            draft = self._item_drafts.get(int(item_id))
            if draft:
                card.apply_draft(draft)
            card.set_interaction_enabled(not bool(self.controller.state.review_disabled))
            self._row_cards[item_id] = card
        self.subtitle.setText(model.subtitle)
        self._group_action_combo.setEnabled(False)
        self._search_input.blockSignals(True)
        self._search_input.setText(str(pane_state.search_text or ""))
        self._search_input.blockSignals(False)
        self._apply_filter_selection()
        self._update_page_controls()
        self._refresh_group_table()
        if self.controller.state.review_disabled:
            self.submit_btn.setEnabled(False)
            self._set_status(
                str(
                    self.controller.state.review_disabled_reason
                    or _TR("This review is available in read-only mode.")
                ),
                state="warning",
            )
        else:
            self.submit_btn.setEnabled(bool(self._item_entries))
            self._set_status("", state="")

    def _set_status(self, message: str, *, state: str = "") -> None:
        self.status_label.setText(message)
        self.status_label.setProperty("immoState", state)
        self._footer_status.setText(message)
        self._footer_status.setProperty("immoState", state)
        for label in (self.status_label, self._footer_status):
            style = label.style()
            style.unpolish(label)
            style.polish(label)

    def _apply_filter_selection(self) -> None:
        active = str(self.controller.state.review_pane_state.issue_group_filter or "all")
        for key, button in self._filter_buttons.items():
            button.blockSignals(True)
            button.setChecked(key == active)
            button.blockSignals(False)

    def _set_issue_filter(self, issue_group: str, checked: bool) -> None:
        if not checked:
            return
        self.controller.state.review_pane_state.issue_group_filter = issue_group
        self.controller.state.review_pane_state.page = 1
        self._apply_filter_selection()
        self._reload_review_page()

    def _on_search_changed(self, text: str) -> None:
        self.controller.state.review_pane_state.search_text = text
        self.controller.state.review_pane_state.page = 1
        self._reload_review_page()

    def _change_page(self, delta: int) -> None:
        review_page = self.controller.state.review_page
        if review_page is None:
            return
        next_page = int(review_page.page or 1) + int(delta or 0)
        if next_page < 1 or next_page > max(1, int(review_page.total_pages or 1)):
            return
        self.controller.state.review_pane_state.page = next_page
        self._reload_review_page()

    def _update_page_controls(self) -> None:
        review_page = self.controller.state.review_page
        if review_page is None:
            self._page_label.setText("")
            self._prev_page_btn.setEnabled(False)
            self._next_page_btn.setEnabled(False)
            return
        self._page_label.setText(
            _TR("Page {page} of {total}").format(
                page=int(review_page.page or 1),
                total=max(1, int(review_page.total_pages or 1)),
            )
        )
        self._prev_page_btn.setEnabled(bool(review_page.has_prev))
        self._next_page_btn.setEnabled(bool(review_page.has_next))

    def _fetch_review_page(
        self,
        page: int,
        page_size: int,
        issue_group: str,
        search_text: str,
        group_key: str,
    ) -> dict[str, Any]:
        return fetch_review_page(
            session_id=str(self.controller.state.session_id or ""),
            page=page,
            page_size=page_size,
            issue_group=issue_group,
            search_text=search_text,
            group_key=group_key,
        )

    def _fetch_import_status(self, task_id: str) -> dict[str, Any]:
        return fetch_import_status(task_id=task_id)

    def _remember_item_drafts(self) -> None:
        for item_id, card in list(self._row_cards.items()):
            self._item_drafts[int(item_id)] = card.export_draft()

    def _draft_to_submit_payload(
        self,
        *,
        item_id: int,
        draft: dict[str, Any],
        entry: dict[str, Any],
    ) -> tuple[dict[str, Any] | None, bool]:
        _ = item_id
        return draft_to_submit_payload(draft=draft, entry=entry)

    def _reload_review_page(self, *, group_key: str | None = None) -> None:
        pane_state = self.controller.state.review_pane_state
        self._persist_group_decision()
        self._remember_item_drafts()
        resolved_group_key = str(group_key or pane_state.selected_group_key or "")
        if not str(self.controller.state.session_id or "").strip():
            if resolved_group_key:
                pane_state.selected_group_key = resolved_group_key
            self._show_group(pane_state.selected_group_key)
            return
        run_background_result(
            self._fetch_review_page,
            self._on_review_page_result,
            self._on_submit_error,
            int(pane_state.page or 1),
            int(pane_state.page_size or 50),
            str(pane_state.issue_group_filter or "all"),
            str(pane_state.search_text or ""),
            resolved_group_key,
        )

    def _on_review_page_result(self, data: dict[str, Any]) -> None:
        pane_state = self.controller.state.review_pane_state
        hydration = hydrate_review_page_payload(
            data,
            pane_state=pane_state,
            current_status=self.controller.state.status,
            current_stage=self.controller.state.stage,
        )
        pane_state.mode = hydration.review_mode
        pane_state.selected_group_key = hydration.selected_group_key
        pane_state.issue_group_filter = hydration.issue_group_filter
        pane_state.search_text = hydration.search_text
        if hydration.page is not None:
            pane_state.page = hydration.page
        if hydration.page_size is not None:
            pane_state.page_size = hydration.page_size
        pane_state.review_state = hydration.review_state
        pane_state.review_disabled = hydration.review_disabled
        pane_state.review_disabled_reason = hydration.review_disabled_reason
        self.controller.update_state(
            status=hydration.status,
            stage=hydration.stage,
            review_count=hydration.review_count,
            review_pending_group_count=hydration.review_pending_group_count,
            review_overflow_count=hydration.review_overflow_count,
            review_total_count=hydration.review_total_count,
            review_mode=hydration.review_mode,
            review_state=hydration.review_state,
            overflow_blocking=hydration.overflow_blocking,
            review_disabled=hydration.review_disabled,
            review_disabled_reason=hydration.review_disabled_reason,
            review_groups=hydration.review_groups,
            review_page=hydration.review_page,
            review_rows=hydration.review_rows,
        )
        self.refresh()
        conflict_payload = dict(data.get("review_submit_conflict", {}) or {})
        if conflict_payload:
            self._apply_conflicts(
                list(conflict_payload.get("row_conflicts", []) or []),
                conflict_item_ids=[
                    int(value)
                    for value in list(conflict_payload.get("conflict_item_ids", []) or [])
                ],
            )
            detail = str(
                conflict_payload.get("detail", "") or _TR("A few lines still need your attention.")
            )
            self._set_status(detail, state="warning")
            return
        error_payload = dict(data.get("review_submit_error", {}) or {})
        if error_payload:
            detail = str(
                error_payload.get("detail", "")
                or _TR("We couldn’t continue with these choices just yet. Please try again.")
            )
            self._set_status(detail, state="warning")

    def _refresh_group_table(self) -> None:
        self._group_table.setRowCount(len(self._group_records))
        for row_index, group in enumerate(self._group_records):
            group_has_conflict = any(
                int(entry.get("item_id", 0) or 0) in self._row_conflicts_by_item
                for entry in self._current_group_entries(group.group_key)
            )
            status_text = (
                _TR("Conflict")
                if group.group_kind == "duplicate_conflict"
                or group.blocking_item_count > 0
                or group_has_conflict
                else _TR("Ready")
            )
            values = [
                group.root_label or _TR("Group"),
                group.issue_title,
                str(group.pending_item_count or group.item_count or 0),
                str(group.suggested_group_action or _TR("Choose")).replace("_", " ").title(),
                status_text,
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, group.group_key)
                if status_text == _TR("Conflict"):
                    item.setBackground(QBrush(Qt.GlobalColor.darkRed))
                self._group_table.setItem(row_index, column, item)
        selected_group_key = self.controller.state.review_pane_state.selected_group_key
        available_group_keys = {group.group_key for group in self._group_records}
        if selected_group_key not in available_group_keys:
            selected_group_key = self._group_records[0].group_key if self._group_records else None
        self._select_group_in_table(selected_group_key)

    def _group_record(self, group_key: str | None) -> ImportReviewGroupRecord | None:
        for group in self._group_records:
            if group.group_key == str(group_key or ""):
                return group
        return None

    def _current_group_entries(self, group_key: str | None) -> list[dict[str, Any]]:
        if not group_key:
            return list(self._item_entries.values())
        return [
            dict(entry)
            for entry in self._item_entries.values()
            if str(entry.get("group_key", "") or "") == str(group_key or "")
        ]

    def _populate_group_action_combo(self, group: ImportReviewGroupRecord | None) -> None:
        self._group_action_combo.blockSignals(True)
        self._group_action_combo.clear()
        self._group_action_combo.addItem(_TR("Review each line individually"), "")
        if group and group.apply_to_all_allowed:
            self._group_action_combo.addItem(_TR("Add compatible lines as new"), "create_new")
            if int(group.consistent_existing_id or 0) > 0:
                self._group_action_combo.addItem(
                    _TR("Use the matching record for compatible lines"),
                    "update_existing",
                )
            self._group_action_combo.addItem(_TR("Skip compatible lines"), "skip")
        selected_action = ""
        if group is not None:
            selected_action = str(
                self._group_decisions.get(group.group_key, {}).get("action", "") or ""
            )
            if not selected_action:
                selected_action = normalize_review_action(str(group.suggested_group_action or ""))
        selected_index = self._group_action_combo.findData(selected_action)
        self._group_action_combo.setCurrentIndex(selected_index if selected_index >= 0 else 0)
        self._group_action_combo.blockSignals(False)
        available_actions = {
            str(self._group_action_combo.itemData(index) or "")
            for index in range(self._group_action_combo.count())
        }
        buttons_enabled = bool(
            group and group.apply_to_all_allowed and not self.controller.state.review_disabled
        )
        for action, button in self._group_action_buttons.items():
            action_value = "" if action == "review_individually" else action
            button.setVisible(buttons_enabled and action_value in available_actions)
            button.setEnabled(buttons_enabled and action_value in available_actions)
        if group and group.apply_to_all_allowed:
            self._group_action_hint.setText(
                _TR(
                    "You can apply one safe root decision to {count} compatible lines in this group."
                ).format(count=max(1, int(group.apply_to_all_count or 0)))
            )
            self._group_action_combo.setEnabled(not self.controller.state.review_disabled)
        else:
            self._group_action_hint.setText(
                _TR("Review these lines individually. This group does not support one-click apply.")
            )
            self._group_action_combo.setEnabled(False)

    def _select_group_in_table(self, group_key: str | None) -> None:
        if not group_key:
            self._show_group(None)
            return
        for row_index in range(self._group_table.rowCount()):
            item = self._group_table.item(row_index, 0)
            if item is None:
                continue
            if str(item.data(Qt.ItemDataRole.UserRole) or "") == str(group_key or ""):
                self._group_table.blockSignals(True)
                self._group_table.selectRow(row_index)
                self._group_table.blockSignals(False)
                self._show_group(str(group_key))
                return
        self._show_group(None)

    def _on_group_selection_changed(self) -> None:
        selected = self._group_table.selectedItems()
        if not selected:
            self._show_group(None)
            return
        self._persist_group_decision()
        group_key = str(selected[0].data(Qt.ItemDataRole.UserRole) or "")
        self.controller.state.review_pane_state.selected_group_key = group_key or None
        if str(self.controller.state.session_id or "").strip():
            self._reload_review_page(group_key=group_key)
        else:
            self._show_group(group_key)

    def _on_table_selection_changed(self) -> None:
        self._on_group_selection_changed()

    def _refresh_item_table(self, group_key: str | None) -> None:
        entries = self._current_group_entries(group_key)
        self._item_table.setRowCount(len(entries))
        for row_index, entry in enumerate(entries):
            item_id = int(entry.get("item_id", 0) or 0)
            status_text = (
                _TR("Conflict") if item_id in self._row_conflicts_by_item else _TR("Ready")
            )
            values = [
                str(int(entry.get("row", 0) or 0)),
                str(entry.get("issue_title", _TR("Needs attention")) or _TR("Needs attention")),
                str(entry.get("suggested_action", "") or _TR("Choose")).replace("_", " ").title(),
                status_text,
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, item_id)
                if item_id in self._row_conflicts_by_item:
                    item.setBackground(QBrush(Qt.GlobalColor.darkRed))
                self._item_table.setItem(row_index, column, item)
        selected_item_id = self.controller.state.review_pane_state.selected_item_id
        available_item_ids = {int(entry.get("item_id", 0) or 0) for entry in entries}
        if selected_item_id not in available_item_ids:
            selected_item_id = None
        if selected_item_id is None and entries:
            selected_item_id = int(entries[0].get("item_id", 0) or 0)
        self._select_item_in_table(selected_item_id)

    def _show_group(self, group_key: str | None) -> None:
        self._current_group_key = group_key
        group = self._group_record(group_key)
        self._detail_title.setText(
            group.root_label if group and group.root_label else _TR("Review group")
        )
        self._group_summary.setText(
            group.issue_summary if group else _TR("Select a group to review its details.")
        )
        self._populate_group_action_combo(group)
        self._refresh_item_table(group_key)

    def _select_item_in_table(self, item_id: int | None) -> None:
        if item_id is None:
            self._show_editor(None)
            return
        for row_index in range(self._item_table.rowCount()):
            item = self._item_table.item(row_index, 0)
            if item is None:
                continue
            if int(item.data(Qt.ItemDataRole.UserRole) or 0) == int(item_id or 0):
                self._item_table.blockSignals(True)
                self._item_table.selectRow(row_index)
                self._item_table.blockSignals(False)
                self._show_editor(int(item_id))
                return
        self._show_editor(None)

    def _on_item_selection_changed(self) -> None:
        selected = self._item_table.selectedItems()
        if not selected:
            self._show_editor(None)
            return
        self._show_editor(int(selected[0].data(Qt.ItemDataRole.UserRole) or 0))

    def _show_editor(self, item_id: int | None) -> None:
        self.controller.state.review_pane_state.selected_item_id = item_id
        self._current_item_id = item_id
        if self._current_editor is not None:
            self._detail_layout.removeWidget(self._current_editor)
            self._current_editor.setParent(None)
            self._current_editor = None
        self._detail_empty.setVisible(item_id is None)
        if item_id is None:
            return
        card = self._row_cards.get(int(item_id))
        if card is None:
            return
        self._detail_empty.setVisible(False)
        self._detail_layout.insertWidget(0, card)
        self._current_editor = card
        conflict = self._row_conflicts_by_item.get(int(item_id))
        if conflict:
            card.error_label.setText(format_conflict_message(conflict))

    def _set_group_action(self, action: str) -> None:
        selected_index = self._group_action_combo.findData(action)
        if selected_index < 0:
            return
        self._group_action_combo.setCurrentIndex(selected_index)
        self._persist_group_decision()

    def _persist_group_decision(self) -> None:
        group_key = str(self._current_group_key or "")
        group = self._group_record(group_key)
        if not group_key or group is None:
            return
        if self.controller.state.review_disabled or not group.apply_to_all_allowed:
            self._group_decisions.pop(group_key, None)
            return
        action = str(self._group_action_combo.currentData() or "")
        if not action:
            self._group_decisions.pop(group_key, None)
            return
        payload: dict[str, Any] = {"action": action, "entity_type": group.entity_type}
        if action == "update_existing":
            existing_id = int(group.consistent_existing_id or 0)
            if existing_id > 0:
                payload["existing_id"] = existing_id
        self._group_decisions[group_key] = payload

    def _queue_bulk_operation(self, operation: dict[str, Any]) -> None:
        group_key = str(operation.get("group_key", "") or "") or json.dumps(
            operation, sort_keys=True
        )
        pane_state = self.controller.state.review_pane_state
        pending = pane_state.pending_bulk_operations or {}
        pending[group_key] = dict(operation)
        pane_state.pending_bulk_operations = pending
        self._set_status(
            _TR("{count} similar-line fix(es) are ready to apply.").format(count=len(pending)),
            state="muted",
        )

    def _submit_review(self) -> None:
        if self.controller.state.review_disabled:
            self.submit_btn.setEnabled(False)
            self._set_status(
                str(
                    self.controller.state.review_disabled_reason
                    or _TR("This review is available in read-only mode.")
                ),
                state="warning",
            )
            return
        self._persist_group_decision()
        self._remember_item_drafts()
        item_decisions: dict[str, dict[str, Any]] = {}
        skip_item_ids: list[int] = []
        for item_id, card in self._row_cards.items():
            if int(item_id) not in self._item_entries:
                continue
            card.error_label.clear()
            payload, error_message = card.to_payload()
            if error_message:
                card.error_label.setText(error_message)
                self._set_status(error_message, state="error")
                self._select_item_in_table(int(item_id))
                return
            if payload is None:
                continue
            action = normalize_review_action(str(payload["action"]))
            original_entry = self._item_entries.get(int(item_id), {})
            baseline_payload = dict(
                original_entry.get("normalized_data", original_entry.get("data", {}))
            )
            row_data = dict(payload.get("payload", {}) or {})
            group_key = str(original_entry.get("group_key", payload.get("group_key", "")) or "")
            group_override = dict(self._group_decisions.get(group_key, {}) or {})
            suggested_action = normalize_review_action(
                str(original_entry.get("suggested_action", "") or "")
            )
            follow_group_resolution = bool(group_override) and action == suggested_action
            if action == "skip":
                skip_item_ids.append(int(item_id))
                continue
            item_payload: dict[str, Any] = {}
            if not follow_group_resolution:
                item_payload["action"] = action
            entity_type = str(payload.get("entity_type", "") or "")
            if entity_type and (
                not follow_group_resolution
                or entity_type != str(original_entry.get("entity_type", "") or "")
            ):
                item_payload["entity_type"] = entity_type
            if row_data != baseline_payload:
                item_payload["corrections"] = row_data
            if not follow_group_resolution and action == "update_existing":
                item_payload["existing_id"] = int(payload.get("existing_id", 0) or 0)
                item_payload["row_version"] = int(payload.get("row_version", 0) or 0)
            if item_payload:
                item_decisions[str(int(item_id))] = item_payload
        for item_id, draft in list(self._item_drafts.items()):
            if int(item_id) in self._row_cards:
                continue
            entry = self._item_entry_cache.get(int(item_id))
            if entry is None:
                continue
            draft_item_payload, skip_item = self._draft_to_submit_payload(
                item_id=int(item_id),
                draft=draft,
                entry=entry,
            )
            if skip_item:
                skip_item_ids.append(int(item_id))
                continue
            if draft_item_payload is not None:
                item_decisions[str(int(item_id))] = draft_item_payload
        self.submit_btn.setEnabled(False)
        self._set_status(_TR("Saving your choices..."), state="loading")
        if _E2E_MODE:
            logger.info(
                "Desktop E2E review submit payload: %s",
                json.dumps(
                    {
                        "item_decisions": item_decisions,
                        "group_decisions": dict(self._group_decisions),
                        "skip_item_ids": skip_item_ids,
                        "bulk_operations": list(
                            (
                                self.controller.state.review_pane_state.pending_bulk_operations
                                or {}
                            ).values()
                        ),
                    },
                    ensure_ascii=True,
                    sort_keys=True,
                ),
            )
        run_background_result(
            self._perform_submit,
            self._on_submit_result,
            self._on_submit_error,
            item_decisions,
            dict(self._group_decisions),
            skip_item_ids,
            list((self.controller.state.review_pane_state.pending_bulk_operations or {}).values()),
        )

    def _perform_submit(
        self,
        item_decisions: dict[str, dict[str, Any]],
        group_decisions: dict[str, dict[str, Any]],
        skip_item_ids: list[int],
        bulk_operations: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return submit_review(
            session_id=str(self.controller.state.session_id or ""),
            item_decisions=item_decisions,
            group_decisions=group_decisions,
            skip_item_ids=skip_item_ids,
            bulk_operations=bulk_operations,
        )

    def _start_submit_polling(self, task_id: str, initial_interval_ms: int) -> None:
        self._stop_submit_polling()
        self._submit_task_id = str(task_id or "")
        if not self._submit_task_id:
            return
        self._submit_timer = QTimer(self)
        self._submit_timer.setInterval(max(100, int(initial_interval_ms or 150)))
        self._submit_timer.timeout.connect(self._poll_current_submit_status)
        self._submit_timer.start()
        self._poll_submit_status(self._submit_task_id)

    def _stop_submit_polling(self) -> None:
        if self._submit_timer is not None:
            self._submit_timer.stop()
            self._submit_timer.deleteLater()
            self._submit_timer = None
        self._submit_task_id = ""
        self._submit_poll_inflight = False

    def _handle_destroyed(self, _obj: object | None = None) -> None:
        self._stop_submit_polling()

    def _poll_current_submit_status(self) -> None:
        if not self._submit_task_id:
            return
        self._poll_submit_status(self._submit_task_id)

    def _poll_submit_status(self, task_id: str) -> None:
        if self._submit_poll_inflight:
            return
        self._submit_poll_inflight = True
        run_background_result(
            self._fetch_import_status,
            self._on_submit_poll_result,
            self._on_submit_poll_error,
            task_id,
        )

    def _on_submit_poll_error(self, message: str | Exception) -> None:
        self._submit_poll_inflight = False
        self.submit_btn.setEnabled(True)
        self._stop_submit_polling()
        self._on_submit_error(message)

    def _on_submit_poll_result(self, data: dict[str, Any]) -> None:
        self._submit_poll_inflight = False
        poll_after = data.get("poll_after_ms", 150)
        if self._submit_timer is not None:
            self._submit_timer.setInterval(max(100, int(poll_after or 150)))
        task_id = str(data.get("task_id", self._submit_task_id) or self._submit_task_id)
        status_val = str(data.get("status", "") or "")
        stage_val = str(data.get("stage", "") or "")
        review_count = int(data.get("review_count", 0) or 0)
        review_pending_group_count = int(
            data.get("review_pending_group_count", self.controller.state.review_pending_group_count)
            or self.controller.state.review_pending_group_count
        )
        review_overflow_count = int(
            data.get("review_overflow_count", self.controller.state.review_overflow_count)
            or self.controller.state.review_overflow_count
        )
        review_total_count = int(
            data.get("review_total_count", self.controller.state.review_total_count)
            or self.controller.state.review_total_count
        )
        review_state = str(data.get("review_state", self.controller.state.review_state) or "none")
        overflow_blocking = bool(data.get("overflow_blocking", False))
        review_disabled = bool(data.get("review_disabled", False))
        review_disabled_reason = str(data.get("review_disabled_reason", "") or "")
        self.controller.update_state(
            task_id=task_id,
            status=status_val or self.controller.state.status,
            stage=stage_val or self.controller.state.stage,
            review_count=review_count,
            review_pending_group_count=review_pending_group_count,
            review_overflow_count=review_overflow_count,
            review_total_count=review_total_count,
            review_state=review_state,
            overflow_blocking=overflow_blocking,
            review_disabled=review_disabled,
            review_disabled_reason=review_disabled_reason,
        )

        if status_val in {"queued", "running"}:
            self.submit_btn.setEnabled(False)
            self._set_status(_TR("Applying your choices..."), state="loading")
            return

        self._stop_submit_polling()
        if stage_val == "review" or review_count > 0 or status_val == "review":
            self.submit_btn.setEnabled(True)
            self.controller.update_state(status="ready", stage="review")
            self._set_status(_TR("Refreshing the remaining review lines..."), state="loading")
            self._reload_review_page(
                group_key=self.controller.state.review_pane_state.selected_group_key
            )
            return

        result_summary = dict(data.get("last_result", {}) or {})
        self.controller.update_state(
            task_id=task_id,
            created_count=int(
                data.get("created_count", result_summary.get("created_count", 0)) or 0
            ),
            updated_count=int(
                data.get("updated_count", result_summary.get("updated_count", 0)) or 0
            ),
            skipped_count=int(
                data.get("skipped_count", result_summary.get("skipped_count", 0)) or 0
            ),
            error_count=int(data.get("error_count", result_summary.get("error_count", 0)) or 0),
            result_entity_counts=dict(data.get("result_entity_counts", {}) or {}),
            result_auto_fix_summary=dict(data.get("result_auto_fix_summary", {}) or {}),
            result_attention_summary=dict(data.get("result_attention_summary", {}) or {}),
            status=status_val or "completed",
            stage=stage_val or "done",
        )
        self.submit_btn.setEnabled(True)
        if status_val == "completed":
            self._set_status("", state="")
            self.finished.emit()
            return
        self._set_status(
            str(
                data.get("error_message", "")
                or _TR("We couldn’t continue with these choices just yet. Please try again.")
            ),
            state="error",
        )

    def _on_submit_error(self, message: str | Exception) -> None:
        self.submit_btn.setEnabled(True)
        if isinstance(message, ApiError):
            if message.code == "IMPORT_REVIEW_CAPACITY_EXCEEDED":
                self.controller.update_state(
                    review_state="emergency_overflow",
                    overflow_blocking=True,
                    review_disabled=True,
                    review_disabled_reason=(
                        message.message
                        or _TR(
                            "This import produced more unresolved review items than the system can safely process in one job."
                        )
                    ),
                )
                self.refresh()
                self._set_status(
                    self.controller.state.review_disabled_reason,
                    state="warning",
                )
                return
            if (
                message.status_code == 409
                and message.code == "IMPORT_REVIEW_DUPLICATE_CONFLICT"
                and isinstance(message.payload, dict)
            ):
                payload = dict(message.payload)
                detail = str(
                    payload.get("detail", "") or _TR("A few lines still need your attention.")
                )
                self._apply_conflicts(
                    list(payload.get("row_conflicts", []) or []),
                    conflict_item_ids=[
                        int(value) for value in list(payload.get("conflict_item_ids", []) or [])
                    ],
                )
                self._set_status(detail, state="warning")
                return
            if message.code == "IMPORT_ACCOUNT_SCOPE_REQUIRED":
                self._set_status(
                    _TR(
                        "Your account is not ready for imports yet. Please contact the agency owner or support."
                    ),
                    state="warning",
                )
                return
            error_text = (
                _TR("We couldn’t continue with these choices just yet. Please try again.")
                if message.status_code >= 500
                else message.message
                or _TR("We couldn’t continue with these choices just yet. Please try again.")
            )
        else:
            error_text = _TR("We couldn’t continue with these choices just yet. Please try again.")
        self._set_status(error_text, state="error")

    def _apply_conflicts(
        self,
        row_conflicts: list[dict[str, Any]],
        *,
        conflict_item_ids: list[int] | None = None,
    ) -> None:
        self._row_conflicts_by_item = map_review_conflicts_to_items(
            item_entries=self._item_entries,
            row_conflicts=row_conflicts,
            conflict_item_ids=conflict_item_ids,
        )
        for item_id, card in self._row_cards.items():
            card_conflict = self._row_conflicts_by_item.get(int(item_id))
            card.error_label.setText(
                format_conflict_message(card_conflict) if card_conflict else ""
            )
        self._refresh_group_table()
        if self._row_conflicts_by_item:
            self._select_item_in_table(next(iter(self._row_conflicts_by_item)))

    def _on_submit_result(self, data: dict[str, Any]) -> None:
        if str(data.get("request_status", "") or "") == "accepted":
            task_id = str(data.get("task_id", "") or "")
            if not task_id:
                self.submit_btn.setEnabled(True)
                self._set_status(
                    _TR("We couldn’t start applying these choices yet. Please try again."),
                    state="error",
                )
                return
            self.controller.update_state(
                task_id=task_id,
                status=str(data.get("status", "running") or "running"),
                stage=str(data.get("stage", "review") or "review"),
                review_count=int(
                    data.get("review_count", self.controller.state.review_count)
                    or self.controller.state.review_count
                ),
                review_pending_group_count=int(
                    data.get(
                        "review_pending_group_count",
                        self.controller.state.review_pending_group_count,
                    )
                    or self.controller.state.review_pending_group_count
                ),
                review_overflow_count=int(
                    data.get("review_overflow_count", self.controller.state.review_overflow_count)
                    or self.controller.state.review_overflow_count
                ),
                review_total_count=int(
                    data.get("review_total_count", self.controller.state.review_total_count)
                    or self.controller.state.review_total_count
                ),
                review_state=str(
                    data.get("review_state", self.controller.state.review_state) or "none"
                ),
                overflow_blocking=bool(data.get("overflow_blocking", False)),
                review_disabled=bool(data.get("review_disabled", False)),
                review_disabled_reason=str(data.get("review_disabled_reason", "") or ""),
            )
            self._set_status(_TR("Applying your choices..."), state="loading")
            self._start_submit_polling(task_id, int(data.get("poll_after_ms", 150) or 150))
            return

        self.submit_btn.setEnabled(True)
        self._row_conflicts_by_item = {}
        self._group_decisions = {}
        self._item_entries = {}
        self._item_entry_cache = {}
        self._item_drafts = {}
        self._row_cards = {}
        still_review, message = apply_final_review_submit_response(self.controller, data)
        if still_review:
            self._set_status(message)
            self.refresh()
            return
        self._set_status("", state="")
        self.finished.emit()


__all__ = ["StepReview", "_ReviewRowCard"]
