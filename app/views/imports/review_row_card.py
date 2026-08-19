"""Row-card widget for importer review editing."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.utils.i18n import tr_factory
from app.views.imports.import_experience import friendly_field_label, ordered_editable_fields
from app.views.imports.review_actions import legacy_review_action, normalize_review_action
from app.widgets.collapsible_section import CollapsibleSection

_TR = tr_factory("ImportWizardStepReview")


class _ReviewRowCard(QFrame):
    bulkOperationQueued = Signal(dict)

    def __init__(
        self,
        entry: dict[str, Any],
        *,
        allowed_entity_types: list[str] | None = None,
    ) -> None:
        super().__init__()
        self.entry = entry
        requested_options = list(entry.get("reclassify_options", []) or [])
        self.allowed_entity_types = requested_options or list(allowed_entity_types or [])
        self._field_widgets: dict[str, QCheckBox | QLineEdit] = {}
        self._field_defaults: dict[str, Any] = {}
        self.setObjectName("ImportReviewCard")
        self.setProperty("immoRole", "workspaceEditor")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        row_num = int(entry.get("row", 0) or 0)
        entity_type = str(entry.get("entity_type", "") or "")
        header = QLabel(_TR("Line {row}").format(row=row_num))
        header.setObjectName("StepDescription")
        layout.addWidget(header)

        issue_title = str(entry.get("issue_title", "") or _TR("Needs attention"))
        issue_summary = str(
            entry.get("issue_summary", "") or _TR("Please confirm this line before we continue.")
        )
        issue_label = QLabel(issue_title)
        issue_label.setObjectName("StepDescription")
        layout.addWidget(issue_label)

        summary_label = QLabel(issue_summary)
        summary_label.setWordWrap(True)
        layout.addWidget(summary_label)

        if entity_type:
            entity_label = QLabel(
                _TR("Import as: {entity}").format(entity=entity_type.replace("_", " "))
            )
            entity_label.setWordWrap(True)
            layout.addWidget(entity_label)

        recovered_fields = list(entry.get("recovered_fields", []) or [])
        if recovered_fields:
            recovered_lines = []
            for recovered in recovered_fields:
                field_name = friendly_field_label(str(recovered.get("field", "") or "value"))
                field_value = str(recovered.get("value", "") or "")
                recovered_lines.append(f"{field_name}: {field_value}")
            recovered_label = QLabel(
                _TR("Recovered fields: {items}").format(items="; ".join(recovered_lines))
            )
            recovered_label.setWordWrap(True)
            layout.addWidget(recovered_label)

        recovery_candidates = list(entry.get("recovery_candidates", []) or [])
        if recovery_candidates:
            candidate_lines = []
            for candidate in recovery_candidates[:4]:
                candidate_field = friendly_field_label(
                    str(candidate.get("field", "") or _TR("value"))
                )
                candidate_label = str(candidate.get("candidate_label", "") or "")
                candidate_lines.append(f"{candidate_field}: {candidate_label}")
            candidate_label_widget = QLabel(
                _TR("Suggested matches: {items}").format(items="; ".join(candidate_lines))
            )
            candidate_label_widget.setWordWrap(True)
            layout.addWidget(candidate_label_widget)

        blocking_reasons = list(entry.get("blocking_reasons", []) or [])
        if blocking_reasons:
            blocking_label = QLabel(
                _TR("Blocking reasons: {reasons}").format(
                    reasons="; ".join(str(reason) for reason in blocking_reasons if reason)
                )
            )
            blocking_label.setWordWrap(True)
            layout.addWidget(blocking_label)

        controls = QHBoxLayout()
        controls.setSpacing(8)

        self.entity_combo = QComboBox()
        self.entity_combo.setObjectName("importReviewEntityCombo")
        current_entity_type = entity_type or (
            self.allowed_entity_types[0] if self.allowed_entity_types else ""
        )
        if self.allowed_entity_types:
            for option in self.allowed_entity_types:
                self.entity_combo.addItem(option.replace("_", " ").title(), option)
            selected_entity_index = self.entity_combo.findData(current_entity_type)
            if selected_entity_index >= 0:
                self.entity_combo.setCurrentIndex(selected_entity_index)
        else:
            self.entity_combo.addItem(current_entity_type or _TR("Unknown"), current_entity_type)
            self.entity_combo.setEnabled(False)

        self.action_combo = QComboBox()
        self.action_combo.setObjectName("importReviewActionCombo")
        self.action_combo.addItem(_TR("Choose an option"), "")
        self.action_combo.addItem(_TR("Add as new"), "create")
        if entry.get("candidate_matches"):
            self.action_combo.addItem(_TR("Use existing record"), "update")
        self.action_combo.addItem(_TR("Keep for later"), "review")
        self.action_combo.addItem(_TR("Do not import this line"), "skip")

        self.candidate_combo = QComboBox()
        self.candidate_combo.setObjectName("importReviewCandidateCombo")
        self.candidate_combo.addItem(_TR("Choose a matching record"), 0)
        for candidate in list(entry.get("candidate_matches", []) or []):
            confidence = float(candidate.get("match_confidence", 0.0) or 0.0)
            label = _TR("{name} ({phone}) score {score:.2f}").format(
                name=str(candidate.get("family_name", "") or _TR("Unknown")),
                phone=str(candidate.get("phone", "") or _TR("No phone")),
                score=confidence,
            )
            self.candidate_combo.addItem(label, int(candidate.get("id", 0) or 0))
        self.candidate_combo.setEnabled(False)

        self.action_combo.currentIndexChanged.connect(self._sync_candidate_enabled)
        self.candidate_combo.currentIndexChanged.connect(self._refresh_candidate_diff)

        controls.addWidget(QLabel(_TR("Import as")))
        controls.addWidget(self.entity_combo, 1)
        controls.addWidget(QLabel(_TR("What would you like to do?")))
        controls.addWidget(self.action_combo, 1)
        controls.addWidget(QLabel(_TR("Matching record")))
        controls.addWidget(self.candidate_combo, 1)
        layout.addLayout(controls)

        self.candidate_scope_label = QLabel("")
        self.candidate_scope_label.setWordWrap(True)
        layout.addWidget(self.candidate_scope_label)

        self.hint_label = QLabel("")
        self.hint_label.setWordWrap(True)
        layout.addWidget(self.hint_label)

        self.diff_label = QLabel("")
        self.diff_label.setWordWrap(True)
        layout.addWidget(self.diff_label)

        self.conflict_label = QLabel("")
        self.conflict_label.setWordWrap(True)
        layout.addWidget(self.conflict_label)

        self.form_widget = QWidget()
        self.form_layout = QFormLayout(self.form_widget)
        self.form_layout.setSpacing(8)
        self.form_layout.setHorizontalSpacing(10)
        self._build_field_editors()
        layout.addWidget(self.form_widget)

        quick_fix_actions = list(entry.get("quick_fix_actions", []) or [])
        if quick_fix_actions:
            quick_fix_layout = QHBoxLayout()
            quick_fix_layout.addWidget(QLabel(_TR("Suggested fixes")))
            for quick_fix in quick_fix_actions[:4]:
                button = QPushButton(str(quick_fix.get("label", _TR("Apply")) or _TR("Apply")))
                button.clicked.connect(
                    lambda _checked=False, payload=dict(quick_fix): self._apply_quick_fix(payload)
                )
                quick_fix_layout.addWidget(button)
            quick_fix_layout.addStretch()
            layout.addLayout(quick_fix_layout)

        bulk_fix_groups = list(entry.get("bulk_fix_groups", []) or [])
        if bulk_fix_groups:
            bulk_fix_layout = QHBoxLayout()
            bulk_fix_layout.addWidget(QLabel(_TR("Apply to similar lines")))
            for group in bulk_fix_groups[:3]:
                label = _TR("Apply to {count} similar lines").format(
                    count=int(group.get("occurrence_count", 0) or 0)
                )
                button = QPushButton(label)
                button.clicked.connect(
                    lambda _checked=False, payload=dict(group): self._queue_bulk_fix(payload)
                )
                bulk_fix_layout.addWidget(button)
            bulk_fix_layout.addStretch()
            layout.addLayout(bulk_fix_layout)

        self.technical_editor = QPlainTextEdit()
        self.technical_editor.setObjectName("ImportReviewJsonEditor")
        self.technical_editor.setReadOnly(True)
        self.technical_editor.setMinimumHeight(120)
        self.technical_editor.setPlainText(
            json.dumps(
                entry.get("normalized_data", entry.get("data", {})),
                ensure_ascii=True,
                indent=2,
                sort_keys=True,
            )
        )
        self.technical_section = CollapsibleSection(_TR("View technical details"))
        self.technical_section.set_content(self.technical_editor)
        self.technical_section.set_collapsed(True)
        layout.addWidget(self.technical_section)
        self.editor = self.technical_editor

        self.error_label = QLabel("")
        self.error_label.setObjectName("InlineError")
        self.error_label.setWordWrap(True)
        layout.addWidget(self.error_label)

        self._apply_suggestion()
        self._apply_candidate_scope_hint()
        self._sync_candidate_enabled()
        if bool(entry.get("immutable_conflict", False)):
            self.conflict_label.setText(
                _TR(
                    "Some information conflicts with the selected existing record. Please choose another option."
                )
            )

    def set_interaction_enabled(self, enabled: bool) -> None:
        self.entity_combo.setEnabled(enabled and self.entity_combo.count() > 0)
        self.action_combo.setEnabled(enabled)
        self.candidate_combo.setEnabled(
            enabled
            and normalize_review_action(str(self.action_combo.currentData() or ""))
            == "update_existing"
        )
        for widget in self._field_widgets.values():
            widget.setEnabled(enabled)
        for button in self.findChildren(QPushButton):
            button.setEnabled(enabled)

    def export_draft(self) -> dict[str, Any]:
        return {
            "action": str(self.action_combo.currentData() or ""),
            "entity_type": str(self.entity_combo.currentData() or ""),
            "existing_id": int(self.candidate_combo.currentData() or 0),
            "payload": self._current_payload(),
        }

    def apply_draft(self, draft: Mapping[str, Any]) -> None:
        entity_type = str(draft.get("entity_type", "") or "")
        if entity_type:
            entity_index = self.entity_combo.findData(entity_type)
            if entity_index >= 0:
                self.entity_combo.setCurrentIndex(entity_index)
        action = str(draft.get("action", "") or "")
        action_index = self.action_combo.findData(action)
        if action_index >= 0:
            self.action_combo.setCurrentIndex(action_index)
        existing_id = int(draft.get("existing_id", 0) or 0)
        if existing_id > 0:
            candidate_index = self.candidate_combo.findData(existing_id)
            if candidate_index >= 0:
                self.candidate_combo.setCurrentIndex(candidate_index)
        payload = dict(draft.get("payload", {}) or {})
        for field_name, value in payload.items():
            self._set_field_value(str(field_name), value)
        self._current_payload()
        self._sync_candidate_enabled()
        self.error_label.clear()

    def _build_field_editors(self) -> None:
        payload = dict(self.entry.get("normalized_data", self.entry.get("data", {})) or {})
        entity_type = str(self.entry.get("entity_type", "") or "")
        for field_name in ordered_editable_fields(entity_type, payload):
            value = payload.get(field_name)
            self._field_defaults[field_name] = value
            widget: QCheckBox | QLineEdit
            if isinstance(value, bool):
                widget = QCheckBox()
                widget.setChecked(bool(value))
            else:
                widget = QLineEdit()
                widget.setObjectName(f"importReviewField_{field_name}")
                if isinstance(value, list):
                    widget.setText(", ".join(str(item) for item in value))
                elif value is None:
                    widget.setText("")
                else:
                    widget.setText(str(value))
            self._field_widgets[field_name] = widget
            self.form_layout.addRow(friendly_field_label(field_name), widget)

    def _current_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        for field_name, widget in self._field_widgets.items():
            default = self._field_defaults.get(field_name)
            if isinstance(widget, QCheckBox):
                payload[field_name] = widget.isChecked()
                continue
            if isinstance(widget, QLineEdit):
                text = widget.text().strip()
                if isinstance(default, list):
                    payload[field_name] = [part.strip() for part in text.split(",") if part.strip()]
                elif isinstance(default, bool):
                    payload[field_name] = text.lower() in {"1", "true", "yes", "on"}
                elif isinstance(default, int):
                    payload[field_name] = int(text) if text else 0
                elif isinstance(default, float):
                    payload[field_name] = float(text) if text else 0.0
                else:
                    payload[field_name] = text
        self.technical_editor.setPlainText(
            json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True)
        )
        return payload

    def _set_field_value(self, field_name: str, value: Any) -> None:
        widget = self._field_widgets.get(field_name)
        if widget is None:
            return
        if isinstance(widget, QCheckBox):
            widget.setChecked(bool(value))
            return
        if isinstance(widget, QLineEdit):
            if isinstance(value, list):
                widget.setText(", ".join(str(item) for item in value))
            else:
                widget.setText("" if value is None else str(value))

    def _apply_quick_fix(self, quick_fix: dict[str, Any]) -> None:
        field_name = str(quick_fix.get("field", "") or "").strip()
        candidate_value = quick_fix.get("candidate_value")
        if not field_name or candidate_value in {None, ""}:
            return
        self._set_field_value(field_name, candidate_value)
        self._current_payload()
        self.error_label.setText("")

    def _queue_bulk_fix(self, group: dict[str, Any]) -> None:
        operation = {
            "operation": "replace_value_in_import",
            "field": str(group.get("field", "") or ""),
            "source_value": str(group.get("source_value", "") or ""),
            "replacement_value": group.get("suggested_candidate_value"),
            "target_rows": list(group.get("target_rows", []) or []),
            "group_key": str(group.get("group_key", "") or ""),
        }
        self.bulkOperationQueued.emit(operation)
        replacement = str(
            group.get("suggested_candidate_label", "") or group.get("suggested_candidate_value", "")
        )
        self.error_label.setText(
            _TR("Queued: use {replacement} on similar lines when you continue.").format(
                replacement=replacement or _TR("this value")
            )
        )

    def _apply_suggestion(self) -> None:
        suggested_action = legacy_review_action(str(self.entry.get("suggested_action", "") or ""))
        suggested_existing_id = int(self.entry.get("suggested_existing_id", 0) or 0)
        suggested_confidence = float(self.entry.get("suggested_confidence", 0.0) or 0.0)
        suggested_reasons = ", ".join(
            str(v) for v in list(self.entry.get("suggested_reasons", []) or []) if v
        )
        if suggested_action:
            idx = self.action_combo.findData(suggested_action)
            if idx >= 0:
                self.action_combo.setCurrentIndex(idx)
        if suggested_existing_id > 0:
            idx = self.candidate_combo.findData(suggested_existing_id)
            if idx >= 0:
                self.candidate_combo.setCurrentIndex(idx)
        if (
            normalize_review_action(suggested_action) == "update_existing"
            and suggested_existing_id > 0
        ):
            message = _TR("Suggested: use the matching record (confidence {score:.2f}).").format(
                score=suggested_confidence
            )
            if suggested_reasons:
                message = f"{message} {suggested_reasons}."
            self.hint_label.setText(message)
        elif suggested_existing_id > 0:
            message = _TR(
                "Suggested: keep this for a quick review before updating a matching record."
            )
            if suggested_reasons:
                message = f"{message} {suggested_reasons}."
            self.hint_label.setText(message)

    def _apply_candidate_scope_hint(self) -> None:
        candidate_matches = list(self.entry.get("candidate_matches", []) or [])
        candidate_total_count = max(
            int(self.entry.get("candidate_total_count", 0) or 0),
            len(candidate_matches),
        )
        candidate_matches_truncated = bool(
            self.entry.get("candidate_matches_truncated", False)
        ) or candidate_total_count > len(candidate_matches)
        if not candidate_matches_truncated or candidate_total_count <= len(candidate_matches):
            self.candidate_scope_label.clear()
            return
        self.candidate_scope_label.setText(
            _TR(
                "Showing {shown} of {total} matching records. Keep this line for review if you need a wider check."
            ).format(
                shown=len(candidate_matches),
                total=candidate_total_count,
            )
        )

    def _sync_candidate_enabled(self) -> None:
        self.candidate_combo.setEnabled(
            normalize_review_action(str(self.action_combo.currentData() or "")) == "update_existing"
        )
        self._refresh_candidate_diff()

    def _refresh_candidate_diff(self) -> None:
        candidate_matches = list(self.entry.get("candidate_matches", []) or [])
        if not candidate_matches:
            self.diff_label.clear()
            return
        selected_index = max(0, self.candidate_combo.currentIndex() - 1)
        if selected_index >= len(candidate_matches):
            self.diff_label.clear()
            return
        selected_candidate = dict(candidate_matches[selected_index] or {})
        field_diff = dict(selected_candidate.get("field_diff", {}) or {})
        changed_mutable = list(field_diff.get("changed_mutable", []) or [])
        changed_immutable = list(field_diff.get("changed_immutable", []) or [])
        if not changed_mutable and not changed_immutable:
            field_diffs = list(selected_candidate.get("field_diffs", []) or [])
        else:
            field_diffs = changed_mutable + changed_immutable
        if not field_diffs:
            self.diff_label.clear()
            return
        parts: list[str] = []
        for diff in field_diffs:
            field = friendly_field_label(str(diff.get("field", "") or "value"))
            incoming = str(diff.get("incoming", diff.get("normalized", "")) or "")
            existing = str(diff.get("existing", diff.get("current", "")) or "")
            parts.append(
                _TR("{field}: imported '{incoming}' vs existing '{existing}'").format(
                    field=field,
                    incoming=incoming,
                    existing=existing,
                )
            )
        self.diff_label.setText(_TR("Please compare: {parts}").format(parts="; ".join(parts)))

    def to_payload(self) -> tuple[dict[str, Any] | None, str | None]:
        row_num = int(self.entry.get("row", 0) or 0)
        action = str(self.action_combo.currentData() or "")
        normalized_action = normalize_review_action(action)
        candidate_matches = list(self.entry.get("candidate_matches", []) or [])
        if not action:
            return (
                None,
                _TR(
                    "Line {row}: choose whether to add it, use the existing record, keep it for later, or skip it."
                ).format(row=row_num),
            )

        try:
            payload = self._current_payload()
        except ValueError:
            return (
                None,
                _TR("Line {row}: please check the numeric fields before continuing.").format(
                    row=row_num
                ),
            )
        result: dict[str, Any] = {
            "item_id": int(self.entry.get("item_id", 0) or 0),
            "group_key": str(self.entry.get("group_key", "") or ""),
            "row": row_num,
            "action": action,
            "payload": payload,
            "entity_type": str(self.entity_combo.currentData() or ""),
        }
        if normalized_action == "update_existing":
            if bool(self.entry.get("immutable_conflict", False)):
                return (
                    None,
                    _TR(
                        "Line {row}: conflicting information blocks updating this matching record."
                    ).format(row=row_num),
                )
            existing_id = int(self.candidate_combo.currentData() or 0)
            if existing_id <= 0:
                return (
                    None,
                    _TR("Line {row}: choose the matching record you want to use.").format(
                        row=row_num
                    ),
                )
            selected_index = max(0, self.candidate_combo.currentIndex() - 1)
            selected_candidate = (
                candidate_matches[selected_index] if selected_index < len(candidate_matches) else {}
            )
            row_version = int(selected_candidate.get("row_version", 0) or 0)
            if row_version <= 0:
                return (
                    None,
                    _TR(
                        "Line {row}: the selected matching record is missing version information."
                    ).format(row=row_num),
                )
            result["existing_id"] = existing_id
            result["row_version"] = row_version
        return result, None


__all__ = ["_ReviewRowCard"]
