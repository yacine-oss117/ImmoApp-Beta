from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QSettings
from PySide6.QtGui import QStandardItemModel
from PySide6.QtWidgets import QApplication, QFrame, QTreeView, QWidget

from app.ui.font_loader import SYSTEM_FONT_FALLBACKS, load_bundled_fonts
from app.ui.theme_manager import apply_theme, current_density, current_theme, set_density, set_theme
from app.ui.theme_qss import build_stylesheet
from app.ui.theme_tokens import DEFAULT_THEME, available_themes
from app.views.clients_v2_ui import build_clients_tab_ui
from app.views.listings_v2_ui import build_listings_tab_ui
from app.views.tree_view_helpers import configure_tree
from app.widgets.demande_form import DemandeForm
from app.widgets.demande_panel import DemandePanel
from app.widgets.offer_form import OfferForm
from app.widgets.offer_panel import OfferPanel

pytestmark = pytest.mark.ui


def _seed_locations(monkeypatch: pytest.MonkeyPatch) -> None:
    fixture_locations = ["Hydra, Alger", "Cheraga, Alger"]
    monkeypatch.setattr(
        "app.widgets.demande_form.prime_locations_non_blocking",
        lambda _parent, on_locations, **_kwargs: on_locations(list(fixture_locations)),
    )
    monkeypatch.setattr(
        "app.widgets.offer_form.prime_locations_non_blocking",
        lambda _parent, on_locations, **_kwargs: on_locations(list(fixture_locations)),
    )


def test_theme_selection_and_apply(qapp: QApplication, tmp_path: Path) -> None:
    settings = QSettings(str(tmp_path / "theme.ini"), QSettings.Format.IniFormat)
    assert current_theme(settings) == DEFAULT_THEME
    assert "dark" in available_themes()
    assert "light" in available_themes()

    selected = set_theme("light", settings)
    assert selected == "light"
    assert current_theme(settings) == "light"
    assert apply_theme(qapp, "dark", persist=False) == "dark"
    assert qapp.styleSheet()


def test_density_settings_contract(qapp: QApplication, tmp_path: Path) -> None:
    settings = QSettings(str(tmp_path / "density.ini"), QSettings.Format.IniFormat)
    assert current_density(settings) == "compact"
    assert set_density("compact", settings) == "compact"
    assert current_density(settings) == "compact"
    assert set_density("invalid", settings) == "compact"
    assert current_density(settings) == "compact"
    apply_theme(qapp, "dark", "compact", persist=False)
    assert qapp.styleSheet()


def test_demande_offer_forms_do_not_force_large_min_heights(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_locations(monkeypatch)
    demande = DemandeForm()
    offer = OfferForm()

    for widget in (
        demande.type,
        demande.action,
        demande.beds_min,
        demande.surface_min,
        demande.surface_max,
        demande.budget_min,
        demande.budget_max,
        demande.furnished,
        offer.type,
        offer.action,
        offer.beds,
        offer.surface,
        offer.budget,
        offer.furnished,
    ):
        assert widget.minimumHeight() <= 24

    demande_sections = [
        section
        for section in demande.findChildren(QFrame)
        if section.objectName() == "immoFormSection"
    ]
    offer_sections = [
        section
        for section in offer.findChildren(QFrame)
        if section.objectName() == "immoFormSection"
    ]
    assert len(demande_sections) >= 3
    assert len(offer_sections) >= 3

    demande.location.set_async_state("error", "Location error")
    assert demande.location.findChild(QWidget, "locationStatusLabel") is not None
    demande.location.clear_async_state()

    demande.deleteLater()
    offer.deleteLater()


def test_primary_actions_use_variant_property(qapp: QApplication) -> None:
    clients_host = QWidget()
    clients_model = QStandardItemModel(0, 13, clients_host)
    clients_ui = build_clients_tab_ui(clients_host, clients_model)

    listings_host = QWidget()
    listings_model = QStandardItemModel(0, 13, listings_host)
    listings_ui = build_listings_tab_ui(listings_host, listings_model)

    assert clients_ui.save_btn.property("immoVariant") == "primary"
    assert listings_ui.save_btn.property("immoVariant") == "primary"
    assert clients_ui.clear_btn.property("immoVariant") in {"ghost", "secondary"}
    assert listings_ui.clear_btn.property("immoVariant") in {"ghost", "secondary"}
    assert clients_ui.client_section.is_collapsible() is False
    assert listings_ui.listing_section.is_collapsible() is False
    assert clients_ui.page_scroll.objectName() == "clientsPageScroll"
    assert clients_ui.page_scroll.verticalScrollBar().property("immoScrollRole") == "compact"
    assert clients_ui.tree.verticalScrollBar().property("immoScrollRole") == "compact"
    assert clients_ui.demandes_empty.text()

    clients_host.deleteLater()
    listings_host.deleteLater()


def test_demande_offer_panels_are_non_collapsible(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_locations(monkeypatch)
    demande_panel = DemandePanel()
    offer_panel = OfferPanel()

    demande_panel.collapse()
    offer_panel.collapse()

    assert demande_panel.is_collapsed() is False
    assert offer_panel.is_collapsed() is False

    demande_panel.deleteLater()
    offer_panel.deleteLater()


def test_font_loading_supports_optional_assets_and_arabic_fallback(
    qapp: QApplication,
) -> None:
    families = load_bundled_fonts()
    assert isinstance(families, list)
    assert "Noto Sans Arabic" in SYSTEM_FONT_FALLBACKS
    assert "Segoe UI" in SYSTEM_FONT_FALLBACKS


def test_theme_stylesheet_contains_workspace_and_dialog_roles() -> None:
    dark_qss = build_stylesheet("dark")
    light_qss = build_stylesheet("light")

    expected_markers = (
        'QMenu[immoMenuRole="context"]',
        "QLabel#agencyAssetPreview",
        'QPushButton[immoRole="tinyAction"]',
        'QScrollArea[immoRole="editorScroll"]',
        'QScrollBar[immoScrollRole="compact"]:vertical',
        "QFrame#demandeSummaryCard",
        'QPushButton[immoSize="sm"]',
        'QLineEdit[immoSize="sm"]',
        "QFrame#NotificationToast_info",
        "QDialog#NotificationsDialog",
        "QFrame#NotificationCard_unread",
        "QWidget#NotificationFilterBar QPushButton:checked",
    )
    for marker in expected_markers:
        assert marker in dark_qss
        assert marker in light_qss

    assert "#1e1e2e" not in light_qss
    assert "QLabel {" in dark_qss
    assert "background: transparent;" in dark_qss


def test_configure_tree_uses_theme_properties_not_inline_styles(qapp: QApplication) -> None:
    tree = QTreeView()
    configure_tree(tree)

    assert tree.property("immoTreeRole") == "workspace"
    assert tree.styleSheet() == ""

    tree.deleteLater()
