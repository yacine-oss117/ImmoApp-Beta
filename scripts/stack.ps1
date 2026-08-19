param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("up", "up-existing", "up-infra", "build-app", "db-prepare", "up-app", "up-app-existing", "up-full", "up-prod", "preflight-prod", "down", "ps", "logs", "logs-infra", "logs-full", "restart-app", "sync-secrets", "provision-alerts")]
    [string]$Action,
    [string]$EnvFile = "",
    [switch]$UseWindowsVolumes,
    [switch]$NoWindowsVolumes
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "common.ps1")

# Existing ProgramData trees created by an elevated quick start may need a
# one-time ACL repair before normal-user commands can persist runtime profile
# state or logs. The helper self-elevates only when repair is actually needed.
Invoke-ImmoAppRuntimePermissionRepairIfNeeded -AutoRepair | Out-Null

$runtimePaths = Ensure-ImmoAppRuntimeLayout
if (-not $EnvFile) {
    $EnvFile = Get-ImmoAppDefaultEnvFile
}
if (-not (Test-Path $EnvFile)) {
    $bootstrapScript = Join-Path $PSScriptRoot "bootstrap_local_runtime.ps1"
    throw "Env file not found: $EnvFile. Run 'powershell -NoProfile -ExecutionPolicy Bypass -File $bootstrapScript' first."
}

function Get-EnvValueFromFile {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Name
    )
    if (-not (Test-Path $Path)) {
        return ""
    }
    foreach ($rawLine in Get-Content $Path) {
        $line = $rawLine.Trim()
        if ([string]::IsNullOrWhiteSpace($line)) { continue }
        if ($line.StartsWith("#")) { continue }
        $eq = $line.IndexOf("=")
        if ($eq -le 0) { continue }
        $key = $line.Substring(0, $eq).Trim()
        if ($key -ne $Name) { continue }
        $value = $line.Substring($eq + 1).Trim()
        if (
            ($value.StartsWith("'") -and $value.EndsWith("'")) -or
            ($value.StartsWith('"') -and $value.EndsWith('"'))
        ) {
            $value = $value.Substring(1, $value.Length - 2)
        }
        return $value
    }
    return ""
}

function Resolve-OpenBaoReadPath {
    param([Parameter(Mandatory = $true)][string]$SecretPath)

    $cleaned = $SecretPath.Trim().TrimStart("/").TrimEnd("/")
    if ([string]::IsNullOrWhiteSpace($cleaned)) {
        throw "OpenBao secret path is empty."
    }
    if ($cleaned.Contains("/data/") -or $cleaned.Contains("/metadata/")) {
        return $cleaned
    }
    $segments = $cleaned.Split("/", [System.StringSplitOptions]::RemoveEmptyEntries)
    if ($segments.Length -le 1) {
        return $cleaned
    }
    $mount = $segments[0]
    $key = ($segments | Select-Object -Skip 1) -join "/"
    return "$mount/data/$key"
}

function Resolve-OpenBaoAppRoleToken {
    param(
        [Parameter(Mandatory = $true)][string]$EnvFilePath,
        [Parameter(Mandatory = $true)][string]$Addr,
        [hashtable]$Headers
    )

    $roleId = if ($env:BAO_ROLE_ID) { $env:BAO_ROLE_ID } else { Get-EnvValueFromFile -Path $EnvFilePath -Name "BAO_ROLE_ID" }
    $secretId = if ($env:BAO_SECRET_ID) { $env:BAO_SECRET_ID } else { Get-EnvValueFromFile -Path $EnvFilePath -Name "BAO_SECRET_ID" }
    $approleFile = if ($env:BAO_APPROLE_FILE) { $env:BAO_APPROLE_FILE } else { Get-EnvValueFromFile -Path $EnvFilePath -Name "BAO_APPROLE_FILE" }

    if (([string]::IsNullOrWhiteSpace($roleId) -or [string]::IsNullOrWhiteSpace($secretId)) -and -not [string]::IsNullOrWhiteSpace($approleFile)) {
        if (-not (Test-Path $approleFile)) {
            Write-Warning "OpenBao AppRole file not found for compose env hydration: $approleFile"
            return ""
        }
        try {
            $parsed = Get-Content $approleFile -Raw | ConvertFrom-Json
        }
        catch {
            Write-Warning "OpenBao AppRole file parse failed for compose env hydration ($approleFile): $($_.Exception.Message)"
            return ""
        }
        if ([string]::IsNullOrWhiteSpace($roleId)) {
            $roleId = [string]$parsed.app_role_id
            if ([string]::IsNullOrWhiteSpace($roleId)) {
                $roleId = [string]$parsed.role_id
            }
        }
        if ([string]::IsNullOrWhiteSpace($secretId)) {
            $secretId = [string]$parsed.app_secret_id
            if ([string]::IsNullOrWhiteSpace($secretId)) {
                $secretId = [string]$parsed.secret_id
            }
        }
    }

    if ([string]::IsNullOrWhiteSpace($roleId) -or [string]::IsNullOrWhiteSpace($secretId)) {
        return ""
    }

    $loginHeaders = @{}
    if ($Headers) {
        foreach ($entry in $Headers.GetEnumerator()) {
            $loginHeaders[$entry.Key] = $entry.Value
        }
    }
    $body = @{ role_id = $roleId.Trim(); secret_id = $secretId.Trim() } | ConvertTo-Json -Compress
    try {
        $response = Invoke-RestMethod -Method Post -Uri "$Addr/v1/auth/approle/login" -Headers $loginHeaders -Body $body -ContentType "application/json"
        $clientToken = [string]$response.auth.client_token
        return $clientToken
    }
    catch {
        Write-Warning "OpenBao AppRole login failed for compose env hydration ($Addr/v1/auth/approle/login): $($_.Exception.Message)"
        return ""
    }
}

