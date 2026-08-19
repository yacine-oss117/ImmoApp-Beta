from __future__ import annotations

import json
import subprocess
import uuid
from pathlib import Path
from typing import Any

import pytest

from app.tests.e2e_desktop import backend
from app.tests.e2e_desktop.pages import (
    ClientsPage,
    ImportWizardPage,
    LoginPage,
    MainWindowPage,
    MatchPage,
    QuickStartPage,
    SetupWizardPage,
    login_to_main_window,
)
from app.tests.e2e_desktop.ui import child, clear_and_type, wait_for

pytestmark = [pytest.mark.e2e, pytest.mark.e2e_nightly, pytest.mark.nightly]


def _phone(prefix: str) -> str:
    return f"{prefix}{backend.numeric_suffix(6)}"


def _letters(length: int = 6) -> str:
    collected = ""
    while len(collected) < length:
        collected += "".join(ch for ch in uuid.uuid4().hex if ch.isalpha())
    return collected[:length]


def _git_sha(repo_root: Path) -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        text=True,
    ).strip()


def _write_setup_front_door_evidence(
    *,
    artifact_dir: Path,
    repo_root: Path,
    front_door_url: str,
    backend_internal_url: str,
    persisted_client_base_url: str,
    connection_source: str,
) -> Path:
    preflight = backend.ensure_front_door_ready(front_door_url)
    evidence = {
        "kind": "immoapp_setup_wizard_front_door_e2e_evidence",
        "schema_version": 1,
        "source_commit_sha": _git_sha(repo_root),
        "front_door_url": preflight.base_url,
        "backend_internal_url": backend_internal_url,
        "health_status": preflight.health_status,
        "identity_status": preflight.identity_status,
        "front_door_header": preflight.front_door_header,
        "identity_kind": preflight.identity.get("kind"),
        "identity_schema_version": preflight.identity.get("schema_version"),
        "persisted_client_base_url": persisted_client_base_url,
        "connection_source": connection_source,
        "proof_result": (
            "GO"
            if persisted_client_base_url == preflight.base_url
            and connection_source != "local_dev_unverified"
            and preflight.front_door_header.lower() == "caddy"
            else "NO-GO"
        ),
    }
    path = artifact_dir / "setup_wizard_front_door_e2e_evidence.json"
    path.write_text(json.dumps(evidence, indent=2, ensure_ascii=True), encoding="utf-8")
    return path


def test_invalid_login_retry_then_success(
    e2e_base_url: str,
    make_backend_user: Any,
    launch_native_desktop: Any,
) -> None:
    user = make_backend_user(prefix="e2e_login_retry")
    session = launch_native_desktop(username=user.username)
    login = LoginPage.wait(session)
    login.sign_in(username=user.username, password="WrongPass_123!", base_url=e2e_base_url)
    login.wait_for_error("Login failed: invalid email or password.")
    login.sign_in(username=user.username, password=user.password, base_url=e2e_base_url)
    main = MainWindowPage.wait(session)
    wait_for("main tabs after login retry", lambda: main.tabs, timeout=20.0)


def test_first_run_setup_and_quick_start_flow_reaches_dashboard(
    artifact_dir: Path,
    repo_root: Path,
    e2e_base_url: str,
    e2e_front_door_url: str,
    make_backend_user: Any,
    launch_native_desktop: Any,
) -> None:
    user = make_backend_user(prefix="e2e_first_run")
    session = launch_native_desktop(
        username=user.username,
        preseed_api=False,
        preseed_quick_start=False,
    )
    SetupWizardPage.wait(session).connect_manual(e2e_front_door_url)
    client_config_path = session.options.appdata_root / "config" / "client_api.json"

    def _setup_saved_verified_front_door() -> bool:
        if not client_config_path.exists():
            return False
        payload = json.loads(client_config_path.read_text(encoding="utf-8-sig"))
        assert payload.get("connection_source") != "local_dev_unverified"
        return bool(payload.get("base_url") == e2e_front_door_url)

    wait_for(
        "setup wizard saved verified front-door URL",
        _setup_saved_verified_front_door,
        timeout=20.0,
    )
    saved_payload = json.loads(client_config_path.read_text(encoding="utf-8-sig"))
    evidence_path = _write_setup_front_door_evidence(
        artifact_dir=artifact_dir,
        repo_root=repo_root,
        front_door_url=e2e_front_door_url,
        backend_internal_url=e2e_base_url,
        persisted_client_base_url=str(saved_payload.get("base_url") or ""),
        connection_source=str(saved_payload.get("connection_source") or ""),
    )
    assert evidence_path.exists()
    QuickStartPage.wait(session).choose_sign_in()
    login = LoginPage.wait(session)
    login.sign_in(username=user.username, password=user.password)
    main = MainWindowPage.wait(session)
    wait_for("dashboard after first run setup", lambda: main.tabs, timeout=20.0)


