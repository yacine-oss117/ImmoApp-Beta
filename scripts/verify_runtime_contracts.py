from __future__ import annotations

import re
import subprocess
from pathlib import Path

from repo_layout import COMPOSE_PROD_YML, COMPOSE_YML, RUN_WEB_SH

REPO_ROOT = Path(__file__).resolve().parents[1]


def _read(path: str | Path) -> str:
    file_path = Path(path)
    if not file_path.is_absolute():
        file_path = REPO_ROOT / file_path
    if not file_path.exists():
        raise SystemExit(f"verify_runtime_contracts: missing required file {path}")
    return file_path.read_text(encoding="utf-8")


def _assert_no_legacy_cache_all() -> None:
    checks: tuple[tuple[str, str], ...] = (
        ("core/data/match_cache_read.py", "def get_all_cached_counts("),
        ("core/data/match_cache_read.py", "def get_dirty_client_ids("),
        ("core/data/match_cache_read.py", "def get_missing_client_ids("),
        ("core/data/match_cache.py", "get_all_cached_counts"),
        ("server/services/match_cache.py", "def get_all_cached_counts("),
    )
    for rel_path, token in checks:
        text = _read(rel_path)
        if token in text:
            raise SystemExit(
                "verify_runtime_contracts: legacy cache contract token found "
                f"in {rel_path}: {token}"
            )


def _assert_no_legacy_schedule_intervals() -> None:
    text = _read("server/immoapp_server/settings_database.py")
    for token in ('"schedule": 60 * 60 * 24', '"schedule": 60 * 60 * 24 * 7'):
        if token in text:
            raise SystemExit(
                "verify_runtime_contracts: legacy interval schedule token found "
                f"in settings_database.py: {token}"
            )


def _assert_worker_beat_healthchecks() -> None:
    compose = _read(COMPOSE_YML)
    if "disable: true" in compose:
        raise SystemExit(
            "verify_runtime_contracts: compose.yml contains disabled healthchecks; "
            "worker/beat healthchecks must be active."
        )
    for service in ("worker:", "worker-match:", "beat:"):
        if service not in compose:
            raise SystemExit(
                "verify_runtime_contracts: missing service definition in compose.yml: " f"{service}"
            )
    required = (
        "inspect ping -d",
        "--pidfile=/tmp/celerybeat.pid",
        "kill -0 $(cat /tmp/celerybeat.pid)",
        "-Q match_pairs -c ${CELERY_MATCH_PAIRS_CONCURRENCY_DOCKER:?hub_runtime_profile_required}",
    )
    for token in required:
        if token not in compose:
            raise SystemExit(
                "verify_runtime_contracts: missing worker/beat healthcheck token "
                f"in compose.yml: {token}"
            )


def _assert_web_runtime_contract() -> None:
    compose = _read(COMPOSE_YML)
    prod = _read(COMPOSE_PROD_YML)
    entrypoint = _read(RUN_WEB_SH)
    required_compose_tokens = (
        "IMMOAPP_WEB_RUNTIME: ${IMMOAPP_WEB_RUNTIME_DOCKER:-gunicorn_uvicorn}",
        "IMMOAPP_MATCH_BUILD_PIPELINE: ${IMMOAPP_MATCH_BUILD_PIPELINE_DOCKER:-direct}",
        "GUNICORN_WORKERS: ${GUNICORN_WORKERS_DOCKER:?hub_runtime_profile_required}",
        "ASGI_THREADS: ${ASGI_THREADS_DOCKER:?hub_runtime_profile_required}",
        "PG_POOL_MAX: ${PG_POOL_MAX_WEB_DOCKER:?hub_runtime_profile_required}",
        '"${IMMOAPP_WEB_BIND_HOST:-127.0.0.1}:${IMMOAPP_BACKEND_HOST_PORT:-8000}:8000"',
        "IMMOAPP_HUB_WORKER_CONCURRENCY: ${IMMOAPP_HUB_WORKER_CONCURRENCY:?hub_runtime_profile_required}",
        "IMMOAPP_HUB_IMPORT_CONCURRENCY: ${IMMOAPP_HUB_IMPORT_CONCURRENCY:?hub_runtime_profile_required}",
        "IMMOAPP_HUB_MATCH_CONCURRENCY: ${IMMOAPP_HUB_MATCH_CONCURRENCY:?hub_runtime_profile_required}",
        "IMMOAPP_HUB_DB_POOL_MAX: ${IMMOAPP_HUB_DB_POOL_MAX:?hub_runtime_profile_required}",
        "exec /app/deployment/docker/run_web.sh",
    )
    for token in required_compose_tokens:
        if token not in compose:
            raise SystemExit(
                "verify_runtime_contracts: missing web runtime token in compose.yml: " f"{token}"
            )
    if "IMMOAPP_WEB_RUNTIME: ${IMMOAPP_WEB_RUNTIME_DOCKER:-gunicorn_uvicorn}" not in prod:
        raise SystemExit(
            "verify_runtime_contracts: compose.prod.yml must pin the gunicorn_uvicorn web runtime."
        )
    required_entrypoint_tokens = (
        'runtime="${IMMOAPP_WEB_RUNTIME:-gunicorn_uvicorn}"',
        "uvicorn_worker.UvicornWorker",
        "server.immoapp_server.asgi:application",
        "exec daphne -b 0.0.0.0 -p 8000 server.immoapp_server.asgi:application",
    )
    for token in required_entrypoint_tokens:
        if token not in entrypoint:
            raise SystemExit(
                "verify_runtime_contracts: missing web entrypoint token in deployment/docker/run_web.sh: "
                f"{token}"
            )


def _assert_hub_network_boundary() -> None:
    compose = _read(COMPOSE_YML)
    for token in (
        '"127.0.0.1:5432:5432"',
        '"127.0.0.1:5672:5672"',
        '"127.0.0.1:6379:6379"',
        '"127.0.0.1:8200:8200"',
        '"127.0.0.1:9000:9000"',
        '"127.0.0.1:9001:9001"',
    ):
        if token not in compose:
            raise SystemExit(
                "verify_runtime_contracts: infra port must stay localhost-bound: " f"{token}"
            )
    for forbidden in (
        "0.0.0.0:5432",
        "0.0.0.0:5672",
        "0.0.0.0:6379",
        "0.0.0.0:8200",
        "0.0.0.0:9000",
        "0.0.0.0:9001",
    ):
        if forbidden in compose:
            raise SystemExit(
                "verify_runtime_contracts: infra port is exposed to LAN: " f"{forbidden}"
            )
    for token in (
        'profiles: ["hub-front-door"]',
        '"${IMMOAPP_CADDY_BIND_HOST:-127.0.0.1}:${IMMOAPP_HUB_FRONT_DOOR_PORT:-8000}:8000"',
    ):
        if token not in compose:
            raise SystemExit(
                "verify_runtime_contracts: Caddy must be the explicit Hub front-door profile: "
                f"{token}"
            )
    if '"${IMMOAPP_WEB_BIND_HOST:-127.0.0.1}:${WEB_PORT:-8000}:8000"' in compose:
        raise SystemExit(
            "verify_runtime_contracts: final Hub mode must not publish backend directly on WEB_PORT."
        )