function Test-OpenBaoReachable {
    param(
        [Parameter(Mandatory = $true)][string]$Addr,
        [hashtable]$Headers
    )

    $healthUri = "$($Addr.TrimEnd('/'))/v1/sys/health"
    $probeHeaders = @{}
    if ($Headers) {
        foreach ($entry in $Headers.GetEnumerator()) {
            $probeHeaders[$entry.Key] = $entry.Value
        }
    }

    try {
        Invoke-WebRequest -Method Get -Uri $healthUri -Headers $probeHeaders -TimeoutSec 3 -UseBasicParsing | Out-Null
        return $true
    }
    catch {
        if ($_.Exception.Response) {
            return $true
        }
        return $false
    }
}

function Set-ComposeEnvFromOpenBao {
    param([string]$EnvFilePath)

    $backend = if ($env:IMMOAPP_SECRETS_BACKEND) { $env:IMMOAPP_SECRETS_BACKEND } else { Get-EnvValueFromFile -Path $EnvFilePath -Name "IMMOAPP_SECRETS_BACKEND" }
    if ([string]::IsNullOrWhiteSpace($backend) -or $backend.ToLower() -ne "openbao") {
        return
    }

    $path = if ($env:IMMOAPP_SECRETS_PATH) { $env:IMMOAPP_SECRETS_PATH } else { Get-EnvValueFromFile -Path $EnvFilePath -Name "IMMOAPP_SECRETS_PATH" }
    if ([string]::IsNullOrWhiteSpace($path)) {
        return
    }

    $addr = if ($env:BAO_ADDR) { $env:BAO_ADDR } else { Get-EnvValueFromFile -Path $EnvFilePath -Name "BAO_ADDR" }
    if ([string]::IsNullOrWhiteSpace($addr)) {
        # BAO_ADDR_DOCKER is a container-network address; do not treat it as host-reachable here.
        # If host BAO_ADDR is not explicitly configured, skip hydration and rely on env-file values.
        $addrDocker = if ($env:BAO_ADDR_DOCKER) { $env:BAO_ADDR_DOCKER } else { Get-EnvValueFromFile -Path $EnvFilePath -Name "BAO_ADDR_DOCKER" }
        if (-not [string]::IsNullOrWhiteSpace($addrDocker)) {
            return
        }
        $addr = "http://127.0.0.1:8200"
    }
    $addr = $addr.TrimEnd("/")
    $namespace = if ($env:BAO_NAMESPACE) { $env:BAO_NAMESPACE } else { Get-EnvValueFromFile -Path $EnvFilePath -Name "BAO_NAMESPACE" }
    $readHeaders = @{}
    if (-not [string]::IsNullOrWhiteSpace($namespace)) {
        $readHeaders["X-Vault-Namespace"] = $namespace
    }
    try {
        $readPath = Resolve-OpenBaoReadPath -SecretPath $path
    }
    catch {
        Write-Warning "OpenBao secret path is invalid for compose env hydration ($path): $($_.Exception.Message)"
        return
    }
    $readUri = "$addr/v1/$readPath"
    if (-not (Test-OpenBaoReachable -Addr $addr -Headers $readHeaders)) {
        return
    }

    $tokenCandidates = New-Object System.Collections.Generic.List[string]
    $token = if ($env:BAO_TOKEN) { $env:BAO_TOKEN } else { Get-EnvValueFromFile -Path $EnvFilePath -Name "BAO_TOKEN" }
    if (-not [string]::IsNullOrWhiteSpace($token)) {
        $tokenCandidates.Add($token.Trim())
    }
    $tokenFile = if ($env:BAO_TOKEN_FILE) { $env:BAO_TOKEN_FILE } else { Get-EnvValueFromFile -Path $EnvFilePath -Name "BAO_TOKEN_FILE" }
    if (-not [string]::IsNullOrWhiteSpace($tokenFile) -and (Test-Path $tokenFile)) {
        $fileToken = (Get-Content $tokenFile -Raw).Trim()
        if (-not [string]::IsNullOrWhiteSpace($fileToken)) {
            $tokenCandidates.Add($fileToken)
        }
    }
    $rootTokenFile = Join-Path (Get-ImmoAppAppDataRoot) "secrets\openbao.token"
    if (Test-Path $rootTokenFile) {
        $rootToken = (Get-Content $rootTokenFile -Raw).Trim()
        if (-not [string]::IsNullOrWhiteSpace($rootToken)) {
            $tokenCandidates.Add($rootToken)
        }
    }
    $tokenCandidates.Add("dev-root-token")

    $secret = $null
    $lastError = ""
    foreach ($candidate in ($tokenCandidates | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Select-Object -Unique)) {
        $headers = @{}
        foreach ($entry in $readHeaders.GetEnumerator()) {
            $headers[$entry.Key] = $entry.Value
        }
        $headers["X-Vault-Token"] = $candidate
        try {
            $secret = Invoke-RestMethod -Method Get -Uri $readUri -Headers $headers
            break
        }
        catch {
            $lastError = $_.Exception.Message
        }
    }
    if ($null -eq $secret) {
        $approleToken = Resolve-OpenBaoAppRoleToken -EnvFilePath $EnvFilePath -Addr $addr -Headers $readHeaders
        if (-not [string]::IsNullOrWhiteSpace($approleToken)) {
            $headers = @{}
            foreach ($entry in $readHeaders.GetEnumerator()) {
                $headers[$entry.Key] = $entry.Value
            }
            $headers["X-Vault-Token"] = $approleToken
            try {
                $secret = Invoke-RestMethod -Method Get -Uri $readUri -Headers $headers
            }
            catch {
                $lastError = $_.Exception.Message
            }
        }
    }
    if ($null -eq $secret) {
        if ([string]::IsNullOrWhiteSpace($lastError)) {
            $lastError = "no token or AppRole credentials resolved"
        }
        Write-Warning "OpenBao read failed for compose env hydration ($readUri): $lastError"
        return
    }
    $data = $secret.data.data
    if ($null -eq $data) {
        Write-Warning "OpenBao path '$readPath' returned no data for compose env hydration."
        return
    }

    $required = @(
        "POSTGRES_DB",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "POSTGRES_ADMIN_USER",
        "POSTGRES_ADMIN_PASSWORD",
        "RABBITMQ_USER",
        "RABBITMQ_PASSWORD",
        "MINIO_ROOT_USER",
        "MINIO_ROOT_PASSWORD",
        "MINIO_KMS_SECRET_KEY",
        "STORAGE_BUCKET"
    )
    foreach ($name in $required) {
        $existing = Get-Item "Env:$name" -ErrorAction SilentlyContinue
        if ($existing -and -not [string]::IsNullOrWhiteSpace([string]$existing.Value)) {
            continue
        }
        $value = $data.$name
        if ($null -eq $value) {
            continue
        }
        $text = [string]$value
        if ([string]::IsNullOrWhiteSpace($text)) {
            continue
        }
        Set-Item -Path "Env:$name" -Value $text
    }
}

