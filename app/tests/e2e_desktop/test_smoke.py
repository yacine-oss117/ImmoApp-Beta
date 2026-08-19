from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from app.tests.e2e_desktop import backend
from app.tests.e2e_desktop.pages import (
    ClientsPage,
    ImportWizardPage,
    ListingsPage,
    MatchPage,
    login_to_main_window,
)
from app.tests.e2e_desktop.ui import wait_for

pytestmark = [pytest.mark.e2e, pytest.mark.e2e_smoke]


def _phone(prefix: str) -> str:
    return f"{prefix}{backend.numeric_suffix(6)}"


def _letters(length: int = 6) -> str:
    collected = ""
    while len(collected) < length:
        collected += "".join(ch for ch in uuid.uuid4().hex if ch.isalpha())
    return collected[:length]


def test_launch_login_success_shows_dashboard(
    e2e_base_url: str,
    make_backend_user,
    launch_native_desktop,
) -> None:
    user = make_backend_user(prefix="e2e_login")
    session = launch_native_desktop(username=user.username)
    main = login_to_main_window(
        session,
        username=user.username,
        password=user.password,
        base_url=e2e_base_url,
    )
    wait_for("main tabs", lambda: main.tabs, timeout=20.0)
    wait_for(
        "desktop auth session persistence",
        lambda: backend.active_session_count(user_id=user.user_id) > 0,
        timeout=20.0,
    )


def test_import_happy_path_persists_data(
    e2e_base_url: str,
    artifact_dir: Path,
    make_backend_user,
    launch_native_desktop,
) -> None:
    user = make_backend_user(prefix="e2e_import_ok", can_import=True)
    family_name = f"ImportHappy{_letters()}"
    phone = _phone("213555")
    before_client_count = backend.count_clients(agency_id=user.agency_id)
    import_file = backend.write_client_import_csv(
        artifact_dir / f"client_import_happy_{uuid.uuid4().hex[:6]}.csv",
        family_name=family_name,
        phone=phone,
    )

    session = launch_native_desktop(username=user.username)
    main = login_to_main_window(
        session,
        username=user.username,
        password=user.password,
        base_url=e2e_base_url,
    )
    main.select_tab("clients")
    clients = ClientsPage(main, session)
    clients.open_import_wizard()
    wizard = ImportWizardPage.wait(session)
    wizard.upload_file(import_file)
    wizard.continue_mapping()
    wizard.wait_for_summary()
    wizard.wait_for_summary_headline("Your import is complete")
    wizard.finish()

    job = backend.wait_for_import_job(
        user_id=user.user_id,
        filename=import_file.name,
        predicate=lambda candidate: candidate.status == backend.ImportJob.Status.COMPLETED,
        timeout=90.0,
    )
    assert job.status == backend.ImportJob.Status.COMPLETED
    result_summary = dict(job.result_summary or {})
    result_entity_counts = dict(result_summary.get("result_entity_counts") or {})
    assert int(result_summary.get("created_count", 0) or 0) >= 1
    assert int(result_entity_counts.get("client", 0) or 0) >= 1
    after_client_count = wait_for(
        "imported client count increment",
        lambda: (
            backend.count_clients(agency_id=user.agency_id)
            if backend.count_clients(agency_id=user.agency_id) > before_client_count
            else None
        ),
        timeout=20.0,
    )
    assert int(after_client_count) > before_client_count