def _assert_hub_runtime_detection_contract() -> None:
    detector = _read("scripts/detect_hub_runtime.ps1")
    setup = _read("scripts/setup_office_hub.ps1")
    install = _read("scripts/collect_hub_install_evidence.ps1")
    status = _read("scripts/collect_hub_status_evidence.ps1")
    common = _read("scripts/common.ps1")
    stack = _read("scripts/stack.ps1")
    network = _read("scripts/verify_hub_network_boundary.ps1")
    register = _read("scripts/register_managed_hub_runtime_provider.ps1")
    build_package = _read("scripts/build_managed_hub_runtime_package.ps1")
    install_provider = _read("scripts/install_managed_hub_runtime_provider.ps1")
    verify_provider = _read("scripts/verify_managed_hub_runtime_provider.ps1")
    local_proof = _read("scripts/verify_hub_m1_local_proof.ps1")
    for token in (
        "immoapp_hub_runtime_detection",
        "immoapp_hub_runtime_provider",
        "manual_docker_desktop",
        "managed_container_runtime",
        "native_windows_services",
        "unavailable",
        "agency_install_status",
        "reason_code",
        "invalid_provider_config",
        "internal_proof_status",
        "proof_only",
        "NO_GO",
        "managed_runtime_missing_inventory",
        "managed_runtime_secret_in_config",
        "managed_runtime_outside_approved_root",
        "managed_runtime_missing_source_provenance",
        "managed_runtime_noncanonical_provider_config",
        "noncanonical_runtime_root",
        "managed_runtime_reparse_point_not_allowed",
        "managed_runtime_resolved_path_outside_approved_root",
        "native_services_deferred",
        "Assert-ImmoAppManagedRuntimePackageInventoryReady",
        "Assert-NoProviderSecretFields",
        "provider_validation_status",
    ):
        if token not in detector:
            raise SystemExit(
                "verify_runtime_contracts: missing Hub runtime detection token: " f"{token}"
            )
    if "Set-Content -LiteralPath $OutputJson" in detector:
        raise SystemExit(
            "verify_runtime_contracts: detect_hub_runtime.ps1 must use safe JSON writes for OutputJson."
        )
    if "Write-ImmoAppSafeJson -Path $OutputJson" not in detector:
        raise SystemExit(
            "verify_runtime_contracts: detect_hub_runtime.ps1 missing safe JSON OutputJson writer."
        )
    for token in (
        "Get-ImmoAppHubRequiredComposeServices",
        "Invoke-ImmoAppHubCompose",
        "Get-ImmoAppHubComposeInvocation",
        "Get-ImmoAppCanonicalRuntimePaths",
        "Get-ImmoAppCanonicalHubRuntimeProviderConfigPath",
        "Test-ImmoAppUsingCanonicalRuntimeRoot",
        "Test-ImmoAppResolvedPathUnderRoot",
        "Test-ImmoAppPathHasReparsePoint",
        "Get-ImmoAppSensitiveFieldPattern",
        "Assert-ImmoAppCanonicalProviderConfigPathSafe",
        "Assert-ImmoAppProviderSnapshotPathSafe",
        "Assert-ImmoAppManagedRuntimeVendorProvenance",
        "Get-ImmoAppStrictRuntimeTreeInventory",
        "Get-ImmoAppSafeZipInventory",
        "Write-ImmoAppSafeJson",
        "Assert-ImmoAppManagedRuntimePackageInventoryReady",
        "Assert-ImmoAppStrictBackupRestoreEvidence",
        "Test-ImmoAppStrictBackupRestoreEvidence",
        "managed_runtime_inventory_hash_mismatch",
        "managed_runtime_inventory_forbidden_content",
        "managed_runtime_package_missing",
        "managed_runtime_package_hash_mismatch",
        "managed_runtime_installed_file_hash_mismatch",
        "managed_runtime_external_artifact_requires_vendor_provenance",
    ):
        if token not in common:
            raise SystemExit(
                "verify_runtime_contracts: missing shared Hub runtime helper: " f"{token}"
            )
    for forbidden in ("& docker compose", "docker compose @", "& docker ps"):
        for rel_path, text in (
            ("scripts/stack.ps1", stack),
            ("scripts/collect_hub_status_evidence.ps1", status),
        ):
            if forbidden in text:
                raise SystemExit(
                    "verify_runtime_contracts: runtime script bypasses Hub runtime helper: "
                    f"{rel_path}: {forbidden}"
                )
    for rel_path, text in (
        ("scripts/setup_office_hub.ps1", setup),
        ("scripts/collect_hub_install_evidence.ps1", install),
        ("scripts/collect_hub_status_evidence.ps1", status),
    ):
        if "detect_hub_runtime.ps1" not in text or "runtime_detection" not in text:
            raise SystemExit(
                "verify_runtime_contracts: Hub evidence path does not consume runtime detection: "
                f"{rel_path}"
            )
    for token in (
        "runtime_state",
        "compose_state",
        "status_reason_code",
        "stack_stopped",
        "partial_stack_required_services_missing",
        "service_missing",
        "health_endpoint_unreachable",
    ):
        if token not in status:
            raise SystemExit(
                "verify_runtime_contracts: missing structured Hub status token: " f"{token}"
            )
    for token in (
        "ConfirmManagedRuntimeProof",
        "Get-ImmoAppHubRuntimeProviderConfigPath",
    ):
        if token not in register:
            raise SystemExit(
                "verify_runtime_contracts: missing managed provider registration token: " f"{token}"
            )
    if "immoapp_hub_runtime_provider_registration" not in common:
        raise SystemExit(
            "verify_runtime_contracts: shared provider registration owner must emit provider registration evidence."
        )
    for token in (
        "immoapp_hub_network_boundary_evidence",
        "unsafe_publishers",
        "approved_lan_facing_service",
        '"caddy"',
        "front_door_url",
        "caddy_status",
        "backend_internal_status",
        "caddy_admin_lan_exposed",
        "web_api_health_status",
        "infra_exposure_status",
        "boundary_result",
        "proof_scope",
        "local_compose_boundary",
        "external_lan_probe_performed",
    ):
        if token not in network:
            raise SystemExit(
                "verify_runtime_contracts: missing Hub network boundary token: " f"{token}"
            )
    for token in (
        "Get-ImmoAppHubIdentityPath",
        "Assert-ImmoAppHubDisplayName",
        "Write-ImmoAppHubIdentity",
        "Read-ImmoAppHubIdentity",
        "Get-ImmoAppHubIdentityDisplayNameHelp",
    ):
        if token not in common:
            raise SystemExit(
                "verify_runtime_contracts: missing Hub identity helper token: " f"{token}"
            )
    setup = _read("scripts/setup_office_hub.ps1")
    manager = _read("scripts/hub_manager.ps1")
    hub_manager_app = _read("app/hub_manager_app.py")
    hub_manager_actions = _read("app/hub_manager_actions.py")
    discovery = _read("app/services/server_discovery.py")
    setup_wizard = _read("app/widgets/setup_wizard.py")
    setup_wizard_ui = _read("app/widgets/setup_wizard_ui.py")
    endpoint_script = _read("scripts/set_client_api_endpoint.ps1")
    api_config = _read("app/services/api_config.py")
    caddyfile = _read("deployment/proxy/Caddyfile")
    e2e_runner = _read("scripts/test_e2e_desktop.ps1")
    e2e_release = _read("scripts/run_e2e_release_validation.ps1")
    e2e_conftest = _read("app/tests/e2e_desktop/conftest.py")
    e2e_backend = _read("app/tests/e2e_desktop/backend.py")
    e2e_journeys = _read("app/tests/e2e_desktop/test_journeys.py")
    build_installer = _read("scripts/build_desktop_installer.ps1")
    installer = _read("deployment/installer/ImmoAppBeta.iss")
    lifecycle = _read("scripts/collect_install_lifecycle_evidence.ps1")
    installed_front_door = _read("scripts/collect_installed_desktop_front_door_evidence.ps1")
    beta_validation = _read("scripts/run_beta_release_validation.ps1")
    for token in (
        "HubDisplayName",
        "HubDesktop setup requires -HubDisplayName",
        "Write-ImmoAppHubIdentity",
        "foundation_plan_status",
        "foundation_applied_status",
        "dry_run_reason",
        "validate_only_is_planning_evidence_not_applied_setup_proof",
        "IMMOAPP_CADDY_BIND_HOST",
        "hub-front-door",
    ):
        if token not in setup and token not in common:
            raise SystemExit(
                "verify_runtime_contracts: missing final Hub setup identity/front-door token: "
                f"{token}"
            )
    if "rename-hub" not in manager or "set_hub_identity.ps1" not in manager:
        raise SystemExit("verify_runtime_contracts: Hub Manager must support rename-hub.")
    for token in (
        'HUB_MANAGER_SCRIPT_NAME = "hub_manager.ps1"',
        'HUB_MANAGER_EXE_NAME = "ImmoApp Hub Manager.exe"',
        "build_hub_manager_command",
        "hidden_child_process_kwargs",
        "CREATE_NO_WINDOW",
        "STARTF_USESHOWWINDOW",
        '"-OutputJson"',
        "install-runtime-artifact",
    ):
        if token not in hub_manager_app and token not in hub_manager_actions:
            raise SystemExit(
                "verify_runtime_contracts: installed Hub Manager app is missing wrapper token: "
                f"{token}"
            )
    if "stack.ps1" in hub_manager_app or "stack.ps1" in hub_manager_actions:
        raise SystemExit(
            "verify_runtime_contracts: Hub Manager app must delegate only to hub_manager.ps1, not stack.ps1."
        )
    if (
        '-Name "ImmoApp Hub Manager" -ScriptPath $hubManagerScript.path -ManagerAppPath $hubManagerAppPath -Action "status"'
        in setup
    ):
        raise SystemExit(
            "verify_runtime_contracts: Hub Manager dashboard shortcut must not launch a one-shot status action."
        )
    if (
        '$shortcut.Arguments = if ([string]::IsNullOrWhiteSpace($Action)) { "" } else { "--action $Action" }'
        not in setup
    ):
        raise SystemExit(
            "verify_runtime_contracts: Hub Manager app shortcuts must allow dashboard launch without action arguments."
        )
    for token in (
        '#define MyHubManagerExeName "ImmoApp Hub Manager.exe"',
        'Filename: "{app}\\{#MyHubManagerExeName}"',
        "--action start",
        "--action finish-hub-setup",
    ):
        if token not in installer:
            raise SystemExit(
                "verify_runtime_contracts: installer must expose installed Hub Manager app shortcut token: "
                f"{token}"
            )
    if (
        'Name: "{autoprograms}\\ImmoApp Hub\\Start ImmoApp Hub"; Filename: "{sys}\\WindowsPowerShell'
        in installer
    ):
        raise SystemExit(
            "verify_runtime_contracts: Hub shortcuts must not expose PowerShell directly."
        )
    for token in (
        "PyInstaller Hub Manager bundle",
        "app\\hub_manager_app.py",
        "ImmoApp Hub Manager.exe",
    ):
        if token not in build_installer:
            raise SystemExit(
                "verify_runtime_contracts: installer builder must package Hub Manager app token: "
                f"{token}"
            )
    for token in (
        "Test-ImmoAppInstalledSource",
        "Get-ImmoAppCurrentScriptRootSource",
        "installed_app",
        "installed_programdata",
        "repo_dev",
        "_internal\\app\\installer_build_identity.json",
    ):
        if token not in common:
            raise SystemExit(
                "verify_runtime_contracts: Hub script source resolver must distinguish installed app/programdata from repo dev: "
                f"{token}"
            )
    install_evidence = _read("scripts/collect_hub_install_evidence.ps1")
    for token in (
        "Test-ImmoAppInstalledSource -Source ([string]$hubManagerScript.source)",
        "Test-ImmoAppInstalledSource -Source ([string]$desktopExe.source)",
        "real agency install requires installed source",
    ):
        if token not in install_evidence:
            raise SystemExit(
                "verify_runtime_contracts: Hub install evidence must accept installed_app/installed_programdata source labels: "
                f"{token}"
            )
    for token in (
        '[string]$hubManagerScript.source -ne "installed"',
        '[string]$desktopExe.source -ne "installed"',
    ):
        if token in install_evidence:
            raise SystemExit(
                "verify_runtime_contracts: Hub install evidence must not hardcode only the legacy installed source label: "
                f"{token}"
            )
    for token in (
        "Get-ImmoAppHubFoundationDirectoryEvidence",
        "Ensure-ImmoAppSafeRuntimeDirectory",
        "Get-ImmoAppHubFirewallRuleEvidence",
        "Ensure-ImmoAppHubFirewallRule",
        "already_present_valid",
        "already_present_invalid",
        "skipped_local_only",
        "skipped_no_lan_requested",
    ):
        if token not in common:
            raise SystemExit(
                "verify_runtime_contracts: missing Hub foundation safety/firewall helper: "
                f"{token}"
            )
    if "New-Item -ItemType Directory -Path $path -Force" in common:
        raise SystemExit(
            "verify_runtime_contracts: runtime layout must use safe directory creation, not raw New-Item."
        )
    for rel_path, text in (
        ("scripts/setup_office_hub.ps1", setup),
        ("scripts/collect_hub_install_evidence.ps1", install),
        ("scripts/collect_hub_status_evidence.ps1", status),
    ):
        if "docker_compose_hidden_from_user = $true" in text:
            raise SystemExit(
                "verify_runtime_contracts: runtime visibility must not claim Docker/Compose hidden unconditionally: "
                f"{rel_path}"
            )
    for token in (
        "Assert-InstallerRoleEvidence",
        "validate-only planning evidence",
        "foundation_applied_status",
        "created/already_present_valid Caddy firewall rule",
        "Test-ImmoAppInstalledSource -Source ([string]$data.hub_manager_script_source)",
        "Test-ImmoAppInstalledSource -Source ([string]$data.desktop_exe_source)",
    ):
        if token not in beta_validation:
            raise SystemExit(
                "verify_runtime_contracts: beta validation must reject dry-run/skipped-firewall Hub foundation evidence: "
                f"{token}"
            )
    for token in (
        "immoapp_hub_discovery",
        "hub_display_name",
        "front_door_url",
        "machine_hostname_readonly",
        'schema_version = int(str(payload.get("schema_version") or "0"))',
        "except (TypeError, ValueError)",
    ):
        if token not in discovery:
            raise SystemExit(
                "verify_runtime_contracts: discovery must advertise only Hub front-door metadata: "
                f"{token}"
            )
    if "admin off" not in caddyfile or "X-ImmoApp-Front-Door" not in caddyfile:
        raise SystemExit(
            "verify_runtime_contracts: Caddy front door must disable admin and mark responses."
        )
    if "_manual_url.setText(front_door_url)" in setup_wizard:
        raise SystemExit(
            "verify_runtime_contracts: setup wizard must not auto-fill visible manual URL from discovery."
        )
    if "from app.services.api_config import set_verified_api_config" not in setup_wizard:
        raise SystemExit(
            "verify_runtime_contracts: setup wizard must use verified front-door endpoint save."
        )
    for token in (
        "setupWizardFoundCard",
        "Verified ImmoApp Hub",
        "Front-door port",
        "same office Wi-Fi",
        "Guest Wi-Fi",
        "backend/internal",
        "Hub Manager > Connection details",
    ):
        if token not in setup_wizard and token not in setup_wizard_ui:
            raise SystemExit(
                "verify_runtime_contracts: setup wizard Phase 1 Hub UX token missing: " f"{token}"
            )
    if (
        "set_verified_api_config" not in endpoint_script
        or "DevBypassFrontDoorVerification" not in endpoint_script
    ):
        raise SystemExit(
            "verify_runtime_contracts: set_client_api_endpoint.ps1 must verify front-door by default and expose only an explicit dev bypass."
        )
    for token in (
        "local_dev_unverified",
        "evidence cannot use local_dev_unverified endpoint source",
    ):
        if token not in endpoint_script and token not in _read(
            "scripts/run_beta_release_validation.ps1"
        ):
            raise SystemExit(
                "verify_runtime_contracts: local dev endpoint source must be visibly blocked from release GO."
            )
    if 'env_base_url = os.environ.get("IMMOAPP_API_BASE_URL")' not in api_config:
        raise SystemExit(
            "verify_runtime_contracts: API env override must be normalized independently from file connection_source."
        )
    for token, text in (
        ("--e2e-front-door-url", e2e_conftest),
        ("backend.ensure_front_door_ready(value)", e2e_conftest),
        ("X-ImmoApp-Front-Door", e2e_backend),
        ("immoapp_hub_front_door_identity", e2e_backend),
        ("UseHubFrontDoor", e2e_runner),
        ("IMMOAPP_E2E_FRONT_DOOR_URL", e2e_runner),
        ('COMPOSE_PROFILES = "hub-front-door"', e2e_runner),
        ('IMMOAPP_BACKEND_HOST_PORT = "18000"', e2e_runner),
        ("UseHubFrontDoor = $true", e2e_release),
        ("e2e_front_door_url", e2e_journeys),
        ("connect_manual(e2e_front_door_url)", e2e_journeys),
    ):
        if token not in text:
            raise SystemExit(
                "verify_runtime_contracts: setup-wizard E2E must use verified Caddy front-door proof: "
                f"{token}"
            )
    if "connect_manual(e2e_base_url)" in e2e_journeys:
        raise SystemExit(
            "verify_runtime_contracts: setup-wizard E2E must not connect through direct backend e2e_base_url."
        )
    for token in (
        "immoapp_setup_wizard_front_door_e2e_evidence",
        "front_door_header",
        "persisted_client_base_url",
        "connection_source",
    ):
        if token not in e2e_journeys:
            raise SystemExit(
                "verify_runtime_contracts: setup-wizard front-door E2E must emit machine-readable release proof: "
                f"{token}"
            )
    for token in (
        "AllowRepoLocalReleaseArtifacts",
        "C:\\ProgramData\\ImmoApp\\release_artifacts",
        "Stable release artifacts must use C:\\ProgramData\\ImmoApp\\release_artifacts",
        "immoapp_installer_package_inventory",
        'installer_role_support = "desktop_and_or_hub"',
        "supports_desktop_only = $true",
        "supports_hub_only = $true",
        "supports_desktop_and_hub = $true",
        "Copy-HubInstallerPayload",
        "Copy-ManagedWsl2RuntimeGeneratedPayload",
        "ManagedWslRootfsTarPath",
        "ManagedWslImageBundleArchivePath",
        "ManagedWslArtifactRoot",
        "ManagedWslArtifactInventoryPath",
        "ExpectedSourceCommitSha",
        "runtime artifact inventory source commit does not match installer source commit",
        "deployment/managed-runtime/rootfs/ImmoAppRuntime.rootfs.tar",
        "deployment/managed-runtime/images/immoapp-runtime-images.tar",
        "deployment/managed-runtime/config/managed_wsl2_runtime_image_bundle_inventory.json",
        "deployment/managed-runtime/config/managed_wsl2_runtime_artifact_inventory.json",
        "deployment/managed-runtime/artifact/managed-wsl2-artifact",
        "deployment/managed-runtime/artifact/managed-wsl2-artifact/bin/backup-managed-hub.ps1",
        "core/runtime/hub_runtime_profile.py",
        "core/runtime/__init__.py",
        "core/env_files.py",
        "core/env_flags.py",
        "core/paths.py",
        "core/__init__.py",
        "core/models_audit.py",
        "Get-InstallerCorePayloadFiles",
        "scripts/register_managed_hub_runtime_provider.ps1",
        "scripts/uninstall_managed_hub_runtime_provider.ps1",
        "scripts/bootstrap_managed_wsl2_runtime.ps1",
        "required_file_checks",
        "forbidden_path_matches",
        "package_inventory_sha256",
    ):
        if token not in build_installer:
            raise SystemExit(
                "verify_runtime_contracts: desktop installer artifacts must default outside the repo: "
                f"{token}"
            )
    hub_payload_block = build_installer.split("function Get-InstallerHubPayloadFiles", 1)[1].split(
        "function Test-InstallerHubPayloadPathAllowed", 1
    )[0]
    for forbidden in (
        "scripts/build_managed_wsl2_runtime_artifact.ps1",
        "scripts/build_managed_wsl2_runtime_rootfs.ps1",
        "scripts/build_managed_wsl2_runtime_image_bundle.ps1",
        "scripts/stack.ps1",
        "scripts/backup_release_bundle.ps1",
        "scripts/verify_release_backup_integrity.py",
        "scripts/verify_release_bundle_manifest.py",
        "deployment/compose/compose.yml",
        "deployment/compose/compose.windows.yml",
        "deployment/compose/compose.app.yml",
        "deployment/proxy/Caddyfile",
        "deployment/managed-runtime/bin/start-managed-hub",
        "deployment/managed-runtime/compose/compose.yaml",
    ):
        if forbidden in hub_payload_block:
            raise SystemExit(
                "verify_runtime_contracts: Hub installer must not package developer/build-machine runtime script: "
                f"{forbidden}"
            )
    hub_manager = _read("scripts/hub_manager.ps1")
    for token in (
        "Get-ImmoAppCurrentScriptRootSource",
        "managed_runtime_provider_missing",
        "Installed Hub Manager requires an ImmoApp-managed runtime provider",
    ):
        if token not in hub_manager:
            raise SystemExit(
                "verify_runtime_contracts: installed Hub Manager must fail closed instead of using dev stack: "
                f"{token}"
            )
    for token in (
        "Choose what to install",
        "Install ImmoApp Desktop",
        "Set up this computer as Office Hub",
        "HubRoleSelectOne",
        "wpSelectTasks",
        "Result := not IsDesktopSelected()",
        "HubRolePage.Values[0] := True",
        "HubRolePage.Values[1] := False",
        "ApplyCommandLineRoleSelection",
        "IMMOAPPINSTALLMODE",
        "IMMOAPPHUBNAME",
        "Invalid /IMMOAPPINSTALLMODE",
        "Hub installs require /IMMOAPPHUBNAME",
        "RaiseException",
        "IsDesktopSelected",
        "IsHubSelected",
        "Name this office Hub",
        "RunHubDesktopFoundationSetup",
        "ShellExec('runas'",
        "HubSetupFinishLater",
        "if not WizardSilent() then begin",
        "if WizardSilent() then begin",
        "WriteHubSetupDeferredEvidence(EvidencePath, CurrentSetupRunId)",
        "silent_install_defers_elevated_hub_setup",
        '"setup_deferred":true',
        "HubSetupEvidenceAppliedGo",
        "hub_setup_launch_requested",
        "CurrentSetupRunId := NewSetupRunId()",
        "JsonContainsStringField(JsonText, 'setup_run_id', SetupRunId)",
        "JsonContainsStringField(JsonText, 'proof_result', 'GO')",
        "JsonContainsBooleanField(JsonText, 'selected_install_hub', True)",
        "JsonContainsStringField(JsonText, 'install_mode', 'hub_only')",
        "JsonContainsStringField(JsonText, 'install_mode', 'desktop_and_hub')",
        "JsonContainsBooleanField(JsonText, 'elevated_setup_observed', True)",
        "JsonContainsBooleanField(JsonText, 'lan_access_enabled', True)",
        "JsonContainsStringField(JsonText, 'local_port', '8000')",
        "GetSelectedHubSetupRole",
        "Result := 'HubOnly'",
        "' -Role ' + GetSelectedHubSetupRole()",
        "-SetupRunId",
        "-CreateFirewallRule -NoAutoStart -NoStartHub",
        "[InstallDelete]",
        r'Type: files; Name: "{app}\scripts\build_managed_wsl2_runtime_artifact.ps1"',
        r'Type: files; Name: "{app}\scripts\build_managed_wsl2_runtime_rootfs.ps1"',
        r'Type: files; Name: "{app}\scripts\build_managed_wsl2_runtime_image_bundle.ps1"',
    ):
        if token not in installer:
            raise SystemExit(
                "verify_runtime_contracts: installer must expose role-aware Hub setup UX: "
                f"{token}"
            )
    silent_branch = installer.split("if WizardSilent() then begin", 1)[1].split(
        "SetupLaunched := ShellExec('runas'",
        1,
    )[0]
    for token in (
        "WriteHubSetupDeferredEvidence(EvidencePath, CurrentSetupRunId)",
        "exit;",
    ):
        if token not in silent_branch:
            raise SystemExit(
                "verify_runtime_contracts: silent Hub install must defer elevated setup before runas: "
                f"{token}"
            )
    for forbidden in (
        "Desktop client only",
        "Office Hub + desktop on this computer",
        "IsHubDesktopRoleSelected",
        "Pos('\"go\"'",
        "Random(",
    ):
        if forbidden in installer:
            raise SystemExit(
                "verify_runtime_contracts: installer must not retain old radio labels or fuzzy GO checks: "
                f"{forbidden}"
            )
    for forbidden in (
        "JsonContainsStringField(JsonText, 'firewall_status', 'skipped_local_only')",
    ):
        if forbidden in installer:
            raise SystemExit(
                "verify_runtime_contracts: installer Hub setup must not accept local-only firewall evidence: "
                f"{forbidden}"
            )
    for token in (
        "finish-hub-setup",
        "Resolve-HubManagerPowerShellPath",
        "System32\\WindowsPowerShell\\v1.0\\powershell.exe",
        "Quote-WindowsCommandLineArgument",
        "Join-WindowsCommandLineArguments",
        "Remove-Item -LiteralPath $evidencePath -Force",
        "-FilePath $powerShellPath",
        "-ArgumentList $arguments",
        "-Verb RunAs",
    ):
        if token not in manager:
            raise SystemExit(
                "verify_runtime_contracts: Hub Manager finish-hub-setup must use safe quoted elevated launch: "
                f"{token}"
            )
    finish_block = manager.split('"finish-hub-setup" {', 1)[1]
    if "-Action start" in finish_block:
        raise SystemExit(
            "verify_runtime_contracts: finish-hub-setup must not start backend services."
        )
    if "-ValidateOnly" in installer:
        raise SystemExit(
            "verify_runtime_contracts: installer Hub role must run applied setup, not ValidateOnly."
        )
    for token in (
        "schema_version = 3",
        "install_mechanics_status",
        "installed_app_front_door_connectivity_status",
        "desktop_installer_release_proof_status",
        "installed_app_front_door_evidence_not_supplied",
    ):
        if token not in lifecycle:
            raise SystemExit(
                "verify_runtime_contracts: lifecycle evidence must split mechanics from front-door connectivity: "
                f"{token}"
            )
    for token in (
        "immoapp_installed_desktop_front_door_evidence",
        "X-ImmoApp-Front-Door",
        "immoapp_hub_front_door_identity",
        "local_dev_unverified_not_allowed",
        "persisted_config_missing",
        "persisted_config_not_front_door_url",
    ):
        if token not in installed_front_door:
            raise SystemExit(
                "verify_runtime_contracts: installed desktop front-door proof must be strict: "
                f"{token}"
            )
    for token in (
        "SetupWizardFrontDoorE2eEvidenceJson",
        "InstalledDesktopFrontDoorEvidenceJson",
        "setup_wizard_front_door_e2e",
        "installed_app_front_door_connectivity",
        "full_desktop_installer_release_proof",
        "desktop_installer_release_proof_status",
    ):
        if token not in beta_validation:
            raise SystemExit(
                "verify_runtime_contracts: beta validation must expose full desktop installer proof phases: "
                f"{token}"
            )
    for forbidden in ("Rename-Computer", "Set-ComputerName", "Win32_ComputerSystem"):
        for rel_path, text in (
            ("scripts/common.ps1", common),
            ("scripts/setup_office_hub.ps1", setup),
            ("scripts/hub_manager.ps1", manager),
        ):
            if forbidden in text:
                raise SystemExit(
                    "verify_runtime_contracts: Hub installer/manager must not mutate Windows hostname: "
                    f"{rel_path}: {forbidden}"
                )
    for token in (
        "immoapp_managed_hub_runtime_package_inventory",
        "managed_runtime_artifact_missing",
        "forbidden_runtime_package_content",
        "Get-GitState",
        "git_status_ok",
        "dirty_state_verified",
        "managed_runtime_package_path_mapping_failed",
        "managed_runtime_dirty_source_tree",
        "managed_runtime_source_commit_override",
        "source_tree_clean",
        "runtime_source_origin",
        "dirty_files_summary_count",
        "AllowExternalRuntimeSource",
        "AllowDirtyRuntimePackageProof",
        "AllowSourceCommitOverride",
        "AllowReplaceOutputRoot",
        "Assert-ManagedRuntimePackageOutputRoot",
        "managed_runtime_output_root_not_approved",
        "schema_version = 2",
        "Verify-ZipMatchesInventory",
        "stagingPackagePath",
        "Move-Item -LiteralPath $stagingPackagePath",
        "managed_runtime_external_artifact_requires_vendor_provenance",
        "VendorProvenanceJson",
        "managed_runtime_source_root_reparse_point",
        "managed_runtime_source_root_resolves_outside_declared_root",
    ):
        if token not in build_package:
            raise SystemExit(
                "verify_runtime_contracts: missing managed runtime package token: " f"{token}"
            )
    if "function Assert-ManagedRuntimeInventory" in detector:
        raise SystemExit(
            "verify_runtime_contracts: detector must not own package inventory policy."
        )
    if "function Assert-PackageInventoryReady" in register:
        raise SystemExit(
            "verify_runtime_contracts: register must not own package inventory policy."
        )
    for token in (
        "deprecated; delegating to register_managed_hub_runtime_provider.ps1",
        "AllowTestRuntime",
        "Production managed runtime provider requires -PackageInventoryJson",
        "register_managed_hub_runtime_provider.ps1",
    ):
        if token not in install_provider:
            raise SystemExit(
                "verify_runtime_contracts: missing managed runtime install token: " f"{token}"
            )
    for token in (
        "Production managed runtime provider registration requires -PackageInventoryJson",
        "proof_only_provider",
        "provider_write_status",
        "not_written_whatif",
        "internal_proof_status",
        "agency_install_status",
        "Invoke-ImmoAppManagedRuntimeVersionCheck",
        "Assert-ImmoAppCanonicalProviderConfigPathSafe",
        "provider_config_sha256_after_write",
        "Write-ImmoAppSafeJson",
    ):
        if token not in common:
            raise SystemExit(
                "verify_runtime_contracts: missing managed provider proof-only token: " f"{token}"
            )
    if "immoapp_managed_hub_runtime_provider_verification" not in verify_provider:
        raise SystemExit("verify_runtime_contracts: missing managed provider verifier.")
    prototype = _read("scripts/prepare_managed_hub_runtime_prototype.ps1")
    for token in (
        "immoapp_managed_hub_runtime_prototype_scaffold",
        "ConfirmManagedRuntimePrototype",
        "managed_runtime_artifact_missing",
        "provider_written = $false",
        "Get-ImmoAppCanonicalRuntimePaths",
        "agency_ready = $false",
        "missing_proof_tracks",
    ):
        if token not in prototype:
            raise SystemExit(
                "verify_runtime_contracts: missing managed runtime prototype scaffold token: "
                f"{token}"
            )
    create_provenance = _read("scripts/create_managed_runtime_vendor_provenance.ps1")
    verify_provenance = _read("scripts/verify_managed_runtime_vendor_provenance.ps1")
    common = _read("scripts/common.ps1")
    for token in (
        "immoapp_managed_runtime_vendor_provenance",
        "artifact_kind",
        "LicenseDistributionAllowed",
        "license_review_status",
        "approved_by",
        "approved_at_utc",
        "artifact_sha256",
        "extracted_inventory_sha256",
        "approved_by_immoapp",
        "runtime_license",
        "Get-ImmoAppSafeZipInventory",
        "Write-ImmoAppSafeJson",
    ):
        if token not in create_provenance:
            raise SystemExit(
                "verify_runtime_contracts: missing vendor provenance creator token: " f"{token}"
            )
    for token in (
        "Get-ImmoAppSafeZipInventory",
        "MaxFileCount",
        "MaxTotalBytes",
        "MaxSingleFileBytes",
        "MaxCompressionRatio",
        "managed_runtime_vendor_zip_unsafe_path",
        "managed_runtime_vendor_zip_duplicate_entry",
        "managed_runtime_vendor_zip_forbidden_content",
        "managed_runtime_vendor_zip_too_many_files",
        "managed_runtime_vendor_zip_total_bytes_exceeded",
        "managed_runtime_vendor_zip_file_too_large",
        "managed_runtime_vendor_zip_suspicious_compression_ratio",
        "license_distribution_allowed",
        "license_review_status",
        "managed_runtime_vendor_inventory_hash_mismatch",
    ):
        if token not in common:
            raise SystemExit(
                "verify_runtime_contracts: missing shared vendor ZIP/provenance guard: " f"{token}"
            )
    if "immoapp_managed_runtime_vendor_provenance_verification" not in verify_provenance:
        raise SystemExit("verify_runtime_contracts: missing vendor provenance verifier.")
    hub_m1_verifier = _read("scripts/verify_hub_beta_m1_evidence.ps1")
    if "Read-Evidence -Path $BackupRestoreProofJson" not in hub_m1_verifier:
        raise SystemExit("verify_runtime_contracts: backup/restore proof must use Read-Evidence.")
    for token in (
        "installed_exe_sha256",
        "forbidden_path_count",
        "installed_inventory_sha256",
        "installer_sha256_claimed_only",
        "installer_sha256_verified",
        "support_bundle_sha256",
        "remote_evidence",
    ):
        if token not in hub_m1_verifier:
            raise SystemExit(
                "verify_runtime_contracts: missing strict M1 evidence validation token: " f"{token}"
            )
    for token in (
        "backup_bundle_sha256",
        "storage_objects_hash_verified",
        "immoapp-restore-drill-",
        "ExpectedCandidateProofRunId",
        "ExpectedRuntimeDependencyMode",
        "ExpectedProviderConfigSha256",
        "ExpectedHubRuntimeProviderMode",
    ):
        if token not in common:
            raise SystemExit(
                "verify_runtime_contracts: missing strict shared backup validation token: "
                f"{token}"
            )
    installed_inventory = _read("scripts/collect_installed_app_inventory.ps1")
    for token in (
        "installer_sha256_verified",
        "installer_sha256_claimed_only",
        "verified_from_installer_file",
        "claimed_only_by_operator",
        "Get-InstallerHubPayloadFiles",
        "Test-InstallerHubPayloadPathAllowed",
        "deployment/managed-runtime/rootfs/ImmoAppRuntime.rootfs.tar",
        "deployment/managed-runtime/images/immoapp-runtime-images.tar",
        "deployment/managed-runtime/config/managed_wsl2_runtime_artifact_inventory.json",
        "deployment/managed-runtime/artifact/managed-wsl2-artifact",
        "scripts/hub_manager.ps1",
        "core/env_files.py",
        "core/models_audit.py",
    ):
        if token not in installed_inventory:
            raise SystemExit(
                "verify_runtime_contracts: installed inventory does not record installer hash proof mode: "
                f"{token}"
            )
    installed_payload_block = installed_inventory.split("function Get-InstallerHubPayloadFiles", 1)[
        1
    ].split("function Test-InstallerHubPayloadPathAllowed", 1)[0]
    for forbidden in (
        "scripts/build_managed_wsl2_runtime_artifact.ps1",
        "scripts/build_managed_wsl2_runtime_rootfs.ps1",
        "scripts/build_managed_wsl2_runtime_image_bundle.ps1",
        "scripts/stack.ps1",
        "scripts/backup_release_bundle.ps1",
        "scripts/verify_release_backup_integrity.py",
        "scripts/verify_release_bundle_manifest.py",
        "deployment/compose/compose.yml",
        "deployment/compose/compose.windows.yml",
        "deployment/compose/compose.app.yml",
        "deployment/proxy/Caddyfile",
        "deployment/managed-runtime/bin/start-managed-hub",
        "deployment/managed-runtime/compose/compose.yaml",
    ):
        if forbidden in installed_payload_block:
            raise SystemExit(
                "verify_runtime_contracts: installed inventory must not allow developer/build-machine runtime script: "
                f"{forbidden}"
            )
    candidate = _read("scripts/run_managed_runtime_candidate_proof.ps1")
    for token in (
        "immoapp_managed_runtime_candidate_proof",
        "missing_artifacts",
        "runtime_zip_candidate",
        "PromoteCandidateProvider",
        "ConfirmPromoteManagedRuntime",
        "provider_restored",
        "provider_restore_or_promotion",
        "setup_office_hub.ps1",
        "collect_hub_status_evidence.ps1",
        "verify_hub_network_boundary.ps1",
        "create_managed_runtime_vendor_provenance.ps1",
        "build_managed_hub_runtime_package.ps1",
        "Invoke-ImmoAppManagedRuntimeProviderRegistration",
        "detect_hub_runtime.ps1",
        "Write-ImmoAppSafeJson",
        "candidate_validation_status",
        "provider_promotion_status",
        "provider_active_after_proof",
        "provider_config_sha256_final",
        "provider_final_state",
        "candidate_proof_run_id",
        "Enter-ImmoAppProviderMutationLock",
        "Exit-ImmoAppProviderMutationLock",
        "provider_lock_status",
        "provider_lock_released",
        "managed_runtime_candidate_validated_not_promoted",
        "provider_promoted",
        "Assert-ImmoAppStrictBackupRestoreEvidence",
        "Assert-ImmoAppProviderSnapshotPathSafe",
        "ConfirmLicenseDistributionApproved",
        "vendor_provenance_required_for_promotion",
        "inline_explicit_approval",
        "vendor_provenance.inline.json",
        "finally {",
    ):
        if token not in candidate:
            raise SystemExit(
                "verify_runtime_contracts: missing managed runtime candidate proof token: "
                f"{token}"
            )
    if 'LicenseReviewStatus = "approved"' in candidate:
        raise SystemExit(
            "verify_runtime_contracts: candidate proof must not hardcode approved "
            "license review status."
        )
    register = _read("scripts/register_managed_hub_runtime_provider.ps1")
    common = _read("scripts/common.ps1")
    if "ProviderMutationLockToken" in candidate or "ProviderMutationLockToken" in register:
        raise SystemExit(
            "verify_runtime_contracts: provider writes must not use bearer-token lock inheritance."
        )
    if "function Invoke-ImmoAppManagedRuntimeProviderRegistration" not in common:
        raise SystemExit(
            "verify_runtime_contracts: provider registration must have one shared common.ps1 owner."
        )
    if "Invoke-ImmoAppManagedRuntimeProviderRegistration" not in register:
        raise SystemExit(
            "verify_runtime_contracts: direct provider registration must call the shared registration owner."
        )
    if (
        '$candidateValidationStatus -eq "GO" -and $providerPromoted -and '
        '$providerPromotionStatus -eq "GO" -and $providerActiveAfterProof -and '
        "$promotionFinalConfirmed"
    ) not in candidate:
        raise SystemExit(
            "verify_runtime_contracts: candidate agency GO must require promoted and "
            "active provider plus final detection confirmation."
        )
    if 'proof_result = if ($failed.Count -eq 0) { "GO" }' in candidate:
        raise SystemExit(
            "verify_runtime_contracts: candidate proof must not mark non-promoted "
            "validation as proof_result=GO."
        )
    hub_m1 = _read("scripts/verify_hub_beta_m1_evidence.ps1")
    if "Test-ImmoAppStrictBackupRestoreEvidence" not in hub_m1:
        raise SystemExit(
            "verify_runtime_contracts: Hub M1 verifier must reuse strict backup/restore evidence validation."
        )
    common = _read("scripts/common.ps1")
    for token in (
        "backup_restore_proof_result_missing",
        "backup_restore_artifact_proof_missing",
        "copied_artifact_sha256",
        "copied_artifact_reference",
        "remote_machine_name",
        "collected_at_utc",
    ):
        if token not in common:
            raise SystemExit(
                "verify_runtime_contracts: strict backup/restore evidence must require local or remote artifact proof: "
                f"{token}"
            )
    if '$proof -ne "GO" -and $status -ne "GO"' in common:
        raise SystemExit(
            "verify_runtime_contracts: legacy backup/restore status=GO must not satisfy release proof."
        )
    if "Legacy status=GO is informational only" not in common:
        raise SystemExit(
            "verify_runtime_contracts: strict backup/restore proof must document legacy status=GO as informational only."
        )
    if "copied_artifact_sha256 must match bundle_sha256/support_bundle_sha256" not in hub_m1:
        raise SystemExit(
            "verify_runtime_contracts: remote support copied_artifact_sha256 must match bundle hash."
        )
    for token in (
        "Test-StrictEvidenceIdentity",
        "source_commit_sha",
        "installer_sha256",
        "created_at_utc",
        "machine_name",
    ):
        if token not in hub_m1:
            raise SystemExit(
                "verify_runtime_contracts: Hub M1 verifier must require strict evidence identity: "
                f"{token}"
            )
    for token in (
        "StartHubForProof",
        "ValidateOnly",
        "internal_hub_status",
        "observed_existing_hub_status",
        "started_hub_status",
        "startup_attempted",
        "missing_restore_evidence",
    ):
        if token not in local_proof:
            raise SystemExit("verify_runtime_contracts: missing local Hub proof token: " f"{token}")