function Set-ComposeEnvFromBootstrapFile {
    param([Parameter(Mandatory = $true)][string]$EnvFilePath)

    $bootstrapPath = Join-Path (Split-Path -Parent $EnvFilePath) ".env.bootstrap.openbao"
    $defaults = @{
        "POSTGRES_DB" = "immoapp"
        "POSTGRES_USER" = "immoapp_app"
        "POSTGRES_PASSWORD" = "immoapp_app_password"
        "POSTGRES_ADMIN_USER" = "immoapp"
        "POSTGRES_ADMIN_PASSWORD" = "immoapp_admin_password"
        "RABBITMQ_USER" = "immoapp"
        "RABBITMQ_PASSWORD" = "immoapp_rabbit_password"
        "MINIO_ROOT_USER" = "immoapp"
        "MINIO_ROOT_PASSWORD" = "immoapp123"
        "MINIO_KMS_SECRET_KEY" = "immoapp-kms-key:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
        "STORAGE_BUCKET" = "immoapp"
        "DJANGO_SECRET_KEY" = "dev-unsafe-secret-key-change-me"
        "ALE_KEY_VERSION" = "v1"
        "ALE_MASTER_KEY" = "test-master-key-32-bytes-minimum"
        "ALE_SEARCH_SECRET" = "test-search-secret"
        "ALE_KDF_SALT" = "test-kdf-salt-123456"
        "STORAGE_SECRET_KEY" = "immoapp123"
        "JWT_SECRET_KEY" = "dev-jwt-secret-key-change-me"
    }
    if (-not (Test-Path $bootstrapPath)) {
        $bootstrapPath = ""
    }

    $required = @(
        "POSTGRES_DB",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "POSTGRES_ADMIN_USER",
        "POSTGRES_ADMIN_PASSWORD",
        "RABBITMQ_USER",
        "RABBITMQ_PASSWORD",
        "MINIO_ROOT_USER",
        "MINIO_ROOT_PASSWORD",
        "MINIO_KMS_SECRET_KEY",
        "STORAGE_BUCKET",
        "DJANGO_SECRET_KEY",
        "ALE_KEY_VERSION",
        "ALE_MASTER_KEY",
        "ALE_SEARCH_SECRET",
        "ALE_KDF_SALT",
        "CELERY_BROKER_URL",
        "STORAGE_SECRET_KEY",
        "JWT_SECRET_KEY"
    )

    foreach ($name in $required) {
        $existing = Get-Item "Env:$name" -ErrorAction SilentlyContinue
        if ($existing -and -not [string]::IsNullOrWhiteSpace([string]$existing.Value)) {
            continue
        }
        $value = ""
        if (-not [string]::IsNullOrWhiteSpace($bootstrapPath)) {
            $value = Get-EnvValueFromFile -Path $bootstrapPath -Name $name
        }
        if ([string]::IsNullOrWhiteSpace($value) -and $defaults.ContainsKey($name)) {
            $value = $defaults[$name]
        }
        if ([string]::IsNullOrWhiteSpace($value)) {
            continue
        }
        Set-Item -Path "Env:$name" -Value $value
    }

    $broker = Get-Item "Env:CELERY_BROKER_URL" -ErrorAction SilentlyContinue
    if (-not $broker -or [string]::IsNullOrWhiteSpace([string]$broker.Value)) {
        $user = [string](Get-Item "Env:RABBITMQ_USER").Value
        $password = [string](Get-Item "Env:RABBITMQ_PASSWORD").Value
        if (-not [string]::IsNullOrWhiteSpace($user) -and -not [string]::IsNullOrWhiteSpace($password)) {
            Set-Item -Path "Env:CELERY_BROKER_URL" -Value "amqp://${user}:${password}@rabbitmq:5672//"
        }
    }
}

