# ruff: noqa: E402
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("IMMOAPP_OFFLINE", "1")
os.environ.setdefault("IMMOAPP_STARTUP_LIGHT", "1")
os.environ.setdefault("IMMOAPP_SKIP_SCHEMA_INIT", "1")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QApplication, QHBoxLayout, QPushButton, QWidget

from app.models import Contract, Listing, Offer, Visit
from app.services.dashboard_cache import DashboardStats
from app.ui.theme_manager import apply_theme
from app.views.clients_v2_ui import build_clients_tab_ui
from app.views.crm import CRMTab
from app.views.dashboard import DashboardTab
from app.views.listings_v2_ui import build_listings_tab_ui
from app.views.match_results_header import build_results_header
from app.views.match_results_section_builder import build_demande_section
from app.views.match_results_types import MatchResultsDeps
from app.views.match_ui import build_match_ui
from app.widgets.demande_panel import DemandePanel
from app.widgets.login_dialog import LoginDialog
from app.widgets.offer_panel import OfferPanel
from core.matcher.match_details import OfferMatch
from core.matcher.match_models import MatchResult


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Capture deterministic UI screenshots.")
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=ROOT / "artifacts" / "ui_capture",
        help="Directory where screenshots are written.",
    )
    parser.add_argument(
        "--fixtures",
        type=Path,
        default=ROOT / "app" / "tests" / "ui_visual" / "fixtures" / "ui_states.json",
        help="Fixture JSON for deterministic rendering.",
    )
    parser.add_argument(
        "--theme",
        choices=("dark", "light", "all"),
        default="all",
        help="Theme to render.",
    )
    return parser.parse_args()