def _assert_managed_wsl2_runtime_policy_contract() -> None:
    policy = _read("scripts/managed_wsl2_runtime_policy.ps1")
    configure = _read("scripts/configure_managed_wsl2_runtime.ps1")
    detect = _read("scripts/detect_hub_runtime.ps1")
    register = _read("scripts/register_managed_hub_runtime_provider.ps1")
    common = _read("scripts/common.ps1")
    release = _read("scripts/run_beta_release_validation.ps1")
    profile = _read("core/runtime/hub_runtime_profile.py")
    if "& $python -B $script $Action --format $Format" not in common:
        raise SystemExit(
            "verify_runtime_contracts: installed Hub profile invocation must disable bytecode writes."
        )
    if "[System.IO.File]::Replace($temp, $full, $backup, $true)" not in common:
        raise SystemExit(
            "verify_runtime_contracts: Write-ImmoAppSafeJson must atomically replace existing evidence files."
        )
    if "catch [System.IO.IOException]" not in common or "last-writer-wins" not in common:
        raise SystemExit(
            "verify_runtime_contracts: Write-ImmoAppSafeJson must handle concurrent same-path evidence writes."
        )
    if (
        "[System.Threading.Mutex]::new" not in common
        or "safe_json_output_lock_timeout" not in common
    ):
        raise SystemExit(
            "verify_runtime_contracts: Write-ImmoAppSafeJson must serialize concurrent same-path writes."
        )
    if "Move-Item -LiteralPath $temp -Destination $full -Force" in common:
        raise SystemExit(
            "verify_runtime_contracts: Write-ImmoAppSafeJson must not use Move-Item -Force for final replacement."
        )
    if '@("localhost", "127.0.0.1", "web", "caddy", $hostname, $lanAddress)' not in common:
        raise SystemExit(
            "verify_runtime_contracts: Hub LAN env must include internal web/caddy hostnames plus machine/LAN hosts."
        )
    for token in (
        "MachineTotalMemoryGb",
        "MachineLogicalProcessors",
        "Normalize-InstalledMemoryClassGb",
        "normalized_memory_class_gb",
        "Select-HubMemoryProfile",
        "Select-HubCpuProfile",
        "Resolve-HubRuntimeProfileEnvelope",
        "explicit_runtime_profile_json",
        "default_persisted_config",
        "runtime_profile_invalid_json",
        "runtime_profile_invalid_selected_profile",
        "memory_derived_hub_profile",
        "cpu_derived_hub_profile",
        "Select-LowerProfile -A $selectedTier -B $profileFromRuntime",
        "hub_minimum_ram_gb",
        "machine_below_minimum_hub_ram",
        "cap_is_ceiling_not_reservation",
        "startup_spike_not_failure",
        "sustained_pressure_backoff_required",
        "global_wsl_config_scope",
        "planned_auto_memory_reclaim",
        "autoMemoryReclaim",
        "gradual",
        'agency_install_status = "NO_GO"',
    ):
        if token not in policy:
            raise SystemExit(
                "verify_runtime_contracts: managed_wsl2_runtime_policy.ps1 missing token: "
                f"{token}"
            )
    if "available_ram" in policy.lower() or "free_ram" in policy.lower():
        raise SystemExit("verify_runtime_contracts: WSL policy must not size from raw free RAM.")
    for token in (
        "ConfirmGlobalWslConfigChange",
        "AllowMergeExistingWslConfig",
        "ApplyShutdown",
        "Merge-WslConfig",
        "Get-WslConfigAmbiguity",
        "duplicate_wsl2_section_requires_manual_cleanup",
        "duplicate_wsl2_managed_key_requires_manual_cleanup",
        "$wsl2End",
        "$output.Insert($wsl2End, $line)",
        "existing_wslconfig_backup_path",
        "existing_wslconfig_preserved",
        "wsl_shutdown_required",
        "wsl_shutdown_performed",
        "final_wslconfig_verified",
        "existing_wslconfig_backup_verified",
        "temp_wslconfig_removed",
        "Test-WslConfigContainsDesiredSettings",
        "autoMemoryReclaim",
    ):
        if token not in configure:
            raise SystemExit(
                "verify_runtime_contracts: configure_managed_wsl2_runtime.ps1 missing token: "
                f"{token}"
            )
    if "Move-Item -LiteralPath $temp -Destination $safePath" not in configure:
        raise SystemExit(
            "verify_runtime_contracts: .wslconfig writer must use temp write then replace."
        )
    for path in (REPO_ROOT / "scripts").glob("*.ps1"):
        if path.name == "configure_managed_wsl2_runtime.ps1":
            continue
        text = path.read_text(encoding="utf-8")
        if (
            ".wslconfig" in text
            and "wslconfig_path" not in text
            and "wslconfig_present" not in text
        ):
            raise SystemExit(
                "verify_runtime_contracts: .wslconfig writes must be owned by "
                f"configure_managed_wsl2_runtime.ps1, found token in {path.name}"
            )
    for token in (
        "managed_wsl2_container_runtime_candidate",
        "managed_wsl2_container_runtime_artifact",
        "wsl_exe_present",
        "wsl_status_available",
        "wsl_version_available",
        "immoapp_wsl_policy_sha256",
        "managed_wsl2_runtime_artifact_missing",
        "managed_wsl2_runtime_start_not_proven",
        "runtime_start_evidence_sha256",
        "managed_runtime_command_path",
        "managed_backup_command_path",
        "front_door_health_status",
        "front_door_live_probe",
        "Test-ImmoAppLiveFrontDoorIdentity",
        "managed_wsl2_front_door_live_probe_failed",
        "managed_wsl2_runtime_start_ready",
        "managed_wsl2_runtime_internal_start_ready",
        'agencyStatus = "NO_GO"',
    ):
        if token not in detect:
            raise SystemExit(
                "verify_runtime_contracts: detect_hub_runtime.ps1 missing WSL candidate token: "
                f"{token}"
            )
    if "elseif ($wslPolicyPresent)" in detect:
        raise SystemExit(
            "verify_runtime_contracts: WSL policy file alone must not switch active runtime mode."
        )
    for token in (
        "RuntimeDependencyMode",
        "WslPolicyJsonPath",
        "WslConfigPlanJsonPath",
        "managed_wsl2_container_runtime_candidate",
        "managed_wsl2_container_runtime_artifact",
        "RuntimeArtifactInventoryJson",
        "Assert-ImmoAppManagedWsl2RuntimeArtifactInventoryReady",
        "managed_wsl2_runtime_artifact_missing",
        "managed_wsl2_runtime_artifact_registered_start_not_proven",
        "wsl_config_plan_json_missing",
        "wsl_config_plan_sha256",
        "existing_managed_runtime_provider_refuses_candidate_overwrite",
        'proof_result = "NO-GO"',
    ):
        if token not in register + common:
            raise SystemExit(
                "verify_runtime_contracts: provider registration missing WSL candidate token: "
                f"{token}"
            )
    manager = _read("scripts/hub_manager.ps1")
    setup = _read("scripts/setup_office_hub.ps1")
    status = _read("scripts/collect_hub_status_evidence.ps1")
    for token in (
        "install-runtime-candidate",
        "install-runtime-artifact",
        "remove-runtime-candidate",
        "ConfirmInstallRuntimeCandidate",
        "ConfirmInstallRuntimeArtifact",
        "immoapp_hub_manager_managed_wsl2_runtime_candidate_install",
        "immoapp_hub_manager_managed_wsl2_runtime_artifact_install",
        "immoapp_hub_manager_managed_wsl2_runtime_candidate_remove",
        "candidate_registration_status",
        "runtime_artifact_status",
        "existing_provider_present",
        "existing_provider_mode",
        "existing_provider_preserved",
        "candidate_overwrite_refused",
        "existing_managed_runtime_provider_refuses_candidate_overwrite",
        "registration_only",
        "managed_wsl2_runtime_artifact_missing|Managed WSL2 runtime candidate provider is registered",
        "managed_wsl2_runtime_policy.ps1",
        "configure_managed_wsl2_runtime.ps1",
        "Install-HubManagerPackagedManagedWsl2Payload",
        "Test-HubManagerManagedWsl2DistroPresent",
        "Import-HubManagerManagedWsl2RuntimeDistro",
        "ConfirmImportManagedWslRuntime",
        "runtime_import_status",
        "runtime_import_path",
        "Update-HubManagerExistingManagedWsl2RuntimePayload",
        "UpdateExistingRuntimePayload",
        "ConfirmUpdateExistingRuntimePayload",
        "packaged_payload_status",
        "runtime_payload_update_status",
        "packaged_managed_runtime_payload_missing",
        "collect_managed_wsl2_runtime_start_evidence.ps1",
        "managed_wsl2_container_runtime_artifact",
        "Invoke-ManagedWsl2RuntimeArtifactAction",
        "LAN reachability is collected separately",
        '@("-HubBaseUrl", $effectiveHubBaseUrl)',
        "managed_runtime_provider_invalid",
        "register_managed_hub_runtime_provider.ps1",
        "uninstall_managed_hub_runtime_provider.ps1",
    ):
        if token not in manager:
            raise SystemExit(
                "verify_runtime_contracts: Hub Manager missing WSL candidate install token: "
                f"{token}"
            )
    for token in (
        "ConfigureWslRuntimeCandidate",
        "ConfirmInstallRuntimeCandidate",
        "wsl_runtime_candidate_requested",
        "wsl_runtime_candidate_install",
        "candidate_registration_status",
        "runtime_artifact_status",
        "runtime_start_status",
        "install-runtime-candidate",
    ):
        if token not in setup:
            raise SystemExit(
                "verify_runtime_contracts: setup_office_hub.ps1 missing WSL candidate setup token: "
                f"{token}"
            )
    support_bundle = _read("app/services/support_bundle.py")
    for token in (
        "managed_wsl2_runtime_candidate_install.json",
        "managed_wsl2_runtime_candidate_remove.json",
        "managed_wsl2_runtime_candidate_install",
        "managed_wsl2_runtime_candidate_remove",
        "managed_wsl2_runtime_artifact_inventory",
        "managed_wsl2_runtime_artifact_install.json",
        "managed_wsl2_runtime_bootstrap_evidence.json",
        "managed_wsl2_runtime_start_evidence.json",
        "managed_wsl2_runtime_status_evidence.json",
        "managed_wsl2_runtime_image_bundle_inventory",
        "managed_wsl2_runtime_image_bundle_inventory_summary",
        "runtime_start_status",
        "runtime_start_reason_code",
        "front_door_live_probe",
        "managed_runtime_log_retention.json",
        "managed_runtime_log_retention",
    ):
        if token not in support_bundle:
            raise SystemExit(
                "verify_runtime_contracts: support bundle missing WSL candidate evidence token: "
                f"{token}"
            )
    for token in (
        "Invoke-ImmoAppManagedRuntimeLogRetention",
        "managed-runtime",
        "536870912",
        "deleted_files",
        "failed_delete_count",
        "failed_delete_files",
        "size_cap_satisfied",
        "age_retention_satisfied",
        "managed_runtime_log_retention_delete_incomplete",
        'agency_install_status = "NO_GO"',
    ):
        if token not in common:
            raise SystemExit(
                "verify_runtime_contracts: managed runtime log retention helper missing token: "
                f"{token}"
            )
    for token in (
        "cleanup-runtime-logs",
        "Invoke-ImmoAppManagedRuntimeLogRetention",
        "RetentionDays",
        "MaxTotalBytes",
    ):
        if token not in manager:
            raise SystemExit(
                "verify_runtime_contracts: Hub Manager missing managed runtime log cleanup token: "
                f"{token}"
            )
    if "managed_runtime_log_retention" not in status:
        raise SystemExit(
            "verify_runtime_contracts: Hub status evidence must include managed runtime log retention summary."
        )
    artifact_builder = _read("scripts/build_managed_wsl2_runtime_artifact.ps1")
    for token in (
        "immoapp_managed_wsl2_runtime_artifact_inventory",
        "Get-ImmoAppStrictRuntimeTreeInventory",
        "Get-ImmoAppManagedWsl2RuntimeArtifactRequiredEntries",
        "runtime_start_status",
        "start_command_path",
        "status_command_path",
        "health_command_path",
        "logs_command_path",
        "stop_command_path",
        "restart_command_path",
        "bootstrap_command_path",
        "image_bundle_archive_path",
        "image_bundle_inventory_path",
        "compose_payload_path",
        "compose_pull_policy",
        "ImmoAppRuntime",
        "immoapp-runtime-identity",
        "expected_wsl_distribution_name",
        "System32\\wsl.exe",
        "IMMOAPP_TEST_WSL_EXE",
        "IMMOAPP_ALLOW_TEST_PROGRAMDATA_ROOT",
        "[string[]]$linuxArgs = @(",
        '"identity" { "/opt/immoapp/runtime/bin/immoapp-runtime-identity"; "--json" }',
        '"start" { "/opt/immoapp/runtime/bin/start-managed-hub" }',
        'if ($Action -eq "start")',
        'if ($Action -eq "restart" -and $exitCode -eq 0)',
        "Get-ImmoAppManagedRuntimeEnvArgs",
        '"IMMOAPP_CADDY_BIND_HOST"',
        '"IMMOAPP_HUB_FRONT_DOOR_URL"',
        '@("env") + $runtimeEnvArgs + $linuxArgs',
        '$wslArguments = @("-d", $distroName, "--cd", "/opt/immoapp/runtime", "--") + $linuxCommandArgs',
        "Start-Process",
        "-RedirectStandardOutput $stdoutPath",
        "-RedirectStandardError $stderrPath",
        "IMMOAPP_MANAGED_WSL2_ACTION_TIMEOUT_SECONDS",
        ".WaitForExit([Math]::Max(1, $actionTimeoutSeconds) * 1000)",
        "managed_wsl2_runtime_bridge_timeout",
        "NO-GO",
        "agency_install_status",
        "NO_GO",
        "Write-ImmoAppSafeJson",
    ):
        if token not in artifact_builder:
            raise SystemExit(
                "verify_runtime_contracts: managed WSL2 artifact builder missing token: " f"{token}"
            )
    if '"/opt/immoapp/runtime/bin/immoapp-runtime-identity --json"' in artifact_builder:
        raise SystemExit(
            "verify_runtime_contracts: managed WSL2 bridge must pass --json as a separate Linux argument"
        )
    if '"POSTGRES_PASSWORD"' in artifact_builder or '"OPENBAO_TOKEN"' in artifact_builder:
        raise SystemExit(
            "verify_runtime_contracts: managed WSL2 bridge must not pass secret env values"
        )
    if (
        "Start-Process" not in artifact_builder
        or "-RedirectStandardOutput $stdoutPath" not in artifact_builder
        or "-RedirectStandardError $stderrPath" not in artifact_builder
        or "[System.IO.File]::ReadAllText($stderrPath)" not in artifact_builder
    ):
        raise SystemExit(
            "verify_runtime_contracts: managed WSL2 bridge must keep stderr separate from JSON stdout"
        )
    if "& $wslPath -d $distroName --cd /opt/immoapp/runtime -- @linuxArgs 2>&1" in artifact_builder:
        raise SystemExit(
            "verify_runtime_contracts: managed WSL2 bridge must not merge stderr into stdout"
        )
    if "-Wait `" in artifact_builder:
        raise SystemExit(
            "verify_runtime_contracts: managed WSL2 bridge must not use unbounded Start-Process -Wait"
        )
    rootfs_builder = _read("scripts/build_managed_wsl2_runtime_rootfs.ps1")
    managed_runtime_templates = "\n".join(
        _read(path)
        for path in (
            "deployment/managed-runtime/bin/immoapp-runtime-identity",
            "deployment/managed-runtime/bin/managed-hub-common",
            "deployment/managed-runtime/bin/start-managed-hub",
            "deployment/managed-runtime/bin/status-managed-hub",
            "deployment/managed-runtime/bin/health-managed-hub",
            "deployment/managed-runtime/bin/logs-managed-hub",
            "deployment/managed-runtime/bin/backup-managed-hub",
            "deployment/managed-runtime/bin/stop-managed-hub",
            "deployment/managed-runtime/bin/restart-managed-hub",
            "deployment/managed-runtime/bin/keepalive-managed-hub",
            "deployment/managed-runtime/compose/compose.yaml",
        )
    )
    managed_rootfs_contract = rootfs_builder + "\n" + managed_runtime_templates
    official_rootfs_builder = _read("scripts/build_official_managed_wsl2_runtime_rootfs.ps1")
    for token in (
        "immoapp_managed_wsl2_runtime_rootfs_inventory",
        "BaseRootfsTarPath is required",
        "no distro rootfs is downloaded or inferred",
        "deployment\\managed-runtime",
        '$buildMethod = "direct_tar_overlay"',
        'tarfile.open(base_path, "r:*")',
        'tarfile.open(output_path, "r:")',
        'key.startswith("GNU.sparse")',
        "member.sparse = None",
        '".pending-"',
        "Move-Item -LiteralPath $pendingOutputFull",
        "build_mutated_wsl = $false",
        "build_invoked_docker = $false",
        "build_invoked_package_manager = $false",
        "archive_validation_status = $archiveValidationStatus",
        "sparse_files_expanded = $sparseFilesExpanded",
        "AllowTestOnlyPath",
        "managed_wsl2_runtime_rootfs_dirty_source",
        "managed_wsl2_runtime_rootfs_source_commit_mismatch",
        "opt/immoapp/runtime/bin/immoapp-runtime-identity",
        "opt/immoapp/runtime/bin/start-managed-hub",
        "opt/immoapp/runtime/bin/status-managed-hub",
        "opt/immoapp/runtime/bin/health-managed-hub",
        "opt/immoapp/runtime/bin/logs-managed-hub",
        "opt/immoapp/runtime/bin/stop-managed-hub",
        "opt/immoapp/runtime/bin/restart-managed-hub",
        "opt/immoapp/runtime/bin/keepalive-managed-hub",
        "opt/immoapp/runtime/compose/compose.yaml",
        'runtime_start_status = "NO-GO"',
        'agency_install_status = "NO_GO"',
        'public_beta_status = "NO_GO"',
        "Write-ImmoAppSafeJson",
    ):
        if token not in rootfs_builder:
            raise SystemExit(
                "verify_runtime_contracts: managed WSL2 rootfs builder missing token: " f"{token}"
            )
    for forbidden in (
        "ImmoAppRuntimeOverlayBuild",
        "wsl.exe",
        "--import",
        "--export",
        "--unregister",
    ):
        if forbidden.lower() in rootfs_builder.lower():
            raise SystemExit(
                "verify_runtime_contracts: managed WSL2 rootfs builder must not mutate WSL: "
                f"{forbidden}"
            )
    for token in (
        "immoapp_managed_wsl2_runtime_identity",
        "docker_desktop_rejected",
        "managed_wsl2_runtime_compose_file_missing",
        "managed_wsl2_docker_daemon_start_timeout",
        "systemctl start docker --no-block",
        "managed_runtime_image_archive_missing",
        "managed_runtime_image_archive_wsl_path_missing",
        "managed_runtime_image_archive_hash_mismatch",
        "hub_backend_services_unhealthy_or_timeout",
        "docker_start_attempted",
        "docker_start_timeout_seconds",
        "wait_for_service_readiness",
        "service_readiness_timeout_seconds",
        "image_archive_wsl_path",
        "caddy_bind_mode",
        "run_identity_with_timeout",
        "identity_timeout_seconds",
        "managed_wsl2_runtime_identity_timeout",
        "managed_wsl2_runtime_stop_failed",
        "managed_wsl2_runtime_logs_failed",
        "front_door_probe_url",
        '"$front_door_probe_url/api/v1/health/"',
        '"$front_door_probe_url/api/v1/hub/front-door/identity/"',
        "docker load -i",
        "pull_policy: never",
        "ensure_runtime_secrets",
        "openbao_token_file",
        "openbao_unseal_file",
        "openbao_approle_file",
        'chmod 755 "$runtime_secrets_dir"',
        'chmod 600 "$openbao_token_file"',
        'chmod 600 "$openbao_unseal_file"',
        'chmod 644 "$openbao_approle_file"',
        "loaded_image_archive_marker",
        'marker_sha" != "$image_archive_sha256"',
        "BAO_TOKEN_FILE: /run/immoapp-secrets/openbao.token",
        "BAO_APPROLE_FILE: /run/immoapp-secrets/openbao-approle.json",
        "openbao-init:",
        "server.secret_store.openbao_runtime_init",
        "server -config=/openbao/config/openbao.hcl",
        'agency_install_status = "NO_GO"',
    ):
        if token not in managed_rootfs_contract:
            raise SystemExit(
                "verify_runtime_contracts: managed WSL2 runtime template missing token: " f"{token}"
            )
    for forbidden in ("docker pull", "apt install", "apt-get install", "winget", "choco"):
        if forbidden in managed_runtime_templates.lower():
            raise SystemExit(
                "verify_runtime_contracts: managed WSL2 runtime start template contains "
                f"forbidden token: {forbidden}"
            )
    identity_template = _read("deployment/managed-runtime/bin/immoapp-runtime-identity")
    if "docker info" in identity_template:
        raise SystemExit(
            "verify_runtime_contracts: managed WSL2 identity must not block bootstrap on docker info"
        )
    if "not_checked_pre_start" not in identity_template:
        raise SystemExit(
            "verify_runtime_contracts: managed WSL2 identity must mark daemon proof as pre-start"
        )
    if "stack.ps1" in managed_runtime_templates or "docker.exe" in managed_runtime_templates:
        raise SystemExit(
            "verify_runtime_contracts: managed WSL2 runtime template contains host fallback token."
        )
    if "service docker start >/dev/null" in managed_runtime_templates:
        raise SystemExit(
            "verify_runtime_contracts: managed WSL2 runtime has unbounded service docker start."
        )
    compose_template = _read("deployment/managed-runtime/compose/compose.yaml")

    def _compose_service_body(service: str) -> str:
        service_block = re.search(
            rf"^  {re.escape(service)}:\n(?P<body>.*?)(?=^  [A-Za-z0-9_-]+:|\Z)",
            compose_template,
            re.MULTILINE | re.DOTALL,
        )
        return service_block.group("body") if service_block else ""

    if 'BAO_TOKEN: ""' not in compose_template:
        raise SystemExit(
            "verify_runtime_contracts: managed WSL2 compose must explicitly clear BAO_TOKEN for seed."
        )
    for line in compose_template.splitlines():
        if "BAO_TOKEN:" in line and line.strip() != 'BAO_TOKEN: ""':
            raise SystemExit(
                "verify_runtime_contracts: managed WSL2 compose must not put a plaintext BAO_TOKEN in env."
            )
    if "BAO_TOKEN_FILE: /run/immoapp-secrets/openbao.token" not in compose_template:
        raise SystemExit(
            "verify_runtime_contracts: managed WSL2 seed must use the persisted OpenBao admin token file."
        )
    if compose_template.count("BAO_APPROLE_FILE: /run/immoapp-secrets/openbao-approle.json") < 7:
        raise SystemExit(
            "verify_runtime_contracts: managed WSL2 app services must use AppRole auth."
        )
    if (
        "-dev-root-token-id" in compose_template
        or "/run/immoapp-secrets/bao_token" in compose_template
    ):
        raise SystemExit(
            "verify_runtime_contracts: managed WSL2 compose must not use dev-mode OpenBao tokens."
        )
    if (
        "openbao-init:" not in compose_template
        or "server.secret_store.openbao_runtime_init" not in compose_template
    ):
        raise SystemExit(
            "verify_runtime_contracts: managed WSL2 compose must initialize persistent OpenBao before seeding."
        )
    if (
        "openbao-seed:" not in compose_template
        or "server.secret_store.openbao_runtime_seed" not in compose_template
    ):
        raise SystemExit(
            "verify_runtime_contracts: managed WSL2 compose must seed OpenBao before app services."
        )
    if (
        "db-app-role-init:" not in compose_template
        or "ALTER ROLE %I WITH PASSWORD %L NOSUPERUSER" not in compose_template
    ):
        raise SystemExit(
            "verify_runtime_contracts: managed WSL2 compose must initialize the app DB role before app start."
        )
    if (
        "db-schema-prepare:" not in compose_template
        or "python server/manage.py immoapp_db_prepare" not in compose_template
    ):
        raise SystemExit(
            "verify_runtime_contracts: managed WSL2 compose must prepare the DB schema before app start."
        )
    if "openbao-seed:\n        condition: service_completed_successfully" not in compose_template:
        raise SystemExit(
            "verify_runtime_contracts: managed WSL2 web service must wait for OpenBao seed completion."
        )
    if "openbao-init:\n        condition: service_completed_successfully" not in compose_template:
        raise SystemExit(
            "verify_runtime_contracts: managed WSL2 seed must wait for OpenBao init completion."
        )
    if (
        "db-schema-prepare:\n        condition: service_completed_successfully"
        not in compose_template
    ):
        raise SystemExit(
            "verify_runtime_contracts: managed WSL2 web service must wait for DB schema preparation."
        )
    if compose_template.count("IMMOAPP_SECRETS_PATH: secret/data/immoapp") < 7:
        raise SystemExit(
            "verify_runtime_contracts: managed WSL2 seed and app services must share the same OpenBao path."
        )
    if compose_template.count("IMMOAPP_SECRETS_ALLOWLIST:") < 6:
        raise SystemExit(
            "verify_runtime_contracts: managed WSL2 app services must load required runtime secret prefixes."
        )
    for secret_prefix in ("POSTGRES_", "RABBITMQ_", "MINIO_"):
        if secret_prefix not in compose_template:
            raise SystemExit(
                "verify_runtime_contracts: managed WSL2 secret allowlist is missing "
                f"{secret_prefix}."
            )
    for required_endpoint in (
        "POSTGRES_HOST: db",
        "VALKEY_URL: redis://valkey:6379/1",
        "CELERY_BROKER_URL: amqp://${RABBITMQ_USER:-immoapp}:${RABBITMQ_PASSWORD:-change-before-start}@rabbitmq:5672//",
        "STORAGE_ENDPOINT_URL: http://minio:9000",
        "STORAGE_CLAMD_HOST: clamav",
    ):
        if compose_template.count(required_endpoint) < 6:
            raise SystemExit(
                "verify_runtime_contracts: managed WSL2 app services must use internal endpoint "
                f"{required_endpoint}."
            )
    if (
        compose_template.count(
            "DJANGO_ALLOWED_HOSTS: ${DJANGO_ALLOWED_HOSTS:-127.0.0.1,localhost,web,caddy}"
        )
        < 7
    ):
        raise SystemExit(
            "verify_runtime_contracts: managed WSL2 app services must declare local front-door allowed hosts."
        )
    caddyfile = _read("deployment/managed-runtime/proxy/Caddyfile")
    for token in (
        "header_up Host web",
        "header_up X-Forwarded-Host {host}",
        "header_up X-Forwarded-Proto {scheme}",
    ):
        if token not in caddyfile:
            raise SystemExit(
                "verify_runtime_contracts: managed WSL2 Caddy front door must normalize upstream Host "
                f"and preserve forwarded host; missing {token!r}."
            )
    for service in (
        "db",
        "rabbitmq",
        "valkey",
        "openbao",
        "minio",
        "clamav",
        "web",
        "worker",
        "worker-import",
        "worker-rebuild",
        "worker-match",
        "beat",
        "caddy",
    ):
        service_block = _compose_service_body(service)
        if not service_block or "restart: unless-stopped" not in service_block:
            raise SystemExit(
                "verify_runtime_contracts: managed WSL2 persistent service "
                f"{service} must restart unless stopped."
            )
    for service in (
        "rabbitmq-init",
        "db-app-role-init",
        "openbao-seed",
        "db-schema-prepare",
        "minio-init",
        "app-data-init",
    ):
        service_block = _compose_service_body(service)
        if not service_block or 'restart: "no"' not in service_block:
            raise SystemExit(
                "verify_runtime_contracts: managed WSL2 one-shot service "
                f"{service} must not restart."
            )
    managed_common = _read("deployment/managed-runtime/bin/managed-hub-common")
    start_template = _read("deployment/managed-runtime/bin/start-managed-hub")
    status_template = _read("deployment/managed-runtime/bin/status-managed-hub")
    if "run_compose_bootstrap_gates()" not in managed_common:
        raise SystemExit(
            "verify_runtime_contracts: managed WSL2 start must rerun one-shot bootstrap gates after Docker restarts."
        )
    if 'cd "$runtime_root"' not in managed_common or managed_common.index(
        'cd "$runtime_root"'
    ) > managed_common.index('"$@" >"$out" 2>&1'):
        raise SystemExit(
            "verify_runtime_contracts: each bounded managed command must re-anchor to the current runtime root."
        )
    if "keepalive_pid_file" not in managed_common or "stop_keepalive()" not in managed_common:
        raise SystemExit(
            "verify_runtime_contracts: managed WSL2 runtime must own a keepalive process so WSL does not stop after start returns."
        )
    if "up -d rabbitmq db valkey openbao minio clamav" not in managed_common:
        raise SystemExit(
            "verify_runtime_contracts: managed WSL2 bootstrap must start durable dependencies before one-shot gates."
        )
    for service in ("openbao-init", "openbao-seed", "db-app-role-init", "db-schema-prepare"):
        if service not in managed_common:
            raise SystemExit(
                "verify_runtime_contracts: managed WSL2 bootstrap gate missing service "
                f"{service}."
            )
    if "--force-recreate --no-deps" not in managed_common:
        raise SystemExit(
            "verify_runtime_contracts: managed WSL2 bootstrap gates must force-recreate one-shot jobs without deleting volumes."
        )
    if (
        "check_compose_services_fast()" not in managed_common
        or "ps --format json" not in managed_common
        or "json_services_fast()" not in managed_common
        or "json_failures_fast()" not in managed_common
    ):
        raise SystemExit(
            "verify_runtime_contracts: managed WSL2 must provide a fast aggregate service health check."
        )
    readiness_block = managed_common.split("wait_for_service_readiness() {", 1)[1].split(
        "wait_for_front_door_readiness() {", 1
    )[0]
    if "check_compose_services_fast" not in readiness_block:
        raise SystemExit(
            "verify_runtime_contracts: managed WSL2 start readiness must use one aggregate Compose snapshot."
        )
    if (
        "wait_for_front_door_readiness" not in start_template
        or 'services_json="$(json_services_fast)"' not in start_template
        or 'failures_json="$(json_failures_fast)"' not in start_template
    ):
        raise SystemExit(
            "verify_runtime_contracts: managed WSL2 start must wait boundedly for the front door and emit aggregate service evidence."
        )
    if (
        "json_services_fast" not in status_template
        or "json_failures_fast" not in status_template
        or "check_compose_services_fast" not in status_template
    ):
        raise SystemExit(
            "verify_runtime_contracts: managed WSL2 status must use fast aggregate Compose status."
        )
    if "down -v" in managed_common or "--renew-anon-volumes" in managed_common:
        raise SystemExit(
            "verify_runtime_contracts: managed WSL2 bootstrap must not delete runtime volumes."
        )
    if (
        "run_compose_bootstrap_gates" not in start_template
        or "managed_wsl2_runtime_bootstrap_gates_failed" not in start_template
        or start_template.index("run_compose_bootstrap_gates")
        > start_template.index("run_compose_up")
    ):
        raise SystemExit(
            "verify_runtime_contracts: managed WSL2 start must run bootstrap gates before full compose up."
        )
    stop_template = _read("deployment/managed-runtime/bin/stop-managed-hub")
    if "down || true" in stop_template or "managed_wsl2_runtime_stop_failed" not in stop_template:
        raise SystemExit(
            "verify_runtime_contracts: managed WSL2 stop must not swallow compose down failure."
        )
    if "stop_keepalive || true" not in stop_template:
        raise SystemExit(
            "verify_runtime_contracts: managed WSL2 stop must terminate the keepalive process."
        )
    keepalive_template = _read("deployment/managed-runtime/bin/keepalive-managed-hub")
    if (
        "managed-hub-keepalive.pid" not in keepalive_template
        or "IMMOAPP_MANAGED_KEEPALIVE_INTERVAL_SECONDS" not in keepalive_template
    ):
        raise SystemExit(
            "verify_runtime_contracts: managed WSL2 keepalive template is missing bounded state."
        )
    health_template = _read("deployment/managed-runtime/bin/health-managed-hub")
    if (
        "verify_image_bundle" in health_template
        or "ensure_images_present status" in health_template
    ):
        raise SystemExit(
            "verify_runtime_contracts: managed WSL2 health must not hash/load the offline image bundle."
        )
    for token in (
        "probe_front_door",
        "check_compose_services_fast",
        "managed_wsl2_runtime_health_go",
    ):
        if token not in health_template:
            raise SystemExit(
                "verify_runtime_contracts: managed WSL2 health is missing fast liveness token: "
                f"{token}"
            )
    logs_template = _read("deployment/managed-runtime/bin/logs-managed-hub")
    if (
        'logs_status="NO-GO"' not in logs_template
        or "managed_wsl2_runtime_logs_failed" not in logs_template
        or 'proof_result="NO-GO"' not in logs_template
    ):
        raise SystemExit(
            "verify_runtime_contracts: managed WSL2 logs must report failed collection as NO-GO."
        )
    backup_template = _read("deployment/managed-runtime/bin/backup-managed-hub")
    for token in (
        "managed_wsl2_backup_go",
        "managed_wsl2_backup_root_not_approved",
        "managed_wsl2_backup_runtime_not_ready",
        "managed_wsl2_backup_database_dump_failed",
        "managed_wsl2_backup_object_mirror_failed",
        "managed_wsl2_backup_archive_failed",
        "/mnt/c/ProgramData/ImmoApp/backups/managed-runtime",
        "pg_dump",
        "mc mirror --overwrite",
        "backup_bundle_sha256",
    ):
        if token not in backup_template:
            raise SystemExit(
                "verify_runtime_contracts: managed WSL2 backup template missing token: " f"{token}"
            )
    for token in (
        "immoapp_managed_wsl2_official_rootfs_build",
        "cloud-images.ubuntu.com/minimal/releases/noble/release/",
        "ubuntu-24.04-minimal-cloudimg-amd64-root.tar.xz",
        "ExpectedBaseRootfsSha256",
        "ImmoAppRuntimeBuild",
        "ConfirmBuild",
        "ConfirmReplaceBuildDistro",
        "KeepBuildDistro",
        "RuntimeVersion",
        "-f install -y --fix-missing",
        "deployment\\managed-runtime",
        "official_rootfs_runtime_template_missing",
        "__IMMOAPP_RUNTIME_VERSION__",
        "opt/immoapp/runtime/bin/stop-managed-hub",
        "opt/immoapp/runtime/bin/restart-managed-hub",
        "opt/immoapp/runtime/bin/backup-managed-hub",
        "opt/immoapp/runtime/compose/compose.yaml",
        "requiredRuntimeEntries",
        '"max-size": "10m"',
        '"max-file": "5"',
        "immoapp-no-network-online.conf",
        "systemctl mask systemd-networkd-wait-online.service",
        "systemctl start docker --no-block",
        "build_distro_cleanup_status",
        "build_distro_cleanup_attempted",
        "build_distro_present_after_cleanup",
        "official_rootfs_build_distro_cleanup_failed_after_export",
        "managed_wsl2_runtime_rootfs_inventory.json",
        "immoapp_managed_wsl2_runtime_rootfs_inventory",
        "rootfs_inventory_sha256",
        '@("--unregister", $BuildDistroName)',
        "runtime_start_status = $runtimeStartStatus",
        "agency_install_status = $agencyInstallStatus",
        "public_beta_status = $publicBetaStatus",
        "import_managed_wsl2_runtime_distro.ps1",
        "-PlanOnly",
        "-ConfirmReplaceExistingDistro",
    ):
        if token not in official_rootfs_builder:
            raise SystemExit(
                "verify_runtime_contracts: official managed WSL2 rootfs builder missing token: "
                f"{token}"
            )
    for forbidden in (
        "managed_wsl2_runtime_compose_payload_not_wired",
        "managed_wsl2_runtime_logs_not_wired",
    ):
        if forbidden in official_rootfs_builder:
            raise SystemExit(
                "verify_runtime_contracts: official managed WSL2 rootfs builder still writes "
                f"stub runtime payload token: {forbidden}"
            )
    import_distro = _read("scripts/import_managed_wsl2_runtime_distro.ps1")
    for token in (
        "immoapp_managed_wsl2_runtime_import_plan",
        "ConfirmImportManagedWslRuntime",
        "ConfirmReplaceExistingDistro",
        "UpdateExistingRuntimePayload",
        "ConfirmUpdateExistingRuntimePayload",
        "RootfsTarPath is required",
        "Get-ImmoAppManagedWsl2RootfsRequiredEntries",
        "opt/immoapp/runtime/bin/backup-managed-hub",
        "./opt/immoapp/runtime",
        "immoapp-runtime-update-tar.err",
        "successSentinelPresent",
        "managed_wsl2_runtime_payload_update_go",
        "managed_wsl2_runtime_payload_update_missing_success_sentinel",
        "scriptTemplate = @'",
        "__ROOTFS_QUOTED__",
        'staging="/opt/immoapp/runtime.update.$$"',
        'mkdir -p "$staging"',
        "preserve_runtime_state",
        "for item in secrets backups logs",
        'cp -a "$old_runtime/$item" "$new_runtime/$item"',
        'preserve_runtime_state "$previous" /opt/immoapp/runtime',
        'status="$?"',
        "managed_wsl2_rootfs_required_command_missing",
        "managed_wsl2_runtime_payload_updated",
        "managed_wsl2_runtime_distro_missing_for_payload_update",
        "wsl.exe --import",
        "--import",
        "--unregister",
        "plan_only",
        "import_attempted",
        "payload_update_attempted",
        "payload_update_status",
        "mutation_performed",
        'runtime_start_status = "NO-GO"',
        'agency_install_status = "NO_GO"',
        'public_beta_status = "NO_GO"',
        "managed_wsl2_runtime_distro_exists_replace_not_confirmed",
        "Write-ImmoAppSafeJson",
    ):
        if token not in import_distro:
            raise SystemExit(
                "verify_runtime_contracts: managed WSL2 import scaffold missing token: " f"{token}"
            )
    start_evidence = _read("scripts/collect_managed_wsl2_runtime_start_evidence.ps1")
    for token in (
        "immoapp_managed_wsl2_runtime_start_evidence",
        "start_run_id",
        "bootstrap_managed_wsl2_runtime.ps1",
        "expected_distro_name",
        "actual_distro_name",
        "runtime_identity_status",
        "container_engine_status",
        "compose_cli_status",
        "compose_status",
        "docker_daemon_status",
        "docker_info_status",
        "image_archive_status",
        "image_inventory_status",
        "image_presence_status",
        "compose_payload_status",
        "compose_pull_policy_status",
        "compose_up_status",
        "runtime_compose_service_status",
        "image_archive_path",
        "image_archive_host_path",
        "image_archive_wsl_path",
        "image_bundle_inventory_path",
        "image_bundle_inventory_host_path",
        "image_bundle_inventory_wsl_path",
        "runtime_bridge_timeout_seconds",
        "runtime_bridge_timed_out",
        "$identityBridgeTimeoutSeconds = 120",
        "managed_wsl2_runtime_bridge_timeout",
        "docker_start_attempted",
        "service_readiness_timeout_seconds",
        "caddy_lan_bind_status",
        '$frontDoorProofRequired = ($Action -in @("start", "restart", "status", "health"))',
        "if (-not $frontDoorProofRequired)",
        "$explicitFrontDoorUrl = -not [string]::IsNullOrWhiteSpace($HubBaseUrl)",
        '"http://127.0.0.1:$(Get-ImmoAppHubPort)"',
        "if ($explicitFrontDoorUrl -and (-not $frontDoorIsLoopback)",
        "explicit_front_door_url_requested",
        '$serviceProofRequired = ($Action -in @("start", "restart", "status", "health", "backup"))',
        '$serviceOk = ((-not $serviceProofRequired) -or $serviceStatus -eq "GO")',
        "service_proof_required",
        "Ensure-ImmoAppHubWslPortProxy",
        "wsl_portproxy_status",
        "wsl_portproxy_verified",
        "managed_wsl2_portproxy_not_verified",
        'wsl_portproxy = if ($networkBridgeOk) { "GO" } else { "NO-GO" }',
        '$caddyBindMode -eq "local"',
        "Get-ImmoAppHubBaseUrl -PreferLan",
        '$Action -in @("start", "restart", "status")',
        "bootstrap_evidence_sha256",
        "pre_start_front_door_reachable",
        "pre_start_backend_direct_reachable",
        "managed_wsl2_pre_start_port_contamination",
        "managed_wsl2_runtime_service_status_not_go",
        "provider_config_sha256",
        "runtime_artifact_inventory_sha256",
        "managed_runtime_command_sha256",
        "X-ImmoApp-Front-Door",
        "immoapp_hub_front_door_identity",
        "proof_result",
        "NO-GO",
    ):
        if token not in start_evidence:
            raise SystemExit(
                "verify_runtime_contracts: managed WSL2 start evidence collector missing token: "
                f"{token}"
            )
    for token in (
        "Ensure-ImmoAppHubWslPortProxy",
        "Get-ImmoAppManagedWslRuntimeIp",
        "Get-ImmoAppHubWslPortProxyEvidence",
        "netsh interface portproxy add v4tov4",
        "portproxy_rule_needs_admin",
        "managed_wsl2_ip_unavailable",
    ):
        if token not in common:
            raise SystemExit(
                "verify_runtime_contracts: common.ps1 missing managed WSL2 portproxy token: "
                f"{token}"
            )
    image_bundle_builder = _read("scripts/build_managed_wsl2_runtime_image_bundle.ps1")
    for token in (
        "immoapp_managed_wsl2_runtime_image_bundle_inventory",
        "docker save",
        "docker_pull_invoked = $false",
        "package_manager_install_invoked = $false",
        'compose_pull_policy_required = "never"',
        "immoapp-managed/server:local",
        "immoapp-managed/caddy:2.9.1",
        "managed_runtime_image_source_not_pinned",
        "managed_runtime_app_image_commit_mismatch",
        "org.opencontainers.image.revision",
        "IMMOAPP_SOURCE_COMMIT_SHA",
        "Assert-AppImageRevision",
        "app_image_source_commit_sha",
        "app_image_revision_label",
        "app_image_revision_verified",
        "image_archive_host_path",
        "image_archive_wsl_path",
    ):
        if token not in image_bundle_builder:
            raise SystemExit(
                "verify_runtime_contracts: managed WSL2 image bundle builder missing token: "
                f"{token}"
            )
    if (
        'source = "openbao/openbao:latest"' in image_bundle_builder
        or ':latest"; tag' in image_bundle_builder
    ):
        raise SystemExit(
            "verify_runtime_contracts: managed WSL2 image bundle builder contains latest source."
        )
    for forbidden in ("docker pull", "apt install", "apt-get install", "winget", "choco"):
        if forbidden in image_bundle_builder.lower():
            raise SystemExit(
                "verify_runtime_contracts: managed WSL2 image bundle builder contains "
                f"forbidden token: {forbidden}"
            )
    dockerfile = _read("deployment/docker/Dockerfile")
    for token in (
        "ARG IMMOAPP_SOURCE_COMMIT_SHA",
        "LABEL org.opencontainers.image.revision",
    ):
        if token not in dockerfile:
            raise SystemExit(
                "verify_runtime_contracts: Dockerfile missing app image source label token: "
                f"{token}"
            )
    bootstrap = _read("scripts/bootstrap_managed_wsl2_runtime.ps1")
    for token in (
        "immoapp_managed_wsl2_runtime_bootstrap_evidence",
        "ImmoAppRuntime",
        "immoapp_managed_wsl2_runtime_identity",
        "container_engine_status",
        "compose_status",
        "managed_wsl2_runtime_distribution_missing",
        "managed_wsl2_runtime_identity_mismatch",
        "managed_wsl2_runtime_identity_timeout",
        "bootstrap_timeout_seconds",
        "bootstrap_timed_out",
        "agency_install_status",
        "NO_GO",
    ):
        if token not in bootstrap:
            raise SystemExit(
                "verify_runtime_contracts: managed WSL2 bootstrap verifier missing token: "
                f"{token}"
            )
    if (
        "Assert-WslPolicyEvidence" not in release
        or "Resolve-WslPolicyPhaseEvidence" not in release
        or "runtime_profile_source" not in release
        or "runtime_profile_sha256" not in release
        or "runtime_profile_status" not in release
        or "missing local runtime_profile_path" not in release
        or "default_persisted_config" not in release
        or "Get-ImmoAppRuntimePaths).ConfigRoot" not in release
        or "active config root hub_runtime_profile.json" not in release
        or "$profileSha -cnotmatch" not in release
        or "Get-FileHash -LiteralPath $profilePath -Algorithm SHA256" not in release
        or "$actualProfileSha -cne $profileSha" not in release
        or "WSL2 runtime profile evidence SHA mismatch" not in release
        or "ConvertFrom-Json" not in release
        or 'Get-JsonPropertyValue -Data $runtimeProfile -Name "selected_profile"' not in release
        or 'Get-JsonPropertyValue -Data $runtimeProfile -Name "profile_name"' not in release
        or "observed_hub_runtime_profile mismatch" not in release
        or "selected_hub_runtime_profile" not in release
        or "machine-capacity planned_wsl_memory_gb exceeds selected_hub_runtime_profile cap"
        not in release
        or "machine-capacity planned_wsl_processors exceeds selected_hub_runtime_profile cap"
        not in release
        or "planned_wsl_memory_gb exceeds observed runtime profile cap" not in release
        or "planned_wsl_processors exceeds observed runtime profile cap" not in release
        or "WSL2 policy planning cannot satisfy agency install" not in release
        or 'Complete-Phase -Phase $phaseWslPolicy -Status "N/A"' not in release
        or '"desktop_only", "hub_only", "desktop_and_hub"' not in release
    ):
        raise SystemExit(
            "verify_runtime_contracts: release validation must record WSL policy evidence without agency GO."
        )
    for token in (
        "effective_runtime_envelope_source",
        "planned_wsl_memory_gb",
        "planned_wsl_processors",
        "cap_is_ceiling_not_reservation",
        "sustained_pressure_backoff_required",
    ):
        if token not in profile:
            raise SystemExit(
                "verify_runtime_contracts: runtime profile summary missing WSL envelope token: "
                f"{token}"
            )


