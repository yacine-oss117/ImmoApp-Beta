from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.services.api_client_errors import ApiError
from app.utils.i18n import tr_factory
from app.utils.qt_async import run_background_result
from app.views.imports.import_experience import friendly_field_label
from app.views.imports.mapping_field_contract import (
    CLIENT_FIELD_KEYS,
    DEMANDE_FIELD_KEYS,
    LISTING_FIELD_KEYS,
    OFFER_FIELD_KEYS,
)
from app.views.imports.mapping_palette import derive_mapping_palette_state
from app.views.imports.wizard_state import ImportWizardController
from app.widgets.collapsible_section import CollapsibleSection

_TR = tr_factory("ImportWizardStepMapping")

_CLIENT_LABELS = {
    "family_name": _TR("Family Name"),
    "phone": _TR("Phone Number"),
    "remarks": _TR("Notes"),
    "is_vip": _TR("VIP"),
    "status": _TR("Status"),
    "tags": _TR("Tags"),
}
_LISTING_LABELS = {
    "family_name": _TR("Owner Name"),
    "phone": _TR("Owner Phone"),
    "remarks": _TR("Notes"),
    "is_vip": _TR("VIP"),
    "status": _TR("Status"),
}
_DEMANDE_LABELS = {
    "client_id": _TR("Client"),
    "action": _TR("Looking for"),
    "type": _TR("Property Type"),
    "wilaya": _TR("City"),
    "locations": _TR("Preferred Areas"),
    "budget_min": _TR("Minimum Budget"),
    "budget_max": _TR("Maximum Budget"),
    "surface_min": _TR("Minimum Size"),
    "surface_max": _TR("Maximum Size"),
    "beds_min": _TR("Minimum Bedrooms"),
    "floor_min": _TR("Minimum Floor"),
    "floor_max": _TR("Maximum Floor"),
    "furnished": _TR("Furnished"),
    "elevator": _TR("Elevator"),
    "accessibility_required": _TR("Accessibility Required"),
    "remarks": _TR("Notes"),
    "tags": _TR("Tags"),
}
_OFFER_LABELS = {
    "listing_id": _TR("Property"),
    "action": _TR("For"),
    "type": _TR("Property Type"),
    "status": _TR("Status"),
    "wilaya": _TR("City"),
    "location": _TR("Area"),
    "budget": _TR("Budget"),
    "surface": _TR("Size"),
    "beds": _TR("Bedrooms"),
    "floor": _TR("Floor"),
    "furnished": _TR("Furnished"),
    "elevator": _TR("Elevator"),
    "accessibility_supported": _TR("Accessibility Supported"),
    "price_negotiable": _TR("Price Negotiable"),
    "price_flex_pct": _TR("Negotiation Margin %"),
    "remarks": _TR("Notes"),
    "link": _TR("Map Link"),
    "latitude": _TR("Latitude"),
    "longitude": _TR("Longitude"),
}


def _field_rows(keys: tuple[str, ...], labels: dict[str, str]) -> list[tuple[str, str]]:
    return [(key, labels[key]) for key in keys]


CLIENT_FIELDS = _field_rows(CLIENT_FIELD_KEYS, _CLIENT_LABELS)
LISTING_FIELDS = _field_rows(LISTING_FIELD_KEYS, _LISTING_LABELS)
DEMANDE_FIELDS = _field_rows(DEMANDE_FIELD_KEYS, _DEMANDE_LABELS)
OFFER_FIELDS = _field_rows(OFFER_FIELD_KEYS, _OFFER_LABELS)


def _available_fields_for_entity(entity_type: str) -> list[tuple[str, str]]:
    if entity_type == "demande":
        return DEMANDE_FIELDS
    if entity_type == "offer":
        return OFFER_FIELDS
    if entity_type == "listing":
        return LISTING_FIELDS
    return CLIENT_FIELDS