def test_import_rejection_path_blocks_and_persists_nothing(
    artifact_dir: Path,
    e2e_base_url: str,
    make_backend_user: Any,
    launch_native_desktop: Any,
) -> None:
    user = make_backend_user(prefix="e2e_import_blocked", can_import=True)
    import_file = backend.write_requests_only_csv(
        artifact_dir / f"requests_only_{uuid.uuid4().hex[:6]}.csv"
    )

    assert backend.count_clients(agency_id=user.agency_id) == 0
    assert backend.count_listings(agency_id=user.agency_id) == 0

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
    wizard.wait_for_blocking_message(
        "Requests-only files aren't supported. Import clients with their requests in the same file."
    )

    assert backend.count_clients(agency_id=user.agency_id) == 0
    assert backend.count_listings(agency_id=user.agency_id) == 0


def test_import_cancel_path_reports_cancelled_without_ghost_state(
    artifact_dir: Path,
    e2e_base_url: str,
    make_backend_user: Any,
    launch_native_desktop: Any,
) -> None:
    user = make_backend_user(prefix="e2e_import_cancel", can_import=True)
    family_name = f"CancelFlow{_letters()}"
    phone = _phone("213559")
    import_file = backend.write_client_import_csv(
        artifact_dir / f"client_import_cancel_{uuid.uuid4().hex[:6]}.csv",
        family_name=family_name,
        phone=phone,
    )

    backend.schedule_next_import_pause(base_url=e2e_base_url, user=user, seconds=8.0)

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
    wait_for(
        "cancel-path import job exists",
        lambda: backend.latest_import_job(user_id=user.user_id, filename=import_file.name),
        timeout=30.0,
    )
    wizard.cancel_execution()

    job = backend.wait_for_import_job(
        user_id=user.user_id,
        filename=import_file.name,
        predicate=lambda candidate: str(
            (candidate.result_summary or {}).get("terminal_reason") or ""
        )
        == "cancelled",
        timeout=180.0,
    )
    assert str((job.result_summary or {}).get("terminal_reason") or "") == "cancelled"
    wizard.wait_for_summary_headline("Your import was cancelled")
    wizard.finish()
    assert backend.fetch_client_row(agency_id=user.agency_id, phone=phone) is None


def test_edit_client_via_ui_refreshes_and_persists(
    e2e_base_url: str,
    make_backend_user: Any,
    launch_native_desktop: Any,
) -> None:
    user = make_backend_user(prefix="e2e_edit_client")
    original_name = f"Edit Client {uuid.uuid4().hex[:6]}"
    updated_name = f"{original_name} Updated"
    phone = _phone("213662")
    backend.insert_existing_client(
        agency_id=user.agency_id,
        user_id=user.user_id,
        family_name=original_name,
        phone=phone,
        remarks="desktop e2e edit seed",
    )
    seeded_client_count = backend.count_clients(agency_id=user.agency_id)
    assert seeded_client_count == 1

    session = launch_native_desktop(username=user.username)
    main = login_to_main_window(
        session,
        username=user.username,
        password=user.password,
        base_url=e2e_base_url,
    )
    main.select_tab("clients")
    clients = ClientsPage(main, session)
    wait_for(
        "seeded client row visible",
        lambda: (
            clients.tree
            if backend.count_clients(agency_id=user.agency_id) == seeded_client_count
            else None
        ),
        timeout=20.0,
    )
    clients.open_first_listed_client()
    wait_for(
        "selected client loaded by phone",
        lambda: clients.current_phone() if clients.current_phone() == phone else None,
        timeout=20.0,
    )
    clear_and_type(child(main.window, auto_id="clientFamilyNameInput"), updated_name)
    clients.save_current(expected_text=updated_name)

    row = wait_for(
        "edited client persisted",
        lambda: backend.fetch_client_row(
            agency_id=user.agency_id,
            phone=phone,
        ),
        timeout=20.0,
    )
    assert row is not None
    assert str(row["family_name"]) == updated_name
    assert str(row["phone"]) == phone
    assert backend.count_clients(agency_id=user.agency_id) == seeded_client_count
    clients.open_first_listed_client()
    wait_for(
        "updated client loaded by phone",
        lambda: (
            clients.current_family_name() if clients.current_family_name() == updated_name else None
        ),
        timeout=20.0,
    )


