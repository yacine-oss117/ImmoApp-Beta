from __future__ import annotations

import time

import pytest
from PySide6.QtWidgets import QPushButton

from app.models import Listing, Offer
from app.services.match_models import ClientMatchResult, MatchResult
from app.views.base import QLabel, QScrollArea, QVBoxLayout, QWidget
from app.views.match_results_controller import MatchResultsController
from app.views.match_results_controller_actions import MatchResultsActionHandlers
from app.widgets.collapsible_section import CollapsibleSection
from core.matcher.match_details import OfferMatch

pytestmark = pytest.mark.ui


def _tiny_png_bytes() -> bytes:
    return bytes.fromhex(
        "89504e470d0a1a0a0000000d4948445200000001000000010802000000907753"
        "de0000000c49444154789c63606060000000040001f61738550000000049454e44ae426082"
    )


def _process_events_until(qapp, predicate, *, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qapp.processEvents()
        if predicate():
            return
    qapp.processEvents()


def _build_controller() -> tuple[MatchResultsController, QLabel, QScrollArea, QVBoxLayout]:
    parent = QWidget()
    placeholder = QLabel("Select a client and click 'Run Match' to see results", parent=parent)

    results_container = QWidget(parent)
    results_layout = QVBoxLayout(results_container)
    results_layout.addStretch()

    scroll_area = QScrollArea(parent)
    scroll_area.setWidgetResizable(True)
    scroll_area.setWidget(results_container)

    controller = MatchResultsController(
        parent=parent,
        results_container=results_container,
        results_layout=results_layout,
        scroll_area=scroll_area,
        placeholder=placeholder,
        get_listing_by_id=lambda _listing_id: None,
        get_selected_client_id=lambda: None,
        get_limit_per_demande=lambda: 20,
        get_score_threshold=lambda: 0.0,
        sender_provider=lambda: None,
        refresh_crm_cb=None,
        feedback_cb=None,
    )
    return controller, placeholder, scroll_area, results_layout


def _build_handlers(parent: QWidget) -> MatchResultsActionHandlers:
    return MatchResultsActionHandlers(
        parent=parent,
        sender_provider=lambda: None,
        get_selected_client_id=lambda: 21,
        refresh_crm_cb=None,
        feedback_cb=None,
    )


def test_display_results_shows_empty_state_for_client_without_demandes(qapp) -> None:
    controller, placeholder, scroll_area, results_layout = _build_controller()

    result = ClientMatchResult(client_id=5, total_unique_offers=0, demande_results=[])
    controller.display_results(result, score_threshold=0.0, full_count=None)

    assert placeholder.isHidden() is False
    assert "no demandes" in placeholder.text().lower()
    assert scroll_area.isHidden() is True
    assert results_layout.count() == 1  # stretch only


def test_display_results_restores_default_placeholder_text_when_results_exist(qapp) -> None:
    controller, placeholder, scroll_area, _ = _build_controller()

    empty_result = ClientMatchResult(client_id=5, total_unique_offers=0, demande_results=[])
    controller.display_results(empty_result, score_threshold=0.0, full_count=None)

    non_empty_result = ClientMatchResult(
        client_id=6,
        total_unique_offers=0,
        demande_results=[
            MatchResult(
                demande_id=1,
                demande_summary="Test demande",
                matches=[],
                total_count=0,
            )
        ],
    )
    controller.display_results(non_empty_result, score_threshold=0.0, full_count=None)

    assert placeholder.text() == "Select a client and click 'Run Match' to see results"
    assert placeholder.isHidden() is True
    assert scroll_area.isHidden() is False


def test_display_results_expands_all_visible_demande_sections(qapp) -> None:
    parent = QWidget()
    placeholder = QLabel("Select a client and click 'Run Match' to see results", parent=parent)
    results_container = QWidget(parent)
    results_layout = QVBoxLayout(results_container)
    results_layout.addStretch()
    scroll_area = QScrollArea(parent)
    scroll_area.setWidgetResizable(True)
    scroll_area.setWidget(results_container)

    listings = {
        71: Listing(id=71, family_name="Owner A"),
        72: Listing(id=72, family_name="Owner B"),
    }
    controller = MatchResultsController(
        parent=parent,
        results_container=results_container,
        results_layout=results_layout,
        scroll_area=scroll_area,
        placeholder=placeholder,
        get_listing_by_id=lambda listing_id: listings.get(listing_id),
        get_selected_client_id=lambda: 11,
        get_limit_per_demande=lambda: 20,
        get_score_threshold=lambda: 0.0,
        sender_provider=lambda: None,
        refresh_crm_cb=None,
        feedback_cb=None,
    )

    result = ClientMatchResult(
        client_id=11,
        total_unique_offers=2,
        demande_results=[
            MatchResult(
                demande_id=101,
                demande_summary="Apartment A",
                matches=[
                    OfferMatch(
                        listing_id=71,
                        offer=Offer(id=701, listing_id=71, action="sell", location="Area A"),
                        score=8.0,
                    )
                ],
                total_count=1,
            ),
            MatchResult(
                demande_id=102,
                demande_summary="Apartment B",
                matches=[
                    OfferMatch(
                        listing_id=72,
                        offer=Offer(id=702, listing_id=72, action="sell", location="Area B"),
                        score=7.0,
                    )
                ],
                total_count=1,
            ),
        ],
    )

    controller.display_results(result, score_threshold=0.0, full_count=None)

    sections = results_container.findChildren(CollapsibleSection)
    assert len(sections) == 2
    assert all(not section.is_collapsed() for section in sections)
    assert isinstance(
        results_container.findChild(QPushButton, "matchOfferPhotosButton_listing_71_offer_701"),
        QPushButton,
    )
    assert isinstance(
        results_container.findChild(QPushButton, "matchOfferPhotosButton_listing_72_offer_702"),
        QPushButton,
    )


def test_match_actions_expose_persisted_contract_and_pdf_actions(
    monkeypatch: pytest.MonkeyPatch, qapp
) -> None:
    parent = QWidget()
    calls: list[tuple[str, dict[str, object]]] = []

    def _create_contract_action(**kwargs: object) -> None:
        calls.append(("create", kwargs))

    def _generate_pdf_contract(**kwargs: object) -> None:
        calls.append(("pdf", kwargs))

    monkeypatch.setattr(
        "app.views.match_results_controller_actions.create_contract_action",
        _create_contract_action,
    )
    monkeypatch.setattr(
        "app.views.match_results_controller_actions.generate_pdf_contract",
        _generate_pdf_contract,
    )

    handlers = MatchResultsActionHandlers(
        parent=parent,
        sender_provider=lambda: None,
        get_selected_client_id=lambda: 21,
        refresh_crm_cb=None,
        feedback_cb=None,
    )
    actions = handlers.create_action_buttons(
        7,
        Offer(id=5, listing_id=7, action="rent", location="Hydra"),
        parent,
    )

    create_button = actions.findChild(QPushButton, "matchCreateContractButton_listing_7_offer_5")
    pdf_button = actions.findChild(QPushButton, "matchGenerateContractPdfButton_listing_7_offer_5")
    assert isinstance(create_button, QPushButton)
    assert isinstance(pdf_button, QPushButton)
    assert create_button.accessibleName() == "Create contract"
    assert pdf_button.accessibleName() == "Generate contract PDF"

    create_button.click()
    pdf_button.click()

    assert [name for name, _ in calls] == ["create", "pdf"]
    assert calls[0][1]["client_id"] == 21
    assert calls[0][1]["listing_id"] == 7
    assert calls[0][1]["action"] == "rent"


def test_match_offer_photos_dialog_renders_loaded_thumbnails(
    monkeypatch: pytest.MonkeyPatch,
    qapp,
) -> None:
    parent = QWidget()
    handlers = _build_handlers(parent)
    monkeypatch.setattr(
        "app.views.match_results_controller_actions.offer_photo_service.list_offer_photos",
        lambda offer_id: [
            {
                "id": 901,
                "offer_id": offer_id,
                "storage_id": "550e8400-e29b-41d4-a716-446655449001",
                "deleted_at": None,
            }
        ],
    )
    monkeypatch.setattr(
        (
            "app.views.match_results_controller_actions.offer_photo_service."
            "download_offer_photo_thumbnail_bytes"
        ),
        lambda _storage_id, *, max_bytes: _tiny_png_bytes(),
    )

    dialog = handlers._build_offer_photos_dialog(offer_id=701, owner_name="Area A")
    try:
        assert dialog.objectName() == "matchOfferPhotosDialog_offer_701"
        assert dialog.findChild(QWidget, "matchOfferPhotoItem_901") is not None
        preview = dialog.findChild(QLabel, "matchOfferPhotoThumbnail_901")
        assert preview is not None
        _process_events_until(
            qapp,
            lambda: preview.property("photoThumbnailState") == "loaded",
        )
        assert preview.property("photoThumbnailLoaded") is True
        assert preview.accessibleName() == "Matched offer photo thumbnail loaded"
        pixmap = preview.pixmap()
        assert pixmap is not None and not pixmap.isNull()
    finally:
        dialog.close()
        dialog.deleteLater()
        qapp.processEvents()


def test_match_offer_photos_dialog_renders_empty_state(
    monkeypatch: pytest.MonkeyPatch,
    qapp,
) -> None:
    parent = QWidget()
    handlers = _build_handlers(parent)
    monkeypatch.setattr(
        "app.views.match_results_controller_actions.offer_photo_service.list_offer_photos",
        lambda _offer_id: [],
    )

    dialog = handlers._build_offer_photos_dialog(offer_id=701, owner_name="Area A")
    try:
        assert dialog.findChild(QLabel, "matchOfferPhotosEmpty_offer_701") is not None
    finally:
        dialog.close()
        dialog.deleteLater()
        qapp.processEvents()


def test_match_offer_photos_dialog_thumbnail_failure_keeps_placeholder(
    monkeypatch: pytest.MonkeyPatch,
    qapp,
) -> None:
    parent = QWidget()
    handlers = _build_handlers(parent)
    monkeypatch.setattr(
        "app.views.match_results_controller_actions.offer_photo_service.list_offer_photos",
        lambda offer_id: [
            {
                "id": 902,
                "offer_id": offer_id,
                "storage_id": "550e8400-e29b-41d4-a716-446655449002",
                "deleted_at": None,
            }
        ],
    )
    monkeypatch.setattr(
        (
            "app.views.match_results_controller_actions.offer_photo_service."
            "download_offer_photo_thumbnail_bytes"
        ),
        lambda _storage_id, *, max_bytes: b"",
    )

    dialog = handlers._build_offer_photos_dialog(offer_id=702, owner_name="Area B")
    try:
        preview = dialog.findChild(QLabel, "matchOfferPhotoThumbnail_902")
        assert preview is not None
        _process_events_until(
            qapp,
            lambda: preview.property("photoThumbnailState") == "failed",
        )
        assert preview.property("photoThumbnailLoaded") is False
        assert preview.accessibleName() == "Matched offer photo thumbnail unavailable"
        assert preview.text() == "Preview unavailable"
    finally:
        dialog.close()
        dialog.deleteLater()
        qapp.processEvents()


def test_match_offer_photos_dialog_has_no_mutation_controls(
    monkeypatch: pytest.MonkeyPatch,
    qapp,
) -> None:
    parent = QWidget()
    handlers = _build_handlers(parent)
    monkeypatch.setattr(
        "app.views.match_results_controller_actions.offer_photo_service.list_offer_photos",
        lambda offer_id: [
            {
                "id": 903,
                "offer_id": offer_id,
                "storage_id": "550e8400-e29b-41d4-a716-446655449003",
                "deleted_at": None,
            }
        ],
    )
    monkeypatch.setattr(
        (
            "app.views.match_results_controller_actions.offer_photo_service."
            "download_offer_photo_thumbnail_bytes"
        ),
        lambda _storage_id, *, max_bytes: b"",
    )

    dialog = handlers._build_offer_photos_dialog(offer_id=703, owner_name="Area C")
    try:
        buttons = dialog.findChildren(QPushButton)
        assert buttons
        assert {button.objectName() for button in buttons} == {"matchOfferPhotosDialogCloseButton"}
        assert dialog.findChild(QPushButton, "offerPhotosAddButton_703") is None
        assert dialog.findChild(QPushButton, "offerPhotoDeleteButton_903") is None
    finally:
        dialog.close()
        dialog.deleteLater()
        qapp.processEvents()
