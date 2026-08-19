"""
UI builder for ListingsTabV2.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from app.delegates.action_delegate import ActionDelegate
from app.utils.i18n import tr_factory
from app.views.listing_sql_model import ListingSQLModel
from app.views.tree_view_helpers import apply_column_widths, configure_tree
from app.widgets.collapsible_section import CollapsibleSection
from app.widgets.collapsible_splitter import CollapsibleSplitter
from app.widgets.notice_banner import NoticeBanner

_TR = tr_factory("ListingsTabUi")


@dataclass(frozen=True)
class ListingFormWidgets:
    """Widgets for the listing form section."""

    owner_name: QLineEdit
    phone: QLineEdit
    is_vip: QComboBox
    remarks: QLineEdit


@dataclass(frozen=True)
class ListingsTabUi:
    """All widgets composing the ListingsTabV2 UI."""

    listing_section: CollapsibleSection
    form: ListingFormWidgets
    offers_container: QWidget
    offers_layout: QVBoxLayout
    add_offer_btn: QPushButton
    save_btn: QPushButton
    clear_btn: QPushButton
    expand_all_btn: QPushButton
    import_btn: QPushButton
    empty_add_btn: QPushButton
    empty_import_btn: QPushButton
    empty_clear_btn: QPushButton
    search_bar: QLineEdit
    tree: QTreeView
    splitter: CollapsibleSplitter
    empty_state: QFrame
    empty_title: QLabel
    empty_text: QLabel
    notice_banner: NoticeBanner
    details_panel: QWidget
    details_label: QLabel
    coords_label: QLabel
    open_map_btn: QPushButton
    action_delegate: ActionDelegate


def build_listings_tab_ui(parent: QWidget, model: ListingSQLModel) -> ListingsTabUi:
    """Build and layout the Listings tab UI."""
    parent.setObjectName("listingsTab")
    main_layout = QVBoxLayout(parent)
    main_layout.setContentsMargins(12, 12, 12, 12)
    main_layout.setSpacing(12)

    listing_section, form = _build_listing_section(parent)

    offers_container = QWidget(parent)
    offers_layout = QVBoxLayout(offers_container)
    offers_layout.setContentsMargins(0, 0, 0, 0)
    offers_layout.setSpacing(10)

    add_offer_btn = QPushButton(_TR("+ Add Offer"))
    add_offer_btn.setObjectName("listingsAddOfferButton")
    add_offer_btn.setProperty("immoVariant", "secondary")
    add_offer_btn.setMaximumWidth(150)
    add_offer_btn.setAccessibleName(_TR("Add offer"))

    save_btn = QPushButton(_TR("Save Property"))
    save_btn.setObjectName("listingsSaveButton")
    save_btn.setShortcut("Ctrl+S")
    save_btn.setToolTip(_TR("Save listing and all offers (Ctrl+S)"))
    save_btn.setAccessibleName(_TR("Save property"))
    save_btn.setProperty("immoVariant", "primary")

    clear_btn = QPushButton(_TR("Clear Form"))
    clear_btn.setObjectName("listingsClearButton")
    clear_btn.setShortcut("Escape")
    clear_btn.setToolTip(_TR("Clear form (Esc)"))
    clear_btn.setAccessibleName(_TR("Clear form"))
    clear_btn.setProperty("immoVariant", "ghost")

    filter_row = QHBoxLayout()

    expand_all_btn = QPushButton(_TR("⏬"))
    expand_all_btn.setObjectName("listingsExpandAllButton")
    expand_all_btn.setToolTip(_TR("Expand All / Collapse All Listings"))
    expand_all_btn.setAccessibleName(_TR("Expand or collapse all listings"))
    expand_all_btn.setProperty("immoVariant", "ghost")
    expand_all_btn.setMinimumWidth(44)

    import_btn = QPushButton(_TR("📥 Import"))
    import_btn.setObjectName("listingsImportButton")
    import_btn.setToolTip(_TR("Import listings from Excel/CSV/ODS"))
    import_btn.setProperty("immoVariant", "secondary")
    import_btn.setAccessibleName(_TR("Import properties"))

    search_bar = QLineEdit()
    search_bar.setObjectName("listingsSearchInput")
    search_bar.setPlaceholderText(_TR("Search: Owner, Phone, Area, Type... (Ctrl+F)"))
    search_bar.setAccessibleName(_TR("Property search"))
    search_bar.setClearButtonEnabled(True)

    filter_row.addWidget(expand_all_btn)
    filter_row.addWidget(import_btn)
    filter_row.addWidget(QLabel(_TR("Search:")))
    filter_row.addWidget(search_bar, 2)

    tree = QTreeView(parent)
    tree.setObjectName("listingsTree")
    tree.setAccessibleName(_TR("Properties tree"))
    tree.setAccessibleDescription(_TR("Property and offers tree view"))
    tree.setModel(model)
    configure_tree(tree)
    apply_column_widths(
        tree, "listings_tab", [220, 130, 100, 70, 180, 60, 90, 120, 80, 70, 130, 130, 160]
    )

    action_delegate = ActionDelegate(tree)
    tree.setItemDelegateForColumn(12, action_delegate)

    details_panel = QWidget(parent)
    details_panel.setObjectName("listingsDetailsPanel")
    details_panel.setProperty("immoCard", True)
    details_panel.setMinimumWidth(0)
    details_panel.setMaximumWidth(420)
    details_layout = QVBoxLayout(details_panel)
    details_layout.setContentsMargins(8, 8, 8, 8)
    details_layout.setSpacing(6)

    details_title = QLabel(_TR("Property Map Preview"))
    details_title.setAccessibleName(_TR("Map preview title"))
    details_title.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

    details_label = QLabel(_TR("Select an offer to view its location."))
    details_label.setObjectName("listingsDetailsLabel")
    details_label.setAccessibleName(_TR("Map preview selection label"))
    details_label.setWordWrap(True)
    details_label.setProperty("immoEmptyState", True)

    coords_label = QLabel(_TR("No coordinates loaded."))
    coords_label.setObjectName("listingsCoordsLabel")
    coords_label.setAccessibleName(_TR("Map preview coordinates"))
    coords_label.setWordWrap(True)
    coords_label.setProperty("immoMuted", True)

    open_map_btn = QPushButton(_TR("Open Map"))
    open_map_btn.setObjectName("listingsOpenMapButton")
    open_map_btn.setAccessibleName(_TR("Open map"))
    open_map_btn.setEnabled(False)

    details_layout.addWidget(details_title)
    details_layout.addWidget(details_label)
    details_layout.addWidget(coords_label)
    details_layout.addStretch()
    details_layout.addWidget(open_map_btn)

    splitter = CollapsibleSplitter(
        Qt.Orientation.Horizontal,
        parent,
        settings_key="listings_tab/map_panel",
        panel_index=1,
        collapsed_default=True,
    )
    splitter.addWidget(tree)
    splitter.addWidget(details_panel)
    splitter.setStretchFactor(0, 3)
    splitter.setStretchFactor(1, 1)
    splitter.setCollapsible(1, True)

    editor_card = QFrame(parent)
    editor_card.setObjectName("listingsEditorCard")
    editor_card.setProperty("immoCard", True)
    editor_layout = QVBoxLayout(editor_card)
    editor_layout.setContentsMargins(12, 12, 12, 12)
    editor_layout.setSpacing(8)

    editor_body = QWidget(editor_card)
    editor_body.setObjectName("listingsEditorBody")
    editor_body_layout = QVBoxLayout(editor_body)
    editor_body_layout.setContentsMargins(0, 0, 0, 0)
    editor_body_layout.setSpacing(10)
    editor_body_layout.addWidget(listing_section)
    editor_body_layout.addWidget(offers_container)

    action_footer = QWidget(editor_body)
    action_footer_layout = QHBoxLayout(action_footer)
    action_footer_layout.setContentsMargins(0, 2, 0, 2)
    action_footer_layout.setSpacing(8)
    action_footer_layout.addWidget(add_offer_btn)
    action_footer_layout.addStretch()
    action_footer_layout.addWidget(save_btn)
    action_footer_layout.addWidget(clear_btn)
    editor_body_layout.addWidget(action_footer)
    editor_body_layout.addStretch()

    editor_scroll = QScrollArea(editor_card)
    editor_scroll.setWidgetResizable(True)
    editor_scroll.setFrameShape(QFrame.Shape.NoFrame)
    editor_scroll.setWidget(editor_body)
    editor_scroll.setProperty("immoRole", "editorScroll")
    editor_layout.addWidget(editor_scroll, 1)

    results_card = QFrame(parent)
    results_card.setObjectName("listingsResultsCard")
    results_card.setProperty("immoCard", True)
    results_layout = QVBoxLayout(results_card)
    results_layout.setContentsMargins(12, 12, 12, 12)
    results_layout.setSpacing(10)
    notice_banner = NoticeBanner(results_card)
    results_layout.addWidget(notice_banner)
    results_layout.addLayout(filter_row)
    empty_state = QFrame(results_card)
    empty_state.setObjectName("listingsEmptyState")
    empty_state.setProperty("immoRole", "workspaceEditor")
    empty_layout = QVBoxLayout(empty_state)
    empty_layout.setContentsMargins(12, 10, 12, 10)
    empty_layout.setSpacing(4)
    empty_title = QLabel(_TR("No properties yet"))
    empty_title.setObjectName("StepDescription")
    empty_text = QLabel(
        _TR("Use the form above to add a property, or use the Import button in the toolbar.")
    )
    empty_text.setWordWrap(True)
    empty_add_btn = QPushButton(_TR("Add property"))
    empty_add_btn.setObjectName("listingsEmptyAddButton")
    empty_add_btn.setProperty("immoVariant", "primary")
    empty_add_btn.setVisible(False)
    empty_import_btn = QPushButton(_TR("Import file"))
    empty_import_btn.setObjectName("listingsEmptyImportButton")
    empty_import_btn.setProperty("immoVariant", "secondary")
    empty_import_btn.setVisible(False)
    empty_clear_btn = QPushButton(_TR("Clear search"))
    empty_clear_btn.setObjectName("listingsEmptyClearButton")
    empty_clear_btn.setProperty("immoVariant", "secondary")
    empty_clear_btn.setVisible(False)
    empty_layout.addWidget(empty_title)
    empty_layout.addWidget(empty_text)
    empty_layout.addWidget(empty_clear_btn)
    empty_state.setVisible(False)
    results_layout.addWidget(empty_state)
    results_layout.addWidget(splitter, 1)

    main_layout.addWidget(editor_card)
    main_layout.addWidget(results_card, 1)

    parent.setTabOrder(form.owner_name, form.phone)
    parent.setTabOrder(form.phone, form.is_vip)
    parent.setTabOrder(form.is_vip, form.remarks)
    parent.setTabOrder(form.remarks, add_offer_btn)
    parent.setTabOrder(add_offer_btn, save_btn)
    parent.setTabOrder(save_btn, clear_btn)
    parent.setTabOrder(clear_btn, search_bar)
    parent.setTabOrder(search_bar, tree)

    return ListingsTabUi(
        listing_section=listing_section,
        form=form,
        offers_container=offers_container,
        offers_layout=offers_layout,
        add_offer_btn=add_offer_btn,
        save_btn=save_btn,
        clear_btn=clear_btn,
        expand_all_btn=expand_all_btn,
        import_btn=import_btn,
        empty_add_btn=empty_add_btn,
        empty_import_btn=empty_import_btn,
        empty_clear_btn=empty_clear_btn,
        search_bar=search_bar,
        tree=tree,
        splitter=splitter,
        empty_state=empty_state,
        empty_title=empty_title,
        empty_text=empty_text,
        notice_banner=notice_banner,
        details_panel=details_panel,
        details_label=details_label,
        coords_label=coords_label,
        open_map_btn=open_map_btn,
        action_delegate=action_delegate,
    )


def _build_listing_section(parent: QWidget) -> tuple[CollapsibleSection, ListingFormWidgets]:
    section = CollapsibleSection(_TR("Add Property"), parent, show_delete=False, collapsible=False)
    section.setObjectName("listingsListingSection")
    form_widget, form = _build_listing_form(parent)
    section.set_content(form_widget)
    return section, form


def _build_listing_form(parent: QWidget) -> tuple[QWidget, ListingFormWidgets]:
    form_widget = QWidget(parent)
    form_widget.setObjectName("listingsListingForm")
    form_layout = QFormLayout(form_widget)
    form_layout.setContentsMargins(0, 0, 0, 0)
    form_layout.setSpacing(10)
    form_layout.setHorizontalSpacing(14)

    owner_name = QLineEdit()
    owner_name.setObjectName("listingOwnerNameInput")
    owner_name.setAccessibleName(_TR("Owner name"))
    owner_name.setPlaceholderText(_TR("Owner Family Name"))
    form_layout.addRow(_TR("Owner Name:"), owner_name)

    phone = QLineEdit()
    phone.setObjectName("listingPhoneInput")
    phone.setAccessibleName(_TR("Phone"))
    phone.setPlaceholderText(_TR("Phone"))
    form_layout.addRow(_TR("Phone:"), phone)

    flags_row = QHBoxLayout()
    is_vip = QComboBox()
    is_vip.setObjectName("listingVipCombo")
    is_vip.setAccessibleName(_TR("VIP"))
    is_vip.addItems([_TR("VIP: No"), _TR("VIP: Yes")])
    flags_row.addWidget(is_vip)
    flags_row.addStretch()
    form_layout.addRow(_TR("Flags:"), flags_row)

    remarks = QLineEdit()
    remarks.setObjectName("listingRemarksInput")
    remarks.setAccessibleName(_TR("Remarks"))
    remarks.setPlaceholderText(_TR("Notes/Remarks"))
    form_layout.addRow(_TR("Remarks:"), remarks)

    form_widget.setTabOrder(owner_name, phone)
    form_widget.setTabOrder(phone, is_vip)
    form_widget.setTabOrder(is_vip, remarks)

    return form_widget, ListingFormWidgets(
        owner_name=owner_name,
        phone=phone,
        is_vip=is_vip,
        remarks=remarks,
    )