function Get-DevDockerInvocationPrefix {
    $prefix = @()
    $context = ""
    if ($env:IMMOAPP_DEV_DOCKER_CONTEXT) {
        $context = [string]$env:IMMOAPP_DEV_DOCKER_CONTEXT
    }
    elseif ($env:DOCKER_CONTEXT) {
        $context = [string]$env:DOCKER_CONTEXT
    }
    elseif (Test-ImmoAppHostWindows) {
        # stack.ps1 is a repo/dev helper. Do not route it through the installed
        # Hub runtime provider, because that provider can be managed WSL2 and
        # intentionally has no host Docker/Compose command.
        $context = "desktop-linux"
    }
    if (-not [string]::IsNullOrWhiteSpace($context)) {
        $prefix += @("--context", $context)
    }
    return $prefix
}

function Invoke-DevDocker {
    param([string[]]$DockerArgs)
    $prefix = Get-DevDockerInvocationPrefix

    # Windows PowerShell 5.1 turns native stderr lines into PowerShell error
    # records. Docker Compose writes normal progress messages (for example
    # "Network ... Creating") to stderr even when the command is succeeding.
    # With this script's ErrorActionPreference=Stop, those harmless progress
    # lines would otherwise abort the stack before Docker can finish.
    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $output = & docker @prefix @DockerArgs 2>&1
        $dockerExitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }

    # Preserve the native command status for Invoke-Compose and readiness checks.
    # Convert native stderr ErrorRecord objects to plain strings first so normal
    # Docker progress does not get serialized into scary NativeCommandError
    # records when Quick Start redirects the wrapper output to its log file.
    $normalizedOutput = @(
        $output | ForEach-Object {
            if ($_ -is [System.Management.Automation.ErrorRecord]) {
                [string]$_.Exception.Message
            }
            else {
                [string]$_
            }
        }
    )
    $global:LASTEXITCODE = $dockerExitCode
    return $normalizedOutput
}

function Invoke-Compose {
    param([string[]]$ComposeArgs)
    Invoke-DevDocker -DockerArgs (@("compose") + $ComposeArgs)
    if ($LASTEXITCODE -ne 0) {
        throw "Dev Docker Compose failed: $($ComposeArgs -join ' ')"
    }
}

function Wait-ComposeServiceHealthy {
    param(
        [Parameter(Mandatory = $true)][string[]]$ComposeArgs,
        [Parameter(Mandatory = $true)][string]$Service,
        [int]$TimeoutSeconds = 180
    )

    $deadline = [DateTimeOffset]::UtcNow.AddSeconds($TimeoutSeconds)
    $lastStatus = "not observed"
    do {
        $output = Invoke-DevDocker -DockerArgs (@("compose") + $ComposeArgs + @("ps", "--format", "json", $Service)) 2>$null
        if ($LASTEXITCODE -eq 0 -and $output) {
            foreach ($line in @($output)) {
                if ([string]::IsNullOrWhiteSpace($line)) {
                    continue
                }
                $serviceState = $line | ConvertFrom-Json
                $state = [string]$serviceState.State
                $health = [string]$serviceState.Health
                $lastStatus = "state=$state health=$health"
                if ($state -eq "running" -and ($health -eq "healthy" -or [string]::IsNullOrWhiteSpace($health))) {
                    Write-Host "Compose service '$Service' is ready ($lastStatus)."
                    return
                }
            }
        }
        else {
            $lastStatus = "Dev Docker Compose ps unavailable"
        }
        Write-Host "Waiting for compose service '$Service' readiness ($lastStatus)."
        Start-Sleep -Seconds 2
    } while ([DateTimeOffset]::UtcNow -lt $deadline)

    throw "Compose service '$Service' did not become healthy within $TimeoutSeconds seconds ($lastStatus)."
}

function Wait-ImmoAppServicesHealthy {
    param([Parameter(Mandatory = $true)][string[]]$ComposeArgs)

    foreach ($service in @("web", "worker", "worker-import", "worker-match", "worker-rebuild", "beat")) {
        Wait-ComposeServiceHealthy -ComposeArgs $ComposeArgs -Service $service
    }
}