def _assert_no_untracked_release_artifacts() -> None:
    result = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    blocked_suffixes = (".zip", ".7z", ".tar", ".gz", ".tgz", ".exe", ".msi")
    blocked_name_tokens = ("proof", "evidence", "bundle", "artifact")
    for line in result.stdout.splitlines():
        if not line.startswith("?? "):
            continue
        rel = line[3:].replace("\\", "/")
        lower = rel.lower()
        if lower.startswith(".tmp/"):
            continue
        if lower.endswith(".ps1") and lower.startswith("scripts/"):
            raise SystemExit(
                "verify_runtime_contracts: new release/runtime scripts must be tracked, "
                f"not left untracked: {rel}"
            )
        name = Path(lower).name
        if lower.endswith(blocked_suffixes) or any(token in name for token in blocked_name_tokens):
            raise SystemExit(
                "verify_runtime_contracts: untracked release/proof artifact under repo root: "
                f"{rel}"
            )


def _assert_hub_installer_closeout_contract() -> None:
    resolver = _read("scripts/resolve_release_installer_artifact.ps1")
    signer = _read("scripts/sign_installer_self_signed.ps1")
    readiness = _read("scripts/collect_hub_runtime_readiness_summary.ps1")
    release = _read("scripts/run_beta_release_validation.ps1")
    for token in (
        "release_artifact_summary_missing_or_ambiguous",
        "release_artifact_inventory_missing_or_ambiguous",
        "Build summary installer_sha256 does not match actual installer hash",
        "Bundle inventory must contain ImmoApp Hub Manager.exe exactly once",
        "release_artifact_no_valid_candidate",
    ):
        if token not in resolver:
            raise SystemExit(
                "verify_runtime_contracts: release artifact resolver missing strict token: "
                f"{token}"
            )
    for token in (
        "self_signed_local_internal",
        "Yacine Larbaoui",
        "unsigned_installer_sha256",
        "signed_installer_sha256",
        'public_beta_distribution_status = "NO-GO self-signed local/internal only"',
        "Set-AuthenticodeSignature",
    ):
        if token not in signer:
            raise SystemExit(
                "verify_runtime_contracts: self-signing script missing local/internal token: "
                f"{token}"
            )
    for token in (
        "Assert-SelfSignedInstallerSignatureEvidence",
        "NO-GO self-signed local/internal only",
        'installer_signature_type = "self_signed_local_internal"',
        "local_internal_signed_status",
    ):
        if token not in release:
            raise SystemExit(
                "verify_runtime_contracts: release validation must keep self-signed separate from public trust: "
                f"{token}"
            )
    for token in (
        "runtime_artifact_status",
        "image_bundle_status",
        "rootfs_status",
        "distro_import_status",
        "provider_registration_status",
        "runtime_start_status",
        "front_door_health_status",
        'public_beta_status = "NO_GO"',
        "hub_manager.ps1 -Action start",
    ):
        if token not in readiness:
            raise SystemExit(
                "verify_runtime_contracts: runtime readiness summary missing separation token: "
                f"{token}"
            )