def _load_fixtures(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        payload = json.load(fh)
    if not isinstance(payload, dict):
        raise SystemExit(f"Invalid fixture payload: {path}")
    return payload


def _process_events(app: QApplication, rounds: int = 4) -> None:
    for _ in range(rounds):
        app.processEvents()


def _save_widget(app: QApplication, widget: QWidget, path: Path, width: int, height: int) -> None:
    widget.resize(width, height)
    widget.show()
    _process_events(app)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not widget.grab().save(str(path), "PNG"):
        raise RuntimeError(f"Failed to save screenshot: {path}")
    widget.hide()
    widget.close()
    widget.deleteLater()
    _process_events(app, 2)


def _seed_locations_cache(locations: list[str]) -> None:
    import app.services.locations_repository as loc_repo
    import app.widgets.location_form_helpers as loc_helpers

    cached = list(locations)
    loc_repo._cached_locations = cached  # noqa: SLF001
    loc_repo.get_all_locations = lambda: list(cached)
    loc_helpers.peek_cached_locations = lambda: list(cached)
    loc_helpers.get_all_locations = lambda: list(cached)


def _populate_model(model: QStandardItemModel, rows: list[list[object]]) -> None:
    for row in rows:
        items = [QStandardItem(str(value)) for value in row]
        model.appendRow(items)


def _build_login(fx: dict[str, Any]) -> QWidget:
    login = fx.get("login", {})
    dialog = LoginDialog()
    dialog._base_url.setText(str(login.get("base_url", "http://localhost:8000")))  # noqa: SLF001
    dialog._username.setText(str(login.get("username", "admin")))  # noqa: SLF001
    dialog._password.setText(str(login.get("password_mask", "********")))  # noqa: SLF001
    dialog._set_status(str(login.get("status", "")))  # noqa: SLF001
    return dialog


def _build_dashboard(fx: dict[str, Any]) -> QWidget:
    import app.services.dashboard_cache as cache

    data = fx.get("dashboard", {})
    stats = DashboardStats(
        client_count=int(data.get("client_count", 0)),
        listing_count=int(data.get("listing_count", 0)),
        today_visits=[item for item in data.get("today_visits", []) if isinstance(item, dict)],
        pending_contracts=[
            item for item in data.get("pending_contracts", []) if isinstance(item, dict)
        ],
        expiring_contracts=[
            item for item in data.get("expiring_contracts", []) if isinstance(item, dict)
        ],
        hot_leads=[item for item in data.get("hot_leads", []) if isinstance(item, dict)],
        is_stale=False,
        last_error=None,
    )
    cache._api_cache = stats  # noqa: SLF001
    tab = DashboardTab()
    tab.set_notice("")
    return tab


def _build_match_empty(fx: dict[str, Any]) -> QWidget:
    host = QWidget()
    ui = build_match_ui(
        parent=host,
        on_client_search=lambda _: None,
        on_filter_changed=lambda: None,
        on_run_match=lambda: None,
        on_save_settings=lambda: None,
    )
    options = fx.get("match", {}).get("client_options", [])
    if isinstance(options, list):
        ui.client_select.setItems([str(v) for v in options])
    if ui.client_select.count() > 0:
        ui.client_select.setCurrentIndex(0)
    return host


def _build_match_results(fx: dict[str, Any]) -> QWidget:
    host = QWidget()
    ui = build_match_ui(
        parent=host,
        on_client_search=lambda _: None,
        on_filter_changed=lambda: None,
        on_run_match=lambda: None,
        on_save_settings=lambda: None,
    )
    ui.placeholder.hide()
    ui.scroll_area.show()

    listing_map: dict[int, Listing] = {}
    matches: list[OfferMatch] = []
    for item in fx.get("match", {}).get("results", []):
        if not isinstance(item, dict):
            continue
        listing_id = int(item.get("listing_id", 0))
        listing_map[listing_id] = Listing(
            id=listing_id,
            family_name=str(item.get("owner_name", "")),
            phone=str(item.get("phone", "")),
        )
        offer = Offer(
            id=listing_id,
            listing_id=listing_id,
            type=str(item.get("type", "")),
            action=str(item.get("action", "")),
            location=str(item.get("location", "")),
            beds=int(item.get("beds", 0)),
            surface=float(item.get("surface", 0.0)),
            budget=float(item.get("budget", 0.0)),
            furnished=str(item.get("furnished", "")),
            floor=int(item.get("floor", 0)),
            link=str(item.get("link", "")),
            latitude=float(item.get("latitude", 0.0)),
            longitude=float(item.get("longitude", 0.0)),
        )
        matches.append(
            OfferMatch(
                listing_id=listing_id,
                offer=offer,
                score=float(item.get("score", 0.0)),
            )
        )

    def _create_actions(_listing_id: int, _offer: Offer, parent: QWidget | None) -> QWidget:
        container = QWidget(parent)
        container.setProperty("matchActionsContainer", True)
        row = QHBoxLayout(container)
        row.setContentsMargins(4, 0, 4, 0)
        row.setSpacing(6)
        visit = QPushButton("Visite", container)
        visit.setProperty("immoVariant", "secondary")
        visit.setProperty("matchAction", "visit")
        contract = QPushButton("Contrat", container)
        contract.setProperty("immoVariant", "success")
        contract.setProperty("matchAction", "contract")
        row.addWidget(visit)
        row.addWidget(contract)
        row.addStretch()
        return container

    deps = MatchResultsDeps(
        get_listing_by_id=lambda listing_id: listing_map.get(listing_id),
        create_action_buttons=_create_actions,
        on_phone_click=lambda: None,
        on_position_click=lambda: None,
        on_load_more=lambda: None,
        on_show_all=lambda: None,
        allow_pagination=False,
    )
    summary = str(fx.get("match", {}).get("summary", "Sample demande"))
    result = MatchResult(
        demande_id=1,
        demande_summary=summary,
        matches=matches,
        total_count=len(matches),
    )

    header = build_results_header(ui.results_container, total_unique_offers=len(matches))
    section = build_demande_section(ui.results_container, result, deps)
    section.set_expanded(True)

    insert_at = max(0, ui.results_layout.count() - 1)
    ui.results_layout.insertWidget(insert_at, header)
    ui.results_layout.insertWidget(insert_at + 1, section)
    return host


def _build_clients(fx: dict[str, Any]) -> QWidget:
    data = fx.get("clients", {})
    host = QWidget()
    model = QStandardItemModel(0, 13, host)
    _populate_model(model, [row for row in data.get("rows", []) if isinstance(row, list)])
    ui = build_clients_tab_ui(host, model)
    ui.form.family_name.setText(str(data.get("name", "")))
    ui.form.phone.setText(str(data.get("phone", "")))
    ui.form.is_vip.setChecked(bool(data.get("vip", False)))

    demande = DemandePanel(demande_number=1, parent=host)
    demande_data = data.get("demande", {})
    if isinstance(demande_data, dict):
        demande.set_data(demande_data)
    demande.expand()
    ui.demandes_layout.addWidget(demande)
    return host


def _build_listings(fx: dict[str, Any]) -> QWidget:
    data = fx.get("listings", {})
    host = QWidget()
    model = QStandardItemModel(0, 13, host)
    _populate_model(model, [row for row in data.get("rows", []) if isinstance(row, list)])
    ui = build_listings_tab_ui(host, model)
    ui.form.owner_name.setText(str(data.get("owner_name", "")))
    ui.form.phone.setText(str(data.get("phone", "")))
    vip_index = int(data.get("vip_index", 0))
    if 0 <= vip_index < ui.form.is_vip.count():
        ui.form.is_vip.setCurrentIndex(vip_index)
    ui.form.remarks.setText(str(data.get("remarks", "")))

    offer = OfferPanel(offer_number=1, parent=host)
    offer_data = data.get("offer", {})
    if isinstance(offer_data, dict):
        offer.set_data(offer_data)
    offer.expand()
    ui.offers_layout.addWidget(offer)
    ui.coords_label.setText("36.7525, 3.0420")
    ui.open_map_btn.setEnabled(True)
    return host


def _build_crm(fx: dict[str, Any], page: str) -> QWidget:
    import app.views.crm_contracts as crm_contracts
    import app.views.crm_visits as crm_visits

    crm_data = fx.get("crm", {})
    visits: list[Visit] = []
    for item in crm_data.get("visits", []):
        if not isinstance(item, dict):
            continue
        visits.append(
            Visit(
                id=int(item.get("id", 0)),
                client_id=int(item.get("client_id", 0)),
                listing_id=int(item.get("listing_id", 0)),
                scheduled_date=str(item.get("scheduled_date", "")),
                scheduled_time=str(item.get("scheduled_time", "")),
                status=str(item.get("status", "scheduled")),
                notes=str(item.get("notes", "")),
                row_version=int(item.get("row_version", 1)),
            )
        )

    contracts: list[Contract] = []
    for item in crm_data.get("contracts", []):
        if not isinstance(item, dict):
            continue
        contracts.append(
            Contract(
                id=int(item.get("id", 0)),
                client_id=int(item.get("client_id", 0)),
                listing_id=int(item.get("listing_id", 0)),
                client_name=str(item.get("client_name", "")),
                listing_location=str(item.get("listing_location", "")),
                contract_type=str(item.get("contract_type", "rent")),
                status=str(item.get("status", "draft")),
                start_date=str(item.get("start_date", "")),
                end_date=str(item.get("end_date", "")),
                amount=float(item.get("amount", 0.0)),
            )
        )

    crm_visits.fetch_visits = lambda status=None: list(visits)
    crm_contracts.fetch_contracts = lambda status=None, contract_type=None: list(contracts)

    tab = CRMTab()
    if page == "contracts":
        tab.tabs.setCurrentIndex(1)
    else:
        tab.tabs.setCurrentIndex(0)
    tab.refresh()
    return tab


def main() -> int:
    args = _parse_args()
    fixtures = _load_fixtures(args.fixtures)

    app = QApplication.instance() or QApplication([])
    themes = ["dark", "light"] if args.theme == "all" else [args.theme]
    _seed_locations_cache([str(v) for v in fixtures.get("locations", [])])

    for theme in themes:
        apply_theme(app, theme, persist=False)
        target_dir = args.out_dir / theme
        target_dir.mkdir(parents=True, exist_ok=True)

        screens: list[tuple[str, QWidget, tuple[int, int]]] = [
            ("login", _build_login(fixtures), (920, 560)),
            ("dashboard", _build_dashboard(fixtures), (1600, 950)),
            ("match_empty", _build_match_empty(fixtures), (1600, 950)),
            ("match_results", _build_match_results(fixtures), (1600, 950)),
            ("clients", _build_clients(fixtures), (1700, 980)),
            ("listings", _build_listings(fixtures), (1700, 980)),
            ("crm_visits", _build_crm(fixtures, "visits"), (1600, 950)),
            ("crm_contracts", _build_crm(fixtures, "contracts"), (1600, 950)),
        ]

        for name, widget, size in screens:
            output = target_dir / f"{name}.png"
            _save_widget(app, widget, output, size[0], size[1])
            print(f"[ui-capture] wrote {output}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