function Get-LocalBootstrapSecretsFile {
    $configured = if ($env:IMMOAPP_BOOTSTRAP_SECRETS_FILE) {
        $env:IMMOAPP_BOOTSTRAP_SECRETS_FILE
    }
    else {
        ""
    }
    if (-not [string]::IsNullOrWhiteSpace($configured) -and (Test-Path $configured)) {
        return $configured
    }
    return (Join-Path (Get-ImmoAppAppDataRoot) "secrets\immoapp-dev-secrets.json")
}

function Assert-LocalBootstrapSecretsFile {
    $path = Get-LocalBootstrapSecretsFile
    if (-not (Test-Path $path)) {
        $bootstrapScript = Join-Path $PSScriptRoot "bootstrap_local_runtime.ps1"
        throw "Local bootstrap secrets file not found: $path. Run '$bootstrapScript' first to create the canonical bootstrap files, then run 'powershell -NoProfile -ExecutionPolicy Bypass -File scripts/stack.ps1 -Action up-infra -UseWindowsVolumes' to seed OpenBao."
    }
    try {
        $parsed = Get-Content $path -Raw | ConvertFrom-Json
    }
    catch {
        throw "Local bootstrap secrets file is not valid JSON: $path"
    }
    if ($null -eq $parsed) {
        throw "Local bootstrap secrets file is empty: $path"
    }
    return $path
}

function Sync-LocalSecrets {
    Assert-NoLegacyOpenBaoContainers
    $null = Assert-LocalBootstrapSecretsFile
    Invoke-Compose ($app + @("up", "-d", "openbao"))
    Invoke-Compose ($app + @("up", "-d", "--force-recreate", "openbao-init"))
    Invoke-Compose ($app + @("up", "-d", "--force-recreate", "openbao-seed"))
    Invoke-Compose ($app + @("up", "-d", "--force-recreate") + $appRuntimeServicesWithFrontDoor)
}

if ($UseWindowsVolumes -and $NoWindowsVolumes) {
    throw "UseWindowsVolumes and NoWindowsVolumes cannot both be set."
}

$composeNames = @("compose.yml")
$useWindowsVolumeMode = if ($UseWindowsVolumes) { $true } else { Test-ImmoAppWindowsVolumeMode -NoWindowsVolumes:$NoWindowsVolumes }
if ($useWindowsVolumeMode) {
    $composeNames += "compose.windows.yml"
}
$composeFiles = Get-ImmoAppComposeArgs -Names $composeNames

$env:IMMOAPP_RUNTIME_ENV_FILE = $EnvFile
$composeProfiles = Get-EnvValueFromFile -Path $EnvFile -Name "COMPOSE_PROFILES"
if (-not [string]::IsNullOrWhiteSpace($composeProfiles)) {
    $env:COMPOSE_PROFILES = $composeProfiles
}
$hubFrontDoorEnabled = (($env:COMPOSE_PROFILES -split "," | ForEach-Object { $_.Trim() }) -contains "hub-front-door")
if ($hubFrontDoorEnabled) {
    $backendHostPort = Get-EnvValueFromFile -Path $EnvFile -Name "IMMOAPP_BACKEND_HOST_PORT"
    if ([string]::IsNullOrWhiteSpace($backendHostPort) -and [string]::IsNullOrWhiteSpace($env:IMMOAPP_BACKEND_HOST_PORT)) {
        $env:IMMOAPP_BACKEND_HOST_PORT = "18000"
    }
    $backendBindHost = Get-EnvValueFromFile -Path $EnvFile -Name "IMMOAPP_WEB_BIND_HOST"
    if ([string]::IsNullOrWhiteSpace($backendBindHost) -and [string]::IsNullOrWhiteSpace($env:IMMOAPP_WEB_BIND_HOST)) {
        $env:IMMOAPP_WEB_BIND_HOST = "127.0.0.1"
    }
}
$appRuntimeServices = @("web", "worker", "worker-import", "worker-rebuild", "worker-match", "beat")
$appRuntimeServicesWithFrontDoor = @($appRuntimeServices)
if ($hubFrontDoorEnabled) {
    $appRuntimeServicesWithFrontDoor += "caddy"
}
$base = (Get-ImmoAppComposeProjectArgs) + @("--env-file", $EnvFile) + $composeFiles
$app = $base + (Get-ImmoAppComposeArgs -Names @("compose.app.yml"))
$prod = $base + (Get-ImmoAppComposeArgs -Names @("compose.prod.yml"))
$full = $app + (Get-ImmoAppComposeArgs -Names @("compose.observability.yml"))

$actionsRequiringBootstrapEnv = @(
    "up",
    "up-existing",
    "up-infra",
    "up-app",
    "up-app-existing",
    "up-full",
    "up-prod",
    "preflight-prod",
    "db-prepare",
    "restart-app",
    "sync-secrets"
)
if ($Action -in $actionsRequiringBootstrapEnv) {
    Assert-ImmoAppBootstrapEnvReady -EnvFilePath $EnvFile -ActionName $Action
}