def _assert_hub_state_and_deletion_contract() -> None:
    common = _read("scripts/common.ps1")
    setup = _read("scripts/setup_office_hub.ps1")
    manager = _read("scripts/hub_manager.ps1")
    manager_app = _read("app/hub_manager_app.py")
    manager_actions = _read("app/hub_manager_actions.py")
    set_identity = _read("scripts/set_hub_identity.ps1")
    support = _read("app/services/support_bundle.py")
    release = _read("scripts/run_beta_release_validation.ps1")
    installer = _read("deployment/installer/ImmoAppBeta.iss")
    install_evidence = _read("scripts/collect_hub_install_evidence.ps1")
    build_installer = _read("scripts/build_desktop_installer.ps1")
    for token in (
        "Get-ImmoAppHubStateManifestPath",
        "Read-ImmoAppHubStateManifest",
        "Write-ImmoAppHubStateManifest",
        "Get-ImmoAppHubStateSummary",
        "Invoke-ImmoAppHubDataDeletion",
        "Read-ImmoAppHubDeleteOwnerAuthorizationEvidence",
        "DELETE HUB DATA",
        "hub_delete_windows_admin_required",
        "hub_delete_runtime_still_running",
        "hub_state_manifest_identity_mismatch",
        "hub_state_manifest_${Label}_reparse_point",
    ):
        if token not in common:
            raise SystemExit(
                "verify_runtime_contracts: Hub state/delete helper missing token: " f"{token}"
            )
    for token in (
        "hub_state_manifest_status",
        "hub_state_manifest_path",
        "Write-ImmoAppHubStateManifest",
    ):
        if token not in setup:
            raise SystemExit(
                "verify_runtime_contracts: Hub setup must write state manifest: " f"{token}"
            )
    if "Write-ImmoAppHubStateManifest" not in set_identity:
        raise SystemExit(
            "verify_runtime_contracts: Hub rename must update hub_state_manifest.json."
        )
    for token in (
        '"delete-hub-data"',
        "ConfirmDeleteHubData",
        "OwnerAuthorizationEvidenceJson",
        "Invoke-ImmoAppHubDataDeletion",
    ):
        if token not in manager:
            raise SystemExit(
                "verify_runtime_contracts: Hub Manager delete-data contract missing: " f"{token}"
            )
    for token in (
        "Danger Zone: delete Hub data",
        "HubManagerLoginDialog",
        "hubManagerLoginUsername",
        "hubManagerLoginPassword",
        "create_owner_authorization_evidence_file",
        "Owner/admin email or username",
        "QLineEdit.EchoMode.Password",
        "DELETE HUB DATA",
        "agency owner/admin login",
        "administrator approval",
        "Uninstall keeps Hub data by default",
        "Hub readiness",
        "Setup checklist",
        "Network",
        "Backup and restore",
        "Hub not started",
        "Network blocked",
    ):
        if token not in manager_app and token not in manager_actions:
            raise SystemExit(
                "verify_runtime_contracts: Hub Manager app must expose guarded Danger Zone: "
                f"{token}"
            )
    if "Path to agency owner/admin authorization evidence JSON" in manager_app:
        raise SystemExit(
            "verify_runtime_contracts: Hub Manager app must collect owner/admin login, "
            "not ask users for authorization JSON paths."
        )
    if 'HubManagerAction(\n        "delete-hub-data"' not in manager_actions:
        raise SystemExit(
            "verify_runtime_contracts: Phase 2 Hub Manager app must expose delete-hub-data "
            "only as a guarded Danger Zone action."
        )
    for token in (
        'schema_version") -ne 2',
        'source") -ne "hub_db"',
        'action") -ne "delete_hub_data"',
        'authorization_scope") -ne "hub_data_delete"',
        "hub_delete_owner_authorization_expired",
        "hub_delete_owner_authorization_malformed_json",
        "hub_delete_owner_authorization_identity_hash_mismatch",
        "hub_delete_owner_authorization_state_hash_mismatch",
        "hub_delete_owner_authorization_lineage_mismatch",
        "plaintext_password_written",
        "Get-ImmoAppHubPreservedDataStateEvidence",
    ):
        if token not in common:
            raise SystemExit(
                "verify_runtime_contracts: Phase 2 delete/preserved-data invariant missing: "
                f"{token}"
            )
    for forbidden in ("DelTree(", "RemoveDir("):
        if forbidden in installer:
            raise SystemExit(
                "verify_runtime_contracts: installer uninstall must preserve Hub data by default: "
                f"{forbidden}"
            )
    if "[UninstallDelete]" in installer:
        allowed_uninstall_delete = {
            'Type: files; Name: "{app}\\is-*.tmp"',
            'Type: files; Name: "{app}\\_internal\\PySide6\\is-*.tmp"',
            'Type: files; Name: "{app}\\deployment\\managed-runtime\\images\\is-*.tmp"',
        }
        uninstall_section = installer.split("[UninstallDelete]", 1)[1].split("[", 1)[0]
        uninstall_delete_lines = {
            line.strip()
            for line in uninstall_section.splitlines()
            if line.strip().startswith("Type:")
        }
        if uninstall_delete_lines != allowed_uninstall_delete:
            raise SystemExit(
                "verify_runtime_contracts: installer [UninstallDelete] may only remove Inno temp files."
            )
    install_section = installer.split("[InstallDelete]", 1)[1].split("[", 1)[0]
    for token in (
        'Type: filesandordirs; Name: "{app}\\core\\__pycache__"',
        'Type: filesandordirs; Name: "{app}\\core\\runtime\\__pycache__"',
        'Type: files; Name: "{app}\\core\\*.pyc"',
        'Type: files; Name: "{app}\\core\\runtime\\*.pyc"',
        'Type: files; Name: "{app}\\is-*.tmp"',
        'Type: files; Name: "{app}\\deployment\\managed-runtime\\images\\is-*.tmp"',
    ):
        if token not in install_section:
            raise SystemExit(
                "verify_runtime_contracts: installer must clean install-root cache/temp leftovers: "
                f"{token}"
            )
    for token in (
        "procedure DeleteInstallerTempFiles(Directory: String);",
        "AddBackslash(Directory) + 'is-*.tmp'",
        "DeleteInstallerTempFiles(ExpandConstant('{app}'));",
        "CleanInstallRootGeneratedLeftovers();",
    ):
        if token not in installer:
            raise SystemExit(
                "verify_runtime_contracts: installer must clean post-extraction Inno temp files: "
                f"{token}"
            )
    for token in (
        "data_preserved_on_uninstall",
        "full_data_wipe_requires_separate_confirmation",
        "preserved_hub_data_state_status",
        "preserved_hub_data_state",
    ):
        if token not in install_evidence:
            raise SystemExit(
                "verify_runtime_contracts: Hub install evidence must prove preserved data state: "
                f"{token}"
            )
    generator = _read("scripts/create_hub_owner_authorization_evidence.py")
    for token in (
        "request_owner_authorization",
        "HubManagerAccessClientError",
        "_approved_output_path",
        "hub_owner_authorization_output_path_unapproved",
        "password_value",
        "plaintext_password_written",
        "session_token_written",
        "hub_identity_sha256",
        "hub_state_manifest_sha256",
        "--base-url",
        "--password-stdin",
        "--password-env",
    ):
        if token not in generator:
            raise SystemExit(
                "verify_runtime_contracts: owner authorization generator missing token: " f"{token}"
            )
    for token in ("get_user_model", "django.setup", "check_password(", '--password"'):
        if token in generator:
            raise SystemExit(
                "verify_runtime_contracts: owner authorization generator must use the Hub "
                f"front door instead of local auth: {token}"
            )
    for token in (
        "scripts.create_hub_owner_authorization_evidence",
        "app.services.hub_manager_access_client",
    ):
        if token not in build_installer:
            raise SystemExit(
                "verify_runtime_contracts: Hub Manager installer build must include owner "
                f"authorization runtime dependency: {token}"
            )
    for token in ("server.immoapp_server.settings", "server.accounts.models"):
        if f'"{token}"' in build_installer:
            raise SystemExit(
                "verify_runtime_contracts: Hub Manager bundle must not include local Hub DB "
                f"auth dependencies: {token}"
            )
    for token in ("hub_state_manifest", "_read_hub_state_manifest_summary"):
        if token not in support:
            raise SystemExit(
                "verify_runtime_contracts: support bundle must include sanitized Hub state: "
                f"{token}"
            )
    if "hub_state_manifest_status must be GO" not in release:
        raise SystemExit(
            "verify_runtime_contracts: release validation must require Hub state manifest GO."
        )


def main() -> int:
    _assert_no_legacy_cache_all()
    _assert_no_legacy_schedule_intervals()
    _assert_worker_beat_healthchecks()
    _assert_web_runtime_contract()
    _assert_hub_network_boundary()
    _assert_hub_runtime_detection_contract()
    _assert_managed_wsl2_runtime_policy_contract()
    _assert_hub_installer_closeout_contract()
    _assert_hub_state_and_deletion_contract()
    _assert_no_untracked_release_artifacts()
    print("verify_runtime_contracts: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