def test_server_notification_toast_and_inbox_render(
    e2e_base_url: str,
    make_backend_user: Any,
    launch_native_desktop: Any,
) -> None:
    user = make_backend_user(prefix="e2e_notify")
    title = f"Desktop Notice {uuid.uuid4().hex[:6]}"
    body = f"Notification body {uuid.uuid4().hex[:8]}"
    initial_count = backend.notification_count(agency_id=user.agency_id, user_id=user.user_id)

    session = launch_native_desktop(username=user.username)
    main = login_to_main_window(
        session,
        username=user.username,
        password=user.password,
        base_url=e2e_base_url,
    )

    backend.publish_notification(base_url=e2e_base_url, user=user, title=title, body=body)
    main.wait_for_toast(title=title, body=body, timeout=30.0)
    wait_for(
        "notification unread badge",
        lambda: (
            child(main.window, auto_id="immoNotificationsButton").window_text()
            if "(1)" in child(main.window, auto_id="immoNotificationsButton").window_text()
            else None
        ),
        timeout=20.0,
    )

    wait_for(
        "notification persisted server-side",
        lambda: backend.notification_count(agency_id=user.agency_id, user_id=user.user_id)
        > initial_count,
        timeout=20.0,
    )


def test_match_screen_survives_transient_backend_failure(
    e2e_base_url: str,
    make_backend_user: Any,
    launch_native_desktop: Any,
) -> None:
    user = make_backend_user(prefix="e2e_match_fault")
    seed = backend.seed_match_entities(
        user=user,
        client_name=f"Match Fault {uuid.uuid4().hex[:6]}",
        listing_owner=f"Match Fault Listing {uuid.uuid4().hex[:6]}",
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
    match_page.select_client(seed.client_name)

    backend.inject_fault(
        base_url=e2e_base_url,
        user=user,
        route_template="matches/client/<int:client_id>/",
        status_code=500,
        detail="Injected desktop E2E match failure.",
        code="E2E_MATCH_FAILURE",
    )
    match_page.run_selected()
    main.wait_for_notice(
        title="Match run didn't finish",
        body="We couldn't finish matching right now.",
        timeout=30.0,
    )

    match_page.run_selected()
    match_page.wait_for_results()
    wait_for(
        "match results recovered after transient failure",
        lambda: backend.api_client_match_total(
            base_url=e2e_base_url,
            user=user,
            client_id=seed.client_id,
        )
        > 0,
        timeout=30.0,
    )


def test_agency_settings_save_persists_and_survives_reload(
    e2e_base_url: str,
    make_backend_user: Any,
    launch_native_desktop: Any,
) -> None:
    user = make_backend_user(prefix="e2e_settings")
    new_name = f"Agency {uuid.uuid4().hex[:6]}"

    session = launch_native_desktop(username=user.username)
    main = login_to_main_window(
        session,
        username=user.username,
        password=user.password,
        base_url=e2e_base_url,
    )
    settings = main.open_agency_settings()
    settings.set_agency_name(new_name)
    settings.save()

    wait_for(
        "agency settings persisted",
        lambda: (
            backend.api_fetch_agency_settings(base_url=e2e_base_url, user=user).get("agency_name")
            if backend.api_fetch_agency_settings(base_url=e2e_base_url, user=user).get(
                "agency_name"
            )
            == new_name
            else None
        ),
        timeout=20.0,
    )

    session_reloaded = launch_native_desktop(username=user.username)
    main_reloaded = login_to_main_window(
        session_reloaded,
        username=user.username,
        password=user.password,
        base_url=e2e_base_url,
    )
    settings_reloaded = main_reloaded.open_agency_settings()
    wait_for(
        "reloaded agency settings name",
        lambda: (
            settings_reloaded.current_agency_name()
            if settings_reloaded.current_agency_name() == new_name
            else None
        ),
        timeout=20.0,
    )


def test_deactivated_user_cannot_mutate_on_next_protected_action(
    e2e_base_url: str,
    make_backend_user: Any,
    launch_native_desktop: Any,
) -> None:
    user = make_backend_user(prefix="e2e_deactivated_session")
    owner = backend.create_owner_user_for_agency(
        agency_id=user.agency_id,
        prefix="e2e_security_owner",
    )
    family_name = f"Rejected Session {uuid.uuid4().hex[:6]}"
    phone = _phone("213663")

    session = launch_native_desktop(username=user.username)
    main = login_to_main_window(
        session,
        username=user.username,
        password=user.password,
        base_url=e2e_base_url,
    )
    main.select_tab("clients")
    clients = ClientsPage(main, session)

    step_up = backend.step_up_token(base_url=e2e_base_url, user=owner)
    backend.deactivate_user_via_api(
        base_url=e2e_base_url,
        owner=owner,
        target_user_id=user.user_id,
        step_up=step_up,
    )
    wait_for(
        "desktop user deactivated backend truth",
        lambda: True if not backend.user_is_active(user_id=user.user_id) else None,
        timeout=20.0,
    )

    clients.create_client_expect_auth_error(family_name=family_name, phone=phone)
    assert (
        backend.fetch_client_row(
            agency_id=user.agency_id,
            phone=phone,
        )
        is None
    )