Set-ComposeEnvFromBootstrapFile -EnvFilePath $EnvFile
if ($Action -in @("build-app", "db-prepare", "up-app", "up", "up-full", "up-prod", "preflight-prod", "restart-app", "sync-secrets", "provision-alerts")) {
    Set-ComposeEnvFromOpenBao -EnvFilePath $EnvFile
}
if ($Action -in @("up-app-existing", "up-existing")) {
    Set-ComposeEnvFromOpenBao -EnvFilePath $EnvFile
}
if ($Action -in @("build-app", "up", "up-existing", "up-infra", "up-app", "up-app-existing", "up-full", "up-prod", "restart-app", "preflight-prod", "down", "logs", "logs-infra", "logs-full", "ps", "provision-alerts")) {
    Set-ImmoAppHubRuntimeProfileEnv
}

function Invoke-ComposeWithOtel {
    param([string[]]$ComposeArgs)
    $prevEndpoint = $env:OTEL_EXPORTER_OTLP_ENDPOINT_DOCKER
    $prevProtocol = $env:OTEL_EXPORTER_OTLP_PROTOCOL_DOCKER
    try {
        $env:OTEL_EXPORTER_OTLP_ENDPOINT_DOCKER = "http://otel-collector:4318"
        if (-not $env:OTEL_EXPORTER_OTLP_PROTOCOL_DOCKER) {
            $env:OTEL_EXPORTER_OTLP_PROTOCOL_DOCKER = "http/protobuf"
        }
        Invoke-Compose $ComposeArgs
    }
    finally {
        if ($null -eq $prevEndpoint) {
            Remove-Item Env:OTEL_EXPORTER_OTLP_ENDPOINT_DOCKER -ErrorAction SilentlyContinue
        }
        else {
            $env:OTEL_EXPORTER_OTLP_ENDPOINT_DOCKER = $prevEndpoint
        }
        if ($null -eq $prevProtocol) {
            Remove-Item Env:OTEL_EXPORTER_OTLP_PROTOCOL_DOCKER -ErrorAction SilentlyContinue
        }
        else {
            $env:OTEL_EXPORTER_OTLP_PROTOCOL_DOCKER = $prevProtocol
        }
    }
}

function Assert-NoLegacyOpenBaoContainers {
    $legacyMarkers = @(
        "openbao-agent",
        "openbao-approle-init",
        "openbao-agent-init"
    )
    $names = Invoke-DevDocker -DockerArgs @("ps", "-a", "--format", "{{.Names}}")
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to inspect dev Docker containers for legacy OpenBao services."
    }
    $hits = @()
    foreach ($name in $names) {
        foreach ($marker in $legacyMarkers) {
            if ($name -like "*$marker*") {
                $hits += $name
                break
            }
        }
    }
    if ($hits.Count -gt 0) {
        $joined = ($hits | Sort-Object -Unique) -join ", "
        $composeYml = Get-ImmoAppComposeFile -Name "compose.yml"
        $composeApp = Get-ImmoAppComposeFile -Name "compose.app.yml"
        throw "Legacy OpenBao agent-mode containers detected: $joined. Run the Hub manager stop/start action after cleanup or use the internal stack wrapper with $composeYml and $composeApp if you are developing."
    }
}

function Assert-ProdRuntimeEnv {
    param(
        [Parameter(Mandatory = $true)][string]$EnvFilePath
    )

    function Resolve-EnvValue {
        param(
            [Parameter(Mandatory = $true)][string]$Name,
            [string]$Default = ""
        )
        $current = [Environment]::GetEnvironmentVariable($Name)
        if (-not [string]::IsNullOrWhiteSpace($current)) {
            return $current
        }
        $fromFile = Get-EnvValueFromFile -Path $EnvFilePath -Name $Name
        if (-not [string]::IsNullOrWhiteSpace($fromFile)) {
            [Environment]::SetEnvironmentVariable($Name, $fromFile)
            return $fromFile
        }
        if ($Default -ne "") {
            [Environment]::SetEnvironmentVariable($Name, $Default)
            return $Default
        }
        return ""
    }

    $secureRedirect = Resolve-EnvValue -Name "SECURE_SSL_REDIRECT_DOCKER" -Default "1"
    $sessionSecure = Resolve-EnvValue -Name "SESSION_COOKIE_SECURE_DOCKER" -Default "1"
    $csrfSecure = Resolve-EnvValue -Name "CSRF_COOKIE_SECURE_DOCKER" -Default "1"
    $baoVerify = Resolve-EnvValue -Name "BAO_VERIFY_SSL_DOCKER" -Default "1"
    $publicBaseUrl = Resolve-EnvValue -Name "IMMOAPP_PUBLIC_BASE_URL"
    $tlsDomain = Resolve-EnvValue -Name "IMMOAPP_TLS_DOMAIN"
    $baoAddrs = Resolve-EnvValue -Name "BAO_ADDRS_DOCKER"
    if (-not $baoAddrs) {
        $baoAddrs = Resolve-EnvValue -Name "BAO_ADDR_DOCKER"
    }

    if ($baoVerify -ne "1") {
        throw "Production profile requires BAO_VERIFY_SSL_DOCKER=1."
    }

    if (-not $publicBaseUrl) {
        throw "Production profile requires IMMOAPP_PUBLIC_BASE_URL (https://...)."
    }
    if (-not $publicBaseUrl.ToLower().StartsWith("https://")) {
        throw "IMMOAPP_PUBLIC_BASE_URL must use https:// in production profile."
    }
    if (-not $tlsDomain) {
        try {
            $uri = [Uri]$publicBaseUrl
            $tlsDomain = $uri.Host
            if ($tlsDomain) {
                [Environment]::SetEnvironmentVariable("IMMOAPP_TLS_DOMAIN", $tlsDomain)
            }
        }
        catch {
            $tlsDomain = ""
        }
    }
    if (-not $tlsDomain) {
        throw "Production profile requires IMMOAPP_TLS_DOMAIN (or derivable host from IMMOAPP_PUBLIC_BASE_URL)."
    }

    if (-not $baoAddrs) {
        throw "Production profile requires BAO_ADDR_DOCKER or BAO_ADDRS_DOCKER (https://...)."
    }
    foreach ($addr in $baoAddrs.Split(",")) {
        $clean = $addr.Trim()
        if (-not $clean) { continue }
        if (-not $clean.ToLower().StartsWith("https://")) {
            throw "Production profile requires HTTPS OpenBao address(es). Found: $clean"
        }
    }

    foreach ($flag in @($secureRedirect, $sessionSecure, $csrfSecure)) {
        if ($flag -ne "1") {
            throw "Production profile requires SECURE_SSL_REDIRECT_DOCKER=1, SESSION_COOKIE_SECURE_DOCKER=1, and CSRF_COOKIE_SECURE_DOCKER=1."
        }
    }
}