def _palette_mode_for_state(state: object) -> str:
    explicit_mode = str(getattr(state, "mapping_palette_mode", "") or "").strip().lower()
    if explicit_mode in {"same_side_union", "recovery_union"}:
        return explicit_mode
    derived_mode, _candidate_entities = derive_mapping_palette_state(
        bundle_mode=getattr(state, "bundle_mode", "single_entity"),
        topology_side_hint=getattr(state, "topology_side_hint", "unknown"),
        detected_entity=getattr(state, "detected_entity", ""),
        manual_mapping_required=bool(getattr(state, "manual_mapping_required", False)),
        detected_columns=list(getattr(state, "detected_columns", []) or []),
        column_mapping=dict(getattr(state, "column_mapping", {}) or {}),
        sheet_profiles=list(getattr(state, "sheet_profiles", []) or []),
        selected_sheet_name=str(
            (
                getattr(state, "inference_summary", {}).get("selected_sheet_name", "")
                if isinstance(getattr(state, "inference_summary", {}), dict)
                else ""
            )
            or ""
        ),
    )
    return derived_mode


def _available_fields_for_state(state: object) -> list[tuple[str, str]]:
    palette_mode = _palette_mode_for_state(state)
    topology_side_hint = str(getattr(state, "topology_side_hint", "unknown") or "unknown")
    if palette_mode in {"same_side_union", "recovery_union"}:
        if topology_side_hint == "client_side":
            combined = CLIENT_FIELDS + DEMANDE_FIELDS
        else:
            combined = LISTING_FIELDS + OFFER_FIELDS
        deduped: list[tuple[str, str]] = []
        seen: set[str] = set()
        for key, label in combined:
            if key in seen:
                continue
            seen.add(key)
            deduped.append((key, label))
        return deduped
    return _available_fields_for_entity(str(getattr(state, "detected_entity", "") or ""))


