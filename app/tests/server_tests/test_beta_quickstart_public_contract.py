from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
QUICKSTART = ROOT / "quickstart.ps1"
README = ROOT / "README.md"
START_LAUNCHER = ROOT / "Start ImmoApp Beta.cmd"
STOP_LAUNCHER = ROOT / "Stop ImmoApp Beta.cmd"


def test_public_beta_quickstart_is_one_command_and_documents_prerequisites() -> None:
    text = README.read_text(encoding="utf-8")
    assert "powershell -NoProfile -ExecutionPolicy Bypass -File .\\quickstart.ps1" in text
    assert "Windows 10 or 11" in text
    assert "Python 3.14" in text
    assert "Docker Desktop" in text
    assert "Start ImmoApp Beta.cmd" in text


def test_quickstart_exports_generated_credentials_for_compose_precedence() -> None:
    text = QUICKSTART.read_text(encoding="utf-8")
    for name in (
        "POSTGRES_PASSWORD",
        "POSTGRES_ADMIN_PASSWORD",
        "RABBITMQ_PASSWORD",
        "MINIO_ROOT_PASSWORD",
        "STORAGE_SECRET_KEY",
        "MINIO_KMS_SECRET_KEY",
    ):
        assert f"$env:{name} =" in text
    assert 'scripts\\stack.ps1") -Action up -UseWindowsVolumes' in text


def test_quickstart_launches_client_against_local_backend() -> None:
    text = QUICKSTART.read_text(encoding="utf-8")
    assert 'http://127.0.0.1:8000/api/v1/health/' in text
    assert 'Join-Path $repoRoot "scripts\\run_client.ps1"' in text
    assert '& $clientScript -BaseUrl "http://127.0.0.1:8000"' in text
    assert 'Username: owner' in text
    assert 'Password: admin' in text


def test_dev_docker_wrapper_tolerates_normal_docker_stderr_progress() -> None:
    text = (ROOT / "scripts" / "stack.ps1").read_text(encoding="utf-8")
    assert '$ErrorActionPreference = "Continue"' in text
    assert '& docker @prefix @DockerArgs 2>&1' in text
    assert '$dockerExitCode = $LASTEXITCODE' in text
    assert '$global:LASTEXITCODE = $dockerExitCode' in text
    assert '$normalizedOutput = @(' in text
    assert '[string]$_.Exception.Message' in text


def test_quickstart_keeps_runtime_topology_out_of_openbao() -> None:
    text = QUICKSTART.read_text(encoding="utf-8")
    assert '$betaSecretsAllowlist = "ALE_,DJANGO_,IMMOAPP_,POSTGRES_,RABBITMQ_,CELERY_BROKER_URL,MINIO_,STORAGE_,SIGNOZ_,JWT_"' in text
    assert 'Set-DotEnvValue -Path $envFile -Name "IMMOAPP_SECRETS_ALLOWLIST"' in text
    allowlist_line = next(
        line for line in text.splitlines() if line.startswith('$betaSecretsAllowlist = ')
    )
    assert "VALKEY_URL" not in allowlist_line
    assert "CHANNEL_LAYER_URL" not in allowlist_line


def test_windows_powershell_web_requests_use_basic_parsing() -> None:
    stack = (ROOT / "scripts" / "stack.ps1").read_text(encoding="utf-8")
    common = (ROOT / "scripts" / "common.ps1").read_text(encoding="utf-8")
    assert "Invoke-WebRequest -Method Get -Uri $healthUri -Headers $probeHeaders -TimeoutSec 3 -UseBasicParsing" in stack
    assert 'Invoke-WebRequest -Method Get -Uri "$($Addr.TrimEnd(\'/\'))/v1/sys/health" -TimeoutSec 3 -UseBasicParsing' in common


def test_quickstart_bootstrap_does_not_force_network_upgrade_on_every_rerun() -> None:
    common = (ROOT / "scripts" / "common.ps1").read_text(encoding="utf-8")
    assert "pip --disable-pip-version-check install -r $RequirementsPath" in common
    assert "pip --disable-pip-version-check install --upgrade -r $RequirementsPath" not in common


def test_db_prepare_does_not_boot_celery_or_probe_redis() -> None:
    stack = (ROOT / "scripts" / "stack.ps1").read_text(encoding="utf-8")
    assert stack.count('"IMMOAPP_SKIP_CELERY_APP=1"') >= 4
    assert '"immoapp_db_prepare", "--seed-local-dev"' in stack


def test_public_beta_has_double_click_start_and_stop_launchers() -> None:
    start = START_LAUNCHER.read_text(encoding="utf-8")
    stop = STOP_LAUNCHER.read_text(encoding="utf-8")

    assert 'quickstart.ps1" -DetachClient' in start
    assert 'cd /d "%~dp0"' in start
    assert "pause" in start.lower()
    assert "BETA TEST LOGIN" in start
    assert "Username: owner" in start
    assert "Password: admin" in start
    assert 'choice /C Q /N /M "Press Q only if you want to close this reminder window: "' in start
    assert "Demo login: owner / admin" in start
    assert 'scripts\\stack.ps1" -Action down -UseWindowsVolumes' in stop


def test_quickstart_limits_elevation_to_bootstrap_and_supports_detached_client() -> None:
    text = QUICKSTART.read_text(encoding="utf-8")
    assert "[switch]$BootstrapOnly" in text
    assert "[switch]$DetachClient" in text
    assert "-BootstrapOnly -BootstrapLogPath" in text
    assert "-WindowStyle Hidden -Wait -PassThru" in text
    assert "The desktop application itself will continue as your normal Windows user." in text
    assert "Existing Python environments match this repository; no UAC prompt is needed." in text
    assert "-NoExit" not in text



def test_quickstart_recovers_orphaned_openbao_state_and_uses_stable_project_name() -> None:
    text = QUICKSTART.read_text(encoding="utf-8")
    assert '$env:COMPOSE_PROJECT_NAME = "immoapp-beta"' in text
    assert "function Repair-BetaOrphanedOpenBaoState" in text
    assert '"openbao_data", "openbao_logs"' in text
    assert 'label=com.docker.compose.project=$projectName' in text
    assert 'label=com.docker.compose.volume=$logicalVolume' in text
    # Windows PowerShell 5.1 scalarizes a one-item pipeline unless the whole
    # filtered result is array-wrapped; StrictMode then breaks on `.Count`.
    assert '$ids = @(@(Invoke-BetaDockerText -DockerArgs @(' in text
    assert ')) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })' in text
    assert "Repair-BetaOrphanedOpenBaoState" in text
    assert "Container diagnostics:" in text