function Invoke-ProdPreflight {
    param(
        [Parameter(Mandatory = $true)][string]$EnvFilePath
    )
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "preflight_prod.ps1") -EnvFile $EnvFilePath
    if ($LASTEXITCODE -ne 0) {
        throw "preflight_prod.ps1 failed."
    }
}

switch ($Action) {
    "up-infra" {
        Assert-NoLegacyOpenBaoContainers
        Invoke-Compose ($base + @("up", "-d", "db", "rabbitmq", "valkey", "minio", "clamav", "openbao"))
        Wait-ComposeServiceHealthy -ComposeArgs $base -Service "db"
        Invoke-Compose ($base + @("up", "-d", "--force-recreate", "minio-init"))
        Invoke-Compose ($base + @("up", "-d", "--force-recreate", "openbao-init"))
        Invoke-Compose ($base + @("up", "-d", "--force-recreate", "openbao-seed"))
    }
    "build-app" {
        Assert-NoLegacyOpenBaoContainers
        Invoke-Compose ($app + @("build", "web"))
    }
    "db-prepare" {
        Assert-NoLegacyOpenBaoContainers
        Invoke-Compose ($app + @("run", "--rm", "-e", "IMMOAPP_SKIP_CELERY_APP=1", "web", "python", "server/manage.py", "immoapp_db_prepare", "--seed-local-dev"))
    }
    "up-app" {
        Assert-NoLegacyOpenBaoContainers
        Invoke-Compose ($app + @("up", "-d", "openbao"))
        Invoke-Compose ($app + @("up", "-d", "--force-recreate", "openbao-init"))
        Invoke-Compose ($app + @("up", "-d", "--force-recreate", "openbao-seed"))
        Invoke-Compose ($app + @("up", "-d", "--force-recreate") + $appRuntimeServicesWithFrontDoor)
        Wait-ImmoAppServicesHealthy -ComposeArgs $app
    }
    "up-app-existing" {
        Assert-NoLegacyOpenBaoContainers
        Invoke-Compose ($app + @("up", "-d", "--no-build", "openbao"))
        Invoke-Compose ($app + @("up", "-d", "--no-build", "--force-recreate", "openbao-init"))
        Invoke-Compose ($app + @("up", "-d", "--no-build", "--force-recreate", "openbao-seed"))
        Invoke-Compose ($app + @("up", "-d", "--no-build", "--force-recreate") + $appRuntimeServicesWithFrontDoor)
        Wait-ImmoAppServicesHealthy -ComposeArgs $app
    }
    "up" {
        Assert-NoLegacyOpenBaoContainers
        Invoke-Compose ($base + @("up", "-d", "db", "rabbitmq", "valkey", "minio", "clamav", "openbao"))
        Wait-ComposeServiceHealthy -ComposeArgs $base -Service "db"
        Invoke-Compose ($base + @("up", "-d", "--force-recreate", "minio-init"))
        Invoke-Compose ($app + @("build", "web"))
        Invoke-Compose ($app + @("up", "-d", "--force-recreate", "openbao-init"))
        Invoke-Compose ($app + @("up", "-d", "--force-recreate", "openbao-seed"))
        Invoke-Compose ($app + @("run", "--rm", "-e", "IMMOAPP_SKIP_CELERY_APP=1", "web", "python", "server/manage.py", "immoapp_db_prepare", "--seed-local-dev"))
        Invoke-Compose ($app + @("up", "-d", "--force-recreate") + $appRuntimeServicesWithFrontDoor)
        Wait-ImmoAppServicesHealthy -ComposeArgs $app
    }
    "up-existing" {
        Assert-NoLegacyOpenBaoContainers
        Invoke-Compose ($base + @("up", "-d", "--no-build", "db", "rabbitmq", "valkey", "minio", "clamav", "openbao"))
        Wait-ComposeServiceHealthy -ComposeArgs $base -Service "db"
        Invoke-Compose ($base + @("up", "-d", "--no-build", "--force-recreate", "minio-init"))
        Invoke-Compose ($app + @("up", "-d", "--no-build", "--force-recreate", "openbao-init"))
        Invoke-Compose ($app + @("up", "-d", "--no-build", "--force-recreate", "openbao-seed"))
        Invoke-Compose ($app + @("up", "-d", "--no-build", "--force-recreate") + $appRuntimeServicesWithFrontDoor)
        Wait-ImmoAppServicesHealthy -ComposeArgs $app
    }
    "up-full" {
        Assert-NoLegacyOpenBaoContainers
        Invoke-ComposeWithOtel ($full + @(
                "up", "-d",
                "db", "rabbitmq", "valkey", "minio", "clamav", "openbao",
                "zookeeper-1", "clickhouse", "schema-migrator-sync", "signoz", "otel-collector"
            ))
        Wait-ComposeServiceHealthy -ComposeArgs $full -Service "db"
        Invoke-ComposeWithOtel ($full + @("up", "-d", "--force-recreate", "minio-init"))
        Invoke-ComposeWithOtel ($full + @("build", "web"))
        Invoke-ComposeWithOtel ($full + @("up", "-d", "--force-recreate", "openbao-init"))
        Invoke-ComposeWithOtel ($full + @("up", "-d", "--force-recreate", "openbao-seed"))
        Invoke-ComposeWithOtel ($full + @("run", "--rm", "-e", "IMMOAPP_SKIP_CELERY_APP=1", "web", "python", "server/manage.py", "immoapp_db_prepare", "--seed-local-dev"))
        Invoke-ComposeWithOtel ($full + @("up", "-d", "--force-recreate") + $appRuntimeServicesWithFrontDoor)
        Wait-ImmoAppServicesHealthy -ComposeArgs $full
    }
    "up-prod" {
        Assert-NoLegacyOpenBaoContainers
        Assert-ProdRuntimeEnv -EnvFilePath $EnvFile
        Invoke-ProdPreflight -EnvFilePath $EnvFile
        Invoke-Compose ($prod + @("up", "-d", "db", "rabbitmq", "valkey", "minio", "clamav", "openbao"))
        Wait-ComposeServiceHealthy -ComposeArgs $prod -Service "db"
        Invoke-Compose ($prod + @("up", "-d", "--force-recreate", "minio-init"))
        Invoke-Compose ($prod + @("build", "web"))
        Invoke-Compose ($prod + @("up", "-d", "--force-recreate", "openbao-init"))
        Invoke-Compose ($prod + @("up", "-d", "--force-recreate", "openbao-seed"))
        Invoke-Compose ($prod + @("run", "--rm", "-e", "IMMOAPP_SKIP_CELERY_APP=1", "web", "python", "server/manage.py", "immoapp_db_prepare"))
        Invoke-Compose ($prod + @("up", "-d", "--force-recreate") + $appRuntimeServicesWithFrontDoor)
        Wait-ImmoAppServicesHealthy -ComposeArgs $prod
    }
    "preflight-prod" {
        Assert-ProdRuntimeEnv -EnvFilePath $EnvFile
        Invoke-ProdPreflight -EnvFilePath $EnvFile
    }
    "down" {
        Invoke-Compose ($full + @("down", "--remove-orphans"))
    }
    "ps" {
        Invoke-Compose ($full + @("ps"))
    }
    "logs" {
        Invoke-Compose ($app + @("logs", "-f", "--tail=200") + $appRuntimeServicesWithFrontDoor)
    }
    "logs-infra" {
        Invoke-Compose ($base + @("logs", "-f", "--tail=200", "db", "rabbitmq", "valkey", "minio", "clamav", "openbao", "openbao-init", "openbao-seed"))
    }
    "logs-full" {
        Invoke-Compose ($full + @("logs", "-f", "--tail=200"))
    }
    "restart-app" {
        Assert-NoLegacyOpenBaoContainers
        Invoke-Compose ($app + @("up", "-d", "openbao"))
        Invoke-Compose ($app + @("up", "-d", "--force-recreate", "openbao-init"))
        Invoke-Compose ($app + @("up", "-d", "--force-recreate", "openbao-seed"))
        Invoke-Compose ($app + @("up", "-d", "--force-recreate") + $appRuntimeServicesWithFrontDoor)
        Wait-ImmoAppServicesHealthy -ComposeArgs $app
    }
    "sync-secrets" {
        Sync-LocalSecrets
    }
    "provision-alerts" {
        & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "provision_signoz_alerts.ps1") -EnvFile $EnvFile
        if ($LASTEXITCODE -ne 0) {
            throw "SigNoz alert provisioning failed."
        }
    }
}
