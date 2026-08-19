"""
Contract Builder Dialog - Create contracts with dynamic articles.

Features:
- Load standard Algerian clauses (10 articles)
- Add custom articles
- Remove non-required articles
- Preview with live rendering
- Generate secure PDF with watermarks and signatures
"""

from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from app.models import Client, Listing, Offer
from app.utils.common import display_wilaya
from app.utils.i18n import tr_factory
from app.views.dialogs.contract_builder_article import ArticleWidget
from app.views.dialogs.contract_builder_articles import ContractBuilderArticleMixin
from app.views.dialogs.contract_builder_pdf import ContractBuilderPdfMixin
from app.views.dialogs.contract_builder_ui import build_articles_panel, build_info_panel
from app.widgets.workspace_dialog import WorkspaceDialogSpec, apply_workspace_dialog

_TR = tr_factory("ContractBuilderDialog")


class ContractBuilderDialog(ContractBuilderPdfMixin, ContractBuilderArticleMixin, QDialog):
    """Dialog for building and generating contracts."""

    def __init__(
        self,
        parent: QWidget | None = None,
        client: Client | None = None,
        listing: Listing | None = None,
        offer: Offer | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(_TR("Generateur de Contrat"))
        self.setModal(True)
        self.setObjectName("immoDialog")
        apply_workspace_dialog(
            self,
            WorkspaceDialogSpec(
                settings_key="dialogs/contract_builder_geometry",
                default_width=1280,
                default_height=860,
                min_width=980,
                min_height=720,
                allow_maximize=True,
            ),
            role="workspaceDialog",
        )

        self._client = client
        self._listing = listing
        self._offer = offer
        self._articles: list[ArticleWidget] = []

        self._setup_ui()

        # Pre-fill if client/listing provided
        if client:
            self._tenant_name.setText(getattr(client, "family_name", ""))
        if listing:
            self._owner_name.setText(getattr(listing, "family_name", ""))
        if offer:
            self._property_type.setCurrentText(offer.type or _TR("Appartement"))
            location = offer.location or display_wilaya(offer.wilaya)
            self._property_address.setText(location or "")
            if offer.surface:
                try:
                    self._property_surface.setValue(int(offer.surface))
                except (TypeError, ValueError):
                    pass

    def _setup_ui(self) -> None:
        """Build the dialog UI."""
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # Header
        header = QLabel(_TR("Generateur de Contrat de Location"))
        header.setObjectName("dialogSectionTitle")
        layout.addWidget(header)

        # Main content in horizontal split
        content = QHBoxLayout()

        # LEFT: Contract Info
        left_panel, info_widgets = build_info_panel(self)
        self._property_type = info_widgets.property_type
        self._property_address = info_widgets.property_address
        self._property_surface = info_widgets.property_surface
        self._owner_name = info_widgets.owner_name
        self._owner_address = info_widgets.owner_address
        self._tenant_name = info_widgets.tenant_name
        self._tenant_address = info_widgets.tenant_address
        self._start_date = info_widgets.start_date
        self._end_date = info_widgets.end_date
        self._monthly_rent = info_widgets.monthly_rent
        self._deposit = info_widgets.deposit
        content.addWidget(left_panel, 1)

        # RIGHT: Articles
        right_panel, article_widgets = build_articles_panel(self, self._add_custom_article)
        self._articles_container = article_widgets.articles_container
        self._articles_layout = article_widgets.articles_layout
        content.addWidget(right_panel, 2)

        layout.addLayout(content, 1)

        # Action buttons
        btn_layout = QHBoxLayout()

        load_clauses_btn = QPushButton(_TR("Charger Clauses Standard"))
        load_clauses_btn.clicked.connect(self._load_standard_clauses)
        load_clauses_btn.setAccessibleName(_TR("Charger clauses standard"))
        load_clauses_btn.setProperty("immoVariant", "secondary")

        preview_btn = QPushButton(_TR("Apercu PDF"))
        preview_btn.clicked.connect(self._preview_pdf)
        preview_btn.setAccessibleName(_TR("Apercu PDF"))
        preview_btn.setProperty("immoVariant", "ghost")

        generate_btn = QPushButton(_TR("Generer PDF"))
        generate_btn.clicked.connect(self._generate_pdf)
        generate_btn.setAccessibleName(_TR("Generer PDF"))
        generate_btn.setProperty("immoVariant", "success")

        cancel_btn = QPushButton(_TR("Annuler"))
        cancel_btn.clicked.connect(self.reject)
        cancel_btn.setAccessibleName(_TR("Annuler"))
        cancel_btn.setProperty("immoVariant", "ghost")

        btn_layout.addWidget(load_clauses_btn)
        btn_layout.addWidget(preview_btn)
        btn_layout.addStretch()
        btn_layout.addWidget(generate_btn)
        btn_layout.addWidget(cancel_btn)

        layout.addLayout(btn_layout)

        self.setTabOrder(self._property_type, self._property_address)
        self.setTabOrder(self._property_address, self._property_surface)
        self.setTabOrder(self._property_surface, self._owner_name)
        self.setTabOrder(self._owner_name, self._owner_address)
        self.setTabOrder(self._owner_address, self._tenant_name)
        self.setTabOrder(self._tenant_name, self._tenant_address)
        self.setTabOrder(self._tenant_address, self._start_date)
        self.setTabOrder(self._start_date, self._end_date)
        self.setTabOrder(self._end_date, self._monthly_rent)
        self.setTabOrder(self._monthly_rent, self._deposit)
        self.setTabOrder(self._deposit, load_clauses_btn)
        self.setTabOrder(load_clauses_btn, preview_btn)
        self.setTabOrder(preview_btn, generate_btn)
        self.setTabOrder(generate_btn, cancel_btn)