def test_import_review_required_path_can_submit_and_persist(
    e2e_base_url: str,
    artifact_dir: Path,
    make_backend_user,
    launch_native_desktop,
) -> None:
    user = make_backend_user(prefix="e2e_import_review", can_import=True)
    family_name = f"ReviewFix{_letters()}"
    imported_family_name = f"{family_name}123"
    phone = _phone("213558")
    before_client_count = backend.count_clients(agency_id=user.agency_id)
    import_file = backend.write_client_import_csv(
        artifact_dir / "client_import_review.csv",
        family_name=imported_family_name,
        phone=phone,
    )

    session = launch_native_desktop(username=user.username)
    main = login_to_main_window(
        session,
        username=user.username,
        password=user.password,
        base_url=e2e_base_url,
    )
    main.select_tab("clients")
    clients = ClientsPage(main, session)
    clients.open_import_wizard()
    wizard = ImportWizardPage.wait(session)
    wizard.upload_file(import_file)
    wizard.continue_mapping()
    wizard.wait_for_review()
    wizard.submit_review(
        action="create_new",
        corrections={"family_name": family_name},
    )
    wizard.wait_for_summary()
    wizard.wait_for_summary_headline("Your import is complete")
    wizard.finish()

    job = backend.wait_for_import_job(
        user_id=user.user_id,
        filename=import_file.name,
        predicate=lambda candidate: candidate.status == backend.ImportJob.Status.COMPLETED,
        timeout=90.0,
    )
    assert job.status == backend.ImportJob.Status.COMPLETED
    result_summary = dict(job.result_summary or {})
    result_entity_counts = dict(result_summary.get("result_entity_counts") or {})
    assert int(result_summary.get("review_history_count", 0) or 0) >= 1
    decision_summary = dict(result_summary.get("decision_summary") or {})
    assert int(decision_summary.get("create_new", 0) or 0) >= 1
    assert int(result_entity_counts.get("client", 0) or 0) >= 1
    after_client_count = wait_for(
        "reviewed import client count increment",
        lambda: (
            backend.count_clients(agency_id=user.agency_id)
            if backend.count_clients(agency_id=user.agency_id) > before_client_count
            else None
        ),
        timeout=20.0,
    )
    assert int(after_client_count) > before_client_count


def test_create_client_via_ui_persists(
    e2e_base_url: str,
    make_backend_user,
    launch_native_desktop,
) -> None:
    user = make_backend_user(prefix="e2e_client")
    family_name = f"Client UI {uuid.uuid4().hex[:6]}"
    phone = _phone("213661")

    session = launch_native_desktop(username=user.username)
    main = login_to_main_window(
        session,
        username=user.username,
        password=user.password,
        base_url=e2e_base_url,
    )
    main.select_tab("clients")
    clients = ClientsPage(main, session)
    clients.create_client(family_name=family_name, phone=phone)

    row = wait_for(
        "client persisted server-side",
        lambda: backend.api_find_client_row(
            base_url=e2e_base_url,
            user=user,
            search=family_name,
            family_name=family_name,
            phone=phone,
        ),
        timeout=20.0,
    )
    assert row is not None
    assert str(row["family_name"]) == family_name
    assert str(row["phone"]) == phone


def test_create_listing_via_ui_persists(
    e2e_base_url: str,
    make_backend_user,
    launch_native_desktop,
) -> None:
    user = make_backend_user(prefix="e2e_listing")
    owner_name = f"Listing UI {uuid.uuid4().hex[:6]}"
    phone = _phone("213771")

    session = launch_native_desktop(username=user.username)
    main = login_to_main_window(
        session,
        username=user.username,
        password=user.password,
        base_url=e2e_base_url,
    )
    main.select_tab("listings")
    listings = ListingsPage(main, session)
    listings.create_listing(owner_name=owner_name, phone=phone, remarks="desktop smoke")

    row = wait_for(
        "listing persisted server-side",
        lambda: backend.api_find_listing_row(
            base_url=e2e_base_url,
            user=user,
            search=owner_name,
            family_name=owner_name,
            phone=phone,
        ),
        timeout=20.0,
    )
    assert row is not None
    assert str(row["family_name"]) == owner_name
    assert str(row["phone"]) == phone


def test_match_screen_loads_results_for_seeded_entities(
    e2e_base_url: str,
    make_backend_user,
    launch_native_desktop,
) -> None:
    user = make_backend_user(prefix="e2e_match")
    seed = backend.seed_match_entities(
        user=user,
        client_name=f"Match Client {uuid.uuid4().hex[:6]}",
        listing_owner=f"Match Listing {uuid.uuid4().hex[:6]}",
        base_url=e2e_base_url,
    )

    session = launch_native_desktop(username=user.username)
    main = login_to_main_window(
        session,
        username=user.username,
        password=user.password,
        base_url=e2e_base_url,
    )
    main.select_tab("matches")
    match_page = MatchPage(main)
    match_page.run_for_client(seed.client_name)

    wait_for(
        "match API results for seeded client",
        lambda: backend.api_client_match_total(
            base_url=e2e_base_url,
            user=user,
            client_id=seed.client_id,
        )
        > 0,
        timeout=30.0,
    )