class StepMapping(QWidget):
    nextRequested = Signal()
    backRequested = Signal()

    def __init__(self, controller: ImportWizardController) -> None:
        super().__init__()
        self.setObjectName("importStepMapping")
        self.controller = controller
        self._show_all_columns = False
        self._preview_inflight = False
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(10)

        # Header
        header = QVBoxLayout()
        self.title_label = QLabel(_TR("Your columns look good"))
        self.title_label.setObjectName("StepTitle")
        self.subtitle_label = QLabel("")
        self.subtitle_label.setWordWrap(True)
        self.subtitle_label.setObjectName("StepDescription")
        self.summary_label = QLabel("")
        self.summary_label.setWordWrap(True)
        self.summary_label.setObjectName("StepDescription")

        info_box = QFrame()
        info_box.setObjectName("InfoBox")
        info_layout = QVBoxLayout(info_box)
        info_layout.setContentsMargins(12, 10, 12, 10)
        self.info_text = QLabel("")
        self.info_text.setObjectName("StepDescription")
        self.info_text.setWordWrap(True)
        info_layout.addWidget(self.info_text)

        header.addWidget(self.title_label)
        header.addWidget(self.subtitle_label)
        header.addWidget(self.summary_label)
        header.addWidget(info_box)
        self.warning_label = QLabel("")
        self.warning_label.setWordWrap(True)
        self.warning_label.setObjectName("InlineWarning")
        header.addWidget(self.warning_label)
        self._layout.addLayout(header)

        self.detail_section = CollapsibleSection(_TR("Review column details"), collapsible=True)
        splitter = QSplitter(Qt.Orientation.Horizontal)

        self.map_table = QTableWidget()
        self.map_table.setObjectName("importMappingTable")
        self.map_table.setColumnCount(3)
        self.map_table.setHorizontalHeaderLabels(
            [_TR("File column"), _TR("Example from your file"), _TR("Match with")]
        )
        self.map_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.map_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.map_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.map_table.verticalHeader().setVisible(False)
        splitter.addWidget(self.map_table)
        self.detail_section.set_content(splitter)
        self._layout.addWidget(self.detail_section)

        self.show_all_btn = QPushButton(_TR("Show all columns"))
        self.show_all_btn.setObjectName("importMappingShowAllButton")
        self.show_all_btn.setProperty("immoVariant", "ghost")
        self.show_all_btn.clicked.connect(self._toggle_visible_columns)
        self._layout.addWidget(self.show_all_btn, alignment=Qt.AlignmentFlag.AlignLeft)

        self.confirmation_label = QLabel(_TR("Nothing will be added until you confirm."))
        self.confirmation_label.setObjectName("StepDescription")
        self._layout.addWidget(self.confirmation_label)

        # Actions
        actions = QHBoxLayout()
        self.back_btn = QPushButton(_TR("Back"))
        self.back_btn.setObjectName("importMappingBackButton")
        self.back_btn.setProperty("immoVariant", "secondary")
        self.back_btn.clicked.connect(self.backRequested.emit)

        self.next_btn = QPushButton(_TR("Continue"))
        self.next_btn.setObjectName("importMappingContinueButton")
        self.next_btn.setProperty("immoVariant", "primary")
        self.next_btn.clicked.connect(self._validate_and_next)

        actions.addWidget(self.back_btn)
        actions.addStretch()
        actions.addWidget(self.next_btn)
        self._layout.addLayout(actions)

        # Listen to state
        self.controller.stateChanged.connect(self._refresh)

    def _blocking_message(self) -> str:
        state = self.controller.state
        if not bool(state.import_supported):
            return str(state.blocking_message or "")
        if state.bundle_mode == "mixed_blocked":
            return _TR(
                "This file mixes client-side and listing-side rows. Split it into separate imports before continuing."
            )
        return ""

    def _toggle_visible_columns(self) -> None:
        self._show_all_columns = not self._show_all_columns
        self._refresh()

    def _visible_headers(self) -> list[str]:
        state = self.controller.state
        if not bool(state.manual_mapping_required) or self._show_all_columns:
            return list(state.headers)
        low_confidence_headers: list[str] = []
        confidence_by_header = {
            str(col.get("header", "") or ""): float(col.get("confidence", 0.0) or 0.0)
            for col in list(state.detected_columns or [])
            if isinstance(col, dict)
        }
        for header in state.headers:
            confidence = confidence_by_header.get(header, 0.0)
            already_mapped = header in set(state.column_mapping.values())
            if confidence < 0.85 or not already_mapped:
                low_confidence_headers.append(header)
        return low_confidence_headers or list(state.headers)

    def _sample_for_header(self, header: str) -> str:
        for preview_row in list(self.controller.state.preview_rows or []):
            if not isinstance(preview_row, dict):
                continue
            direct_value = preview_row.get(header)
            if str(direct_value or "").strip():
                return str(direct_value)
            for container_key in ("original", "raw_data", "normalized", "normalized_data"):
                container = preview_row.get(container_key)
                if not isinstance(container, dict):
                    continue
                nested_value = container.get(header)
                if str(nested_value or "").strip():
                    return str(nested_value)
        return ""

    def _stored_mapping(self) -> dict[str, str]:
        return {
            str(field_name): str(source_header)
            for field_name, source_header in dict(
                self.controller.state.column_mapping or {}
            ).items()
            if str(field_name or "").strip() and str(source_header or "").strip()
        }

    def _refresh(self) -> None:
        state = self.controller.state
        if state.status != "mapping":
            return
        experience = state.experience_summary
        if experience is not None:
            self.title_label.setText(experience.headline)
            self.subtitle_label.setText(experience.supporting_text)
            self.summary_label.setText(" ".join(experience.automation_points))
            self.info_text.setText(
                _TR(
                    "We matched the columns for you. Continue when you're ready, or review the details below."
                )
                if not bool(state.manual_mapping_required)
                else _TR("Most of your file is ready. Review the columns below, then continue.")
            )
            if _palette_mode_for_state(state) == "recovery_union":
                if str(state.topology_side_hint or "unknown") == "client_side":
                    self.info_text.setText(
                        _TR(
                            "This file may include both clients and requests. We unlocked a few more field choices so you can guide the import safely."
                        )
                    )
                else:
                    self.info_text.setText(
                        _TR(
                            "This file may include both properties and offers. We unlocked a few more field choices so you can guide the import safely."
                        )
                    )
            if str(state.file_model_hint or "unknown") == "client_lead_sheet":
                self.info_text.setText(
                    _TR(
                        "We detected client leads with property preferences. Review the request fields below, then continue."
                    )
                )
            elif str(state.file_model_hint or "unknown") == "listing_inventory":
                self.info_text.setText(
                    _TR(
                        "We detected property listings with offer details. Review the property and offer fields below, then continue."
                    )
                )
        blocked_message = self._blocking_message()
        if blocked_message:
            self.title_label.setText(_TR("This file needs a different import format"))
            self.subtitle_label.setText(blocked_message)
            self.summary_label.clear()
            self.info_text.setText(
                _TR(
                    "Use a combined file instead: clients with requests, or properties with offers."
                )
            )
            self.warning_label.setText(blocked_message)
            self.detail_section.setVisible(False)
            self.show_all_btn.setVisible(False)
            self.confirmation_label.setVisible(False)
            self.next_btn.setEnabled(False)
            self.back_btn.setEnabled(True)
            return
        self.detail_section.setVisible(True)
        self.confirmation_label.setVisible(True)
        self.next_btn.setEnabled(not self._preview_inflight)
        if bool(state.manual_mapping_required):
            reasons = " ".join(str(reason) for reason in state.manual_mapping_reasons if reason)
            summary = state.recoverability_summary or {}
            recoverability_text = ""
            if summary:
                recoverability_text = _TR(
                    " We already handled common formatting where possible. Ready automatically: {auto}. Needs a closer look: {review}. Blocking lines: {blocking}."
                ).format(
                    auto=int(summary.get("auto_recoverable", 0) or 0),
                    review=int(summary.get("review_recoverable", 0) or 0),
                    blocking=int(summary.get("blocking", 0) or 0),
                )
            self.warning_label.setText(
                _TR("A few columns need your attention before we continue.")
                + (f" {reasons}" if reasons else "")
                + recoverability_text
            )
            self.detail_section.expand()
            self.show_all_btn.setVisible(True)
            self.show_all_btn.setText(
                _TR("Show only columns to check")
                if self._show_all_columns
                else _TR("Show all columns")
            )
        else:
            self.warning_label.clear()
            self.detail_section.set_title(_TR("Review column details"))
            self.detail_section.set_collapsed(True)
            self.show_all_btn.setVisible(False)
        price_summary = dict(state.price_dialect_summary or {})
        ambiguous_price_rows = int(price_summary.get("ambiguous_price_row_count", 0) or 0)
        if ambiguous_price_rows > 0:
            warning_text = _TR(
                "Some prices still have more than one possible scale. We will keep them under review until you confirm whether they are written in DZD or local centime-style shorthand."
            )
            if self.warning_label.text():
                self.warning_label.setText(f"{self.warning_label.text()} {warning_text}")
            else:
                self.warning_label.setText(warning_text)

        visible_headers = self._visible_headers()

        available_fields = _available_fields_for_state(state)
        self.map_table.setRowCount(len(visible_headers))

        for row, header in enumerate(visible_headers):
            # File Header
            item_header = QTableWidgetItem(
                header if header else _TR("Column {n}").format(n=row + 1)
            )
            item_header.setFlags(Qt.ItemFlag.ItemIsEnabled)
            item_header.setToolTip(_TR("Original file column: {header}").format(header=header))
            item_header.setData(Qt.ItemDataRole.UserRole, header)
            self.map_table.setItem(row, 0, item_header)

            # Sample Value from preview_rows
            sample = self._sample_for_header(header)

            item_sample = QTableWidgetItem(sample if sample else _TR("No example"))
            item_sample.setFlags(Qt.ItemFlag.ItemIsEnabled)
            if not sample:
                item_sample.setForeground(QBrush(Qt.GlobalColor.gray))
            self.map_table.setItem(row, 1, item_sample)

            # System Field Dropdown
            combo = QComboBox()
            combo.addItem(_TR("-- Ignore Column --"), None)
            for key, label in available_fields:
                combo.addItem(friendly_field_label(key) if key else label, key)
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
            combo.view().setMinimumWidth(220)

            # Smart auto-select logic
            header_lower = header.lower().replace("_", " ").replace("-", " ")
            matched = False
            for i in range(combo.count()):
                field_label = combo.itemText(i).lower()
                field_key = str(combo.itemData(i)).lower()

                # Direct match or fuzzy match
                if (
                    field_key in header_lower
                    or field_label in header_lower
                    or header_lower in field_label
                ):
                    combo.setCurrentIndex(i)
                    matched = True
                    break

            # If we already have a mapping in state, prefer explicit mapping over heuristics.
            selected_field = next(
                (
                    field_name
                    for field_name, source_header in state.column_mapping.items()
                    if source_header == header
                ),
                None,
            )
            if selected_field:
                for i in range(combo.count()):
                    if combo.itemData(i) == selected_field:
                        combo.setCurrentIndex(i)
                        matched = True
                        break

            if not matched:
                combo.setCurrentIndex(0)

            self.map_table.setCellWidget(row, 2, combo)

    def _validate_and_next(self) -> None:
        blocked_message = self._blocking_message()
        if blocked_message:
            self.warning_label.setText(blocked_message)
            return
        if self.controller.state.bundle_mode == "mixed_blocked":
            QMessageBox.warning(
                self,
                _TR("Split File Required"),
                _TR(
                    "This file mixes client-side and listing-side rows. Split it into separate imports before executing."
                ),
            )
            return
        if self._preview_inflight:
            return
        mapping = self._stored_mapping()
        visible_headers: set[str] = set()
        for row in range(self.map_table.rowCount()):
            header_item = self.map_table.item(row, 0)
            if not header_item:
                continue
            header = str(header_item.data(Qt.ItemDataRole.UserRole) or header_item.text() or "")
            if header:
                visible_headers.add(header)
        mapping = {
            field_name: source_header
            for field_name, source_header in mapping.items()
            if source_header not in visible_headers
        }
        selected_headers_by_field: dict[str, list[str]] = {
            field_name: [source_header] for field_name, source_header in mapping.items()
        }
        for row in range(self.map_table.rowCount()):
            header_item = self.map_table.item(row, 0)
            if not header_item:
                continue
            header = str(header_item.data(Qt.ItemDataRole.UserRole) or header_item.text() or "")
            display_header = str(header_item.text() or header)
            combo = self.map_table.cellWidget(row, 2)
            if isinstance(combo, QComboBox):
                field_key = combo.currentData()
                if field_key:
                    field_name = str(field_key)
                    selected_headers_by_field.setdefault(field_name, []).append(display_header)
                    mapping[field_name] = header

        duplicate_assignments = {
            field_name: headers
            for field_name, headers in selected_headers_by_field.items()
            if len(headers) > 1
        }
        if duplicate_assignments:
            duplicates_text = "; ".join(
                f"{friendly_field_label(field_name)}: {', '.join(headers)}"
                for field_name, headers in duplicate_assignments.items()
            )
            self.warning_label.setText(
                _TR(
                    "Each import field can only be matched once. Please fix these duplicates: {duplicates}"
                ).format(duplicates=duplicates_text)
            )
            return

        if not mapping:
            self.warning_label.setText(_TR("Match at least one column before continuing."))
            return

        if not self.controller.state.session_id:
            self.controller.update_state(column_mapping=mapping, status="execute_ready")
            self.nextRequested.emit()
            return

        self.controller.update_state(column_mapping=mapping)
        self._preview_inflight = True
        self.next_btn.setEnabled(False)
        self.back_btn.setEnabled(False)
        self.warning_label.setText("")
        self.info_text.setText(_TR("We’re checking your columns and preparing a quick summary."))
        run_background_result(
            self._request_preview,
            self._handle_preview_success,
            self._handle_preview_error,
            mapping,
        )

    def _request_preview(self, mapping: dict[str, str]) -> dict[str, object]:
        from app.services.api_client import api_post, as_dict

        state = self.controller.state
        response = api_post(
            "import/preview/",
            {
                "session_id": state.session_id,
                "entity_type": state.detected_entity or state.entity_hint,
                "column_mapping": mapping,
            },
        )
        data = as_dict(response)
        return {str(key): value for key, value in data.items()}

    def _handle_preview_success(self, data: dict[str, object]) -> None:
        self._preview_inflight = False
        self.next_btn.setEnabled(True)
        self.back_btn.setEnabled(True)

        entity_counts_raw = data.get("entity_counts", {})
        auto_fix_summary_raw = data.get("auto_fix_summary", {})
        attention_summary_raw = data.get("attention_summary", {})
        manual_mapping_required = bool(data.get("manual_mapping_required", False))
        manual_mapping_reasons_raw = data.get("manual_mapping_reasons", [])
        recoverability_summary_raw = data.get("recoverability_summary", {})
        preview_rows_raw = data.get("preview_rows", [])
        stats_raw = data.get("stats", {})
        mapping_palette_mode = str(data.get("mapping_palette_mode", "") or "")
        file_model_hint = str(data.get("file_model_hint", "") or "")
        dominant_side = str(data.get("dominant_side", "") or "")
        dominant_side_confidence = data.get("dominant_side_confidence", 0.0)
        row_mixed_review_count = data.get("row_mixed_review_count", 0)
        semantic_projection_conflicts_raw = data.get("semantic_projection_conflicts", [])
        price_dialect_summary_raw = data.get("price_dialect_summary", {})
        dominant_side_confidence_value = (
            float(dominant_side_confidence)
            if isinstance(dominant_side_confidence, (int, float))
            else 0.0
        )
        row_mixed_review_count_value = (
            int(row_mixed_review_count) if isinstance(row_mixed_review_count, (int, float)) else 0
        )

        self.controller.update_state(
            preview_rows=list(preview_rows_raw) if isinstance(preview_rows_raw, list) else [],
            stats=dict(stats_raw) if isinstance(stats_raw, dict) else {},
            manual_mapping_required=manual_mapping_required,
            manual_mapping_reasons=(
                [str(reason) for reason in manual_mapping_reasons_raw]
                if isinstance(manual_mapping_reasons_raw, list)
                else []
            ),
            recoverability_summary=(
                {
                    str(key): int(value)
                    for key, value in recoverability_summary_raw.items()
                    if isinstance(value, (int, float))
                }
                if isinstance(recoverability_summary_raw, dict)
                else {}
            ),
            preview_entity_counts=(
                {
                    str(key): int(value)
                    for key, value in entity_counts_raw.items()
                    if isinstance(value, (int, float))
                }
                if isinstance(entity_counts_raw, dict)
                else {}
            ),
            preview_auto_fix_summary=(
                {
                    str(key): int(value)
                    for key, value in auto_fix_summary_raw.items()
                    if isinstance(value, (int, float))
                }
                if isinstance(auto_fix_summary_raw, dict)
                else {}
            ),
            preview_attention_summary=(
                {
                    str(key): int(value)
                    for key, value in attention_summary_raw.items()
                    if isinstance(value, (int, float))
                }
                if isinstance(attention_summary_raw, dict)
                else {}
            ),
            mapping_palette_mode=(
                mapping_palette_mode
                if mapping_palette_mode in {"entity_only", "same_side_union", "recovery_union"}
                else self.controller.state.mapping_palette_mode
            ),
            file_model_hint=file_model_hint or self.controller.state.file_model_hint,
            dominant_side=dominant_side or self.controller.state.dominant_side,
            dominant_side_confidence=dominant_side_confidence_value,
            row_mixed_review_count=row_mixed_review_count_value,
            semantic_projection_conflicts=(
                [str(value) for value in semantic_projection_conflicts_raw]
                if isinstance(semantic_projection_conflicts_raw, list)
                else list(self.controller.state.semantic_projection_conflicts or [])
            ),
            price_dialect_summary=(
                {str(key): value for key, value in price_dialect_summary_raw.items()}
                if isinstance(price_dialect_summary_raw, dict)
                else dict(self.controller.state.price_dialect_summary or {})
            ),
            status="mapping" if manual_mapping_required else "execute_ready",
        )
        if manual_mapping_required:
            return
        self.nextRequested.emit()

    def _handle_preview_error(self, error: Exception) -> None:
        self._preview_inflight = False
        self.next_btn.setEnabled(True)
        self.back_btn.setEnabled(True)
        if isinstance(error, ApiError):
            if error.status_code == 409:
                message = error.message or _TR("A few columns still need your attention.")
            elif error.status_code >= 500:
                message = _TR("We couldn’t check these columns just yet. Please try again.")
            else:
                message = error.message or _TR("We couldn’t check these columns just yet.")
        else:
            message = _TR("We couldn’t check these columns just yet. Please try again.")
        self.warning_label.setText(message)
        self.info_text.setText(
            _TR("Review the suggested columns below, then continue when you’re ready.")
        )
