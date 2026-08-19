"""UI builder for ClientsTabV2."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.delegates.action_delegate import ActionDelegate
from app.utils.i18n import tr_factory
from app.views.client_sql_model import ClientSQLModel
from app.views.clients_scroll import ClientsPageScrollArea, ClientsTreeView
from app.views.tree_view_helpers import apply_column_widths, configure_tree
from app.widgets.collapsible_section import CollapsibleSection
from app.widgets.notice_banner import NoticeBanner

_TR = tr_factory("ClientsTabUi")


@dataclass(frozen=True)
class ClientFormWidgets:
    """Widgets for the client form section."""

    family_name: QLineEdit
    phone: QLineEdit
    is_vip: QCheckBox


@dataclass(frozen=True)
class ClientsTabUi:
    """All widgets composing the ClientsTabV2 UI."""

    page_scroll: ClientsPageScrollArea
    client_section: CollapsibleSection
    form: ClientFormWidgets
    demandes_container: QWidget
    demandes_layout: QVBoxLayout
    demandes_empty: QLabel
    add_demande_btn: QPushButton
    save_btn: QPushButton
    clear_btn: QPushButton
    focus_table_btn: QPushButton
    expand_all_btn: QPushButton
    import_btn: QPushButton
    empty_add_btn: QPushButton
    empty_import_btn: QPushButton
    empty_clear_btn: QPushButton
    search_bar: QLineEdit
    tree: ClientsTreeView
    records_card: QFrame
    empty_state: QFrame
    empty_title: QLabel
    empty_text: QLabel
    notice_banner: NoticeBanner
    action_delegate: ActionDelegate


def build_clients_tab_ui(parent: QWidget, model: ClientSQLModel) -> ClientsTabUi:
    """Build the Clients editor, compact request summaries, and full records workspace."""
    parent.setObjectName("clientsTab")
    shell_layout = QVBoxLayout(parent)
    shell_layout.setContentsMargins(0, 0, 0, 0)
    shell_layout.setSpacing(0)

    page_scroll = ClientsPageScrollArea(parent)
    page_content = QWidget(page_scroll)
    page_content.setObjectName("clientsPageContent")
    page_layout = QVBoxLayout(page_content)
    page_layout.setContentsMargins(12, 12, 12, 12)
    page_layout.setSpacing(12)

    client_section, form = _build_client_section(page_content)

    add_demande_btn = QPushButton(_TR("+ Add Request"))
    add_demande_btn.setObjectName("clientsAddDemandeButton")
    add_demande_btn.setProperty("immoVariant", "secondary")
    add_demande_btn.setProperty("immoSize", "sm")
    add_demande_btn.setMaximumWidth(160)
    add_demande_btn.setAccessibleName(_TR("Add request"))

    demandes_card = QFrame(page_content)
    demandes_card.setObjectName("clientsRequestsCard")
    demandes_card.setProperty("immoRole", "requestList")
    demandes_card_layout = QVBoxLayout(demandes_card)
    demandes_card_layout.setContentsMargins(12, 10, 12, 10)
    demandes_card_layout.setSpacing(8)

    demandes_header = QHBoxLayout()
    demandes_title = QLabel(_TR("Property Requests"), demandes_card)
    demandes_title.setObjectName("clientsRequestsTitle")
    demandes_header.addWidget(demandes_title)
    demandes_header.addStretch()
    demandes_header.addWidget(add_demande_btn)
    demandes_card_layout.addLayout(demandes_header)

    demandes_empty = QLabel(
        _TR("No requests yet. Add one if this client is looking for a property."),
        demandes_card,
    )
    demandes_empty.setObjectName("clientsRequestsEmpty")
    demandes_empty.setProperty("immoEmptyState", True)
    demandes_empty.setWordWrap(True)
    demandes_card_layout.addWidget(demandes_empty)

    demandes_container = QWidget(demandes_card)
    demandes_container.setObjectName("clientsRequestsContainer")
    demandes_layout = QVBoxLayout(demandes_container)
    demandes_layout.setContentsMargins(0, 0, 0, 0)
    demandes_layout.setSpacing(8)
    demandes_card_layout.addWidget(demandes_container)

    save_btn = QPushButton(_TR("Save Client"))
    save_btn.setObjectName("clientsSaveButton")
    save_btn.setShortcut("Ctrl+S")
    save_btn.setToolTip(_TR("Save client and all requests (Ctrl+S)"))
    save_btn.setAccessibleName(_TR("Save client"))
    save_btn.setProperty("immoVariant", "primary")

    clear_btn = QPushButton(_TR("Clear Form"))
    clear_btn.setObjectName("clientsClearButton")
    clear_btn.setShortcut("Escape")
    clear_btn.setToolTip(_TR("Clear form (Esc)"))
    clear_btn.setAccessibleName(_TR("Clear form"))
    clear_btn.setProperty("immoVariant", "ghost")

    editor_card = QFrame(page_content)
    editor_card.setObjectName("clientsEditorCard")
    editor_card.setProperty("immoCard", True)
    editor_layout = QVBoxLayout(editor_card)
    editor_layout.setContentsMargins(12, 12, 12, 12)
    editor_layout.setSpacing(10)
    editor_layout.addWidget(client_section)
    editor_layout.addWidget(demandes_card)

    action_footer = QWidget(editor_card)
    action_footer_layout = QHBoxLayout(action_footer)
    action_footer_layout.setContentsMargins(0, 2, 0, 0)
    action_footer_layout.setSpacing(8)
    action_footer_layout.addStretch()
    action_footer_layout.addWidget(save_btn)
    action_footer_layout.addWidget(clear_btn)
    editor_layout.addWidget(action_footer)

    filter_row = QHBoxLayout()

    expand_all_btn = QPushButton(_TR("⏬"))
    expand_all_btn.setObjectName("clientsExpandAllButton")
    expand_all_btn.setToolTip(_TR("Expand All / Collapse All Clients"))
    expand_all_btn.setAccessibleName(_TR("Expand or collapse all clients"))
    expand_all_btn.setProperty("immoVariant", "ghost")
    expand_all_btn.setProperty("immoSize", "sm")
    expand_all_btn.setMinimumWidth(38)
    filter_row.addWidget(expand_all_btn)

    import_btn = QPushButton(_TR("📥 Import"))
    import_btn.setObjectName("clientsImportButton")
    import_btn.setToolTip(_TR("Import clients from Excel/CSV"))
    import_btn.setProperty("immoVariant", "secondary")
    import_btn.setProperty("immoSize", "sm")
    import_btn.setAccessibleName(_TR("Import clients"))
    filter_row.addWidget(import_btn)

    focus_table_btn = QPushButton(_TR("⛶"))
    focus_table_btn.setObjectName("clientsFocusTableButton")
    focus_table_btn.setToolTip(_TR("Focus the client table"))
    focus_table_btn.setAccessibleName(_TR("Focus client table"))
    focus_table_btn.setProperty("immoVariant", "ghost")
    focus_table_btn.setProperty("immoSize", "sm")
    focus_table_btn.setMaximumWidth(38)
    filter_row.addWidget(focus_table_btn)

    search_bar = QLineEdit()
    search_bar.setObjectName("clientsSearchInput")
    search_bar.setPlaceholderText(_TR("Search: Name, Phone, Location, Type, Action... (Ctrl+F)"))
    search_bar.setAccessibleName(_TR("Client search"))
    search_bar.setClearButtonEnabled(True)
    filter_row.addWidget(QLabel(_TR("Search:")))
    filter_row.addWidget(search_bar, 2)

    tree = ClientsTreeView(page_content)
    tree.setObjectName("clientsTree")
    tree.setAccessibleName(_TR("Clients tree"))
    tree.setAccessibleDescription(_TR("Client and requests tree view"))
    tree.setModel(model)
    tree.setProperty("immoRole", "workspaceTable")
    configure_tree(tree)
    apply_column_widths(
        tree, "clients_tab", [220, 130, 100, 70, 180, 60, 90, 120, 80, 130, 130, 120, 160]
    )

    action_delegate = ActionDelegate(tree)
    tree.setItemDelegateForColumn(12, action_delegate)

    records_card = QFrame(page_content)
    records_card.setObjectName("clientsResultsCard")
    records_card.setProperty("immoCard", True)
    records_layout = QVBoxLayout(records_card)
    records_layout.setContentsMargins(12, 12, 12, 12)
    records_layout.setSpacing(10)
    notice_banner = NoticeBanner(records_card)
    records_layout.addWidget(notice_banner)
    records_layout.addLayout(filter_row)

    empty_state = QFrame(records_card)
    empty_state.setObjectName("clientsEmptyState")
    empty_state.setProperty("immoRole", "workspaceEditor")
    empty_layout = QVBoxLayout(empty_state)
    empty_layout.setContentsMargins(12, 10, 12, 10)
    empty_layout.setSpacing(4)
    empty_title = QLabel(_TR("No clients yet"))
    empty_title.setObjectName("StepDescription")
    empty_text = QLabel(
        _TR("Use the form above to add a client, or use the Import button in the toolbar.")
    )
    empty_text.setWordWrap(True)
    empty_add_btn = QPushButton(_TR("Add client"))
    empty_add_btn.setObjectName("clientsEmptyAddButton")
    empty_add_btn.setProperty("immoVariant", "primary")
    empty_add_btn.setVisible(False)
    empty_import_btn = QPushButton(_TR("Import file"))
    empty_import_btn.setObjectName("clientsEmptyImportButton")
    empty_import_btn.setProperty("immoVariant", "secondary")
    empty_import_btn.setVisible(False)
    empty_clear_btn = QPushButton(_TR("Clear search"))
    empty_clear_btn.setObjectName("clientsEmptyClearButton")
    empty_clear_btn.setProperty("immoVariant", "secondary")
    empty_clear_btn.setVisible(False)
    empty_layout.addWidget(empty_title)
    empty_layout.addWidget(empty_text)
    empty_layout.addWidget(empty_clear_btn)
    empty_state.setVisible(False)
    records_layout.addWidget(empty_state)
    records_layout.addWidget(tree, stretch=1)

    page_layout.addWidget(editor_card)
    page_layout.addWidget(records_card, stretch=1)
    page_scroll.setWidget(page_content)
    page_scroll.set_records_widget(records_card)
    page_scroll.set_table_view(tree)
    tree.set_outer_scroll_area(page_scroll)
    shell_layout.addWidget(page_scroll)

    parent.setTabOrder(form.family_name, form.phone)
    parent.setTabOrder(form.phone, form.is_vip)
    parent.setTabOrder(form.is_vip, add_demande_btn)
    parent.setTabOrder(add_demande_btn, save_btn)
    parent.setTabOrder(save_btn, clear_btn)
    parent.setTabOrder(clear_btn, search_bar)
    parent.setTabOrder(search_bar, tree)

    return ClientsTabUi(
        page_scroll=page_scroll,
        client_section=client_section,
        form=form,
        demandes_container=demandes_container,
        demandes_layout=demandes_layout,
        demandes_empty=demandes_empty,
        add_demande_btn=add_demande_btn,
        save_btn=save_btn,
        clear_btn=clear_btn,
        focus_table_btn=focus_table_btn,
        expand_all_btn=expand_all_btn,
        import_btn=import_btn,
        empty_add_btn=empty_add_btn,
        empty_import_btn=empty_import_btn,
        empty_clear_btn=empty_clear_btn,
        search_bar=search_bar,
        tree=tree,
        records_card=records_card,
        empty_state=empty_state,
        empty_title=empty_title,
        empty_text=empty_text,
        notice_banner=notice_banner,
        action_delegate=action_delegate,
    )


def _build_client_section(parent: QWidget) -> tuple[CollapsibleSection, ClientFormWidgets]:
    section = CollapsibleSection(_TR("Add Client"), parent, show_delete=False, collapsible=False)
    section.setObjectName("clientsClientSection")
    form_widget, form = _build_client_form(parent)
    section.set_content(form_widget)
    return section, form


def _build_client_form(parent: QWidget) -> tuple[QWidget, ClientFormWidgets]:
    form_widget = QWidget(parent)
    form_widget.setObjectName("clientsClientForm")
    form = QFormLayout(form_widget)
    form.setVerticalSpacing(10)
    form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
    form.setHorizontalSpacing(14)

    family_name = QLineEdit()
    family_name.setObjectName("clientFamilyNameInput")
    family_name.setAccessibleName(_TR("Family name"))
    family_name.setPlaceholderText(_TR("Client family name"))
    phone = QLineEdit()
    phone.setObjectName("clientPhoneInput")
    phone.setAccessibleName(_TR("Phone"))
    phone.setPlaceholderText(_TR("Phone"))
    is_vip = QCheckBox(_TR("VIP ⭐"))
    is_vip.setObjectName("clientVipCheck")
    is_vip.setAccessibleName(_TR("VIP"))

    form.addRow(_TR("Name"), family_name)
    form.addRow(_TR("Phone"), phone)

    h_checks = QHBoxLayout()
    h_checks.addWidget(is_vip)
    h_checks.addStretch()
    h_checks.setSpacing(20)
    form.addRow("", h_checks)

    form_widget.setTabOrder(family_name, phone)
    form_widget.setTabOrder(phone, is_vip)

    return form_widget, ClientFormWidgets(
        family_name=family_name,
        phone=phone,
        is_vip=is_vip,
    )
