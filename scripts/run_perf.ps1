param(
    [ValidateSet("custom", "baseline", "contention")]
    [string]$Profile = "custom",
    [int]$Tenants = 20,
    [int]$RowsPerTenant = 400,
    [int]$ActiveManagers = 0,
    [int]$ActiveOwners = 0,
    [int]$ReadRate = 30,
    [int]$ReadPreAllocatedVUs = 30,
    [int]$ReadMaxVUs = 120,
    [int]$RebuildVUs = 2,
    [string]$Duration = "180s",
    [int]$AuthRetryMax = 8,
    [double]$AuthRetrySleepSec = 1.0,
    [string]$K6SetupTimeout = "180s",
    [switch]$SkipWarmupReadCache,
    [double]$ReadP95Ms = 300,
    [double]$ReadP99Ms = 600,
    [double]$HttpFailedRate = 0.01,
    [int]$DbLatencyMs = 15,
    [int]$DbJitterMs = 5,
    [int]$DbDownstreamBandwidthKbps = 0,
    [int]$RabbitLatencyMs = 10,
    [int]$RabbitJitterMs = 4,
    [string]$Tag = "",
    [switch]$Build,
    [switch]$KeepData,
    [switch]$KeepStack
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

. (Join-Path $PSScriptRoot "common.ps1")

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

if (-not $Tag) {
    $Tag = Get-Date -Format "yyyyMMddHHmmss"
}

$outputDir = Join-Path $repoRoot "scripts/perf_outputs"
New-Item -ItemType Directory -Force -Path $outputDir | Out-Null

$seedFileName = "perf_users_$Tag.json"
$seedFile = Join-Path $outputDir $seedFileName
$summaryFileName = "k6_summary_$Tag.json"
$summaryFile = Join-Path $outputDir $summaryFileName
$latencyFileName = "latency_rollups_$Tag.json"
$latencyFile = Join-Path $outputDir $latencyFileName
$reportFile = Join-Path $outputDir ("perf_report_{0}.json" -f $Tag)

$composeArgs = (Get-ImmoAppComposeProjectArgs) + (Get-ImmoAppComposeArgs -Names @("compose.yml", "compose.perf.yml"))

function Apply-PerfProfile {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name
    )
    switch ($Name) {
        "baseline" {
            $script:Tenants = 10
            $script:RowsPerTenant = 200
            $script:ReadRate = 20
            $script:ReadPreAllocatedVUs = 20
            $script:ReadMaxVUs = 80
            $script:RebuildVUs = 1
            $script:Duration = "120s"
            $script:ReadP95Ms = 350
            $script:ReadP99Ms = 700
            $script:HttpFailedRate = 0.01
            $script:DbLatencyMs = 8
            $script:DbJitterMs = 3
            $script:DbDownstreamBandwidthKbps = 0
            $script:RabbitLatencyMs = 6
            $script:RabbitJitterMs = 2
        }
        "contention" {
            $script:Tenants = 25
            $script:RowsPerTenant = 600
            $script:ReadRate = 45
            $script:ReadPreAllocatedVUs = 45
            $script:ReadMaxVUs = 180
            $script:RebuildVUs = 2
            $script:Duration = "240s"
            $script:ReadP95Ms = 700
            $script:ReadP99Ms = 1400
            $script:HttpFailedRate = 0.02
            $script:DbLatencyMs = 30
            $script:DbJitterMs = 10
            $script:DbDownstreamBandwidthKbps = 2048
            $script:RabbitLatencyMs = 20
            $script:RabbitJitterMs = 8
        }
        default {
            return
        }
    }
}

function Set-PerfRuntimeToxiproxyEnv {
    Set-Item -Path "Env:PERF_DB_LATENCY_MS" -Value ([string]$DbLatencyMs)
    Set-Item -Path "Env:PERF_DB_JITTER_MS" -Value ([string]$DbJitterMs)
    Set-Item -Path "Env:PERF_DB_DOWNSTREAM_BANDWIDTH_KBPS" -Value ([string]$DbDownstreamBandwidthKbps)
    Set-Item -Path "Env:PERF_RABBIT_LATENCY_MS" -Value ([string]$RabbitLatencyMs)
    Set-Item -Path "Env:PERF_RABBIT_JITTER_MS" -Value ([string]$RabbitJitterMs)
}

function Import-PerfEnvFile {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )
    if (-not (Test-Path $Path)) {
        return
    }
    foreach ($rawLine in Get-Content -Path $Path) {
        $line = $rawLine.Trim()
        if (-not $line -or $line.StartsWith("#")) {
            continue
        }
        $idx = $line.IndexOf("=")
        if ($idx -le 0) {
            continue
        }
        $key = $line.Substring(0, $idx).Trim()
        $value = $line.Substring($idx + 1).Trim()
        if ($value.StartsWith('"') -and $value.EndsWith('"') -and $value.Length -ge 2) {
            $value = $value.Substring(1, $value.Length - 2)
        }
        if (-not (Get-Item -Path ("Env:{0}" -f $key) -ErrorAction SilentlyContinue)) {
            Set-Item -Path ("Env:{0}" -f $key) -Value $value
        }
    }
}

function Assert-RequiredEnv {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Names
    )
    foreach ($name in $Names) {
        $item = Get-Item -Path ("Env:{0}" -f $name) -ErrorAction SilentlyContinue
        $value = if ($null -ne $item) { [string]$item.Value } else { "" }
        if (-not $value) {
            throw "Missing required env for perf run: $name"
        }
    }
}

function Set-DefaultPerfSecretsIfMissing {
    $defaults = @{
        POSTGRES_ADMIN_PASSWORD = "immoapp_admin_password"
        POSTGRES_PASSWORD = "immoapp_app_password"
        RABBITMQ_PASSWORD = "immoapp_rabbit_password"
        DJANGO_SECRET_KEY = "immoapp-local-perf-secret-key-change-me"
        DJANGO_ALLOWED_HOSTS = "127.0.0.1,localhost,web"
    }
    foreach ($entry in $defaults.GetEnumerator()) {
        $name = [string]$entry.Key
        $item = Get-Item -Path ("Env:{0}" -f $name) -ErrorAction SilentlyContinue
        $value = if ($null -ne $item) { [string]$item.Value } else { "" }
        if (-not $value) {
            Set-Item -Path ("Env:{0}" -f $name) -Value ([string]$entry.Value)
            Write-Warning "Perf runner set local fallback for missing $name"
        }
    }
}

function Get-ServerPythonPath {
    $candidates = @(
        "C:/ProgramData/ImmoApp/venvs/immoapp-server-py314/Scripts/python.exe",
        (Join-Path $env:PROGRAMDATA "ImmoApp/venvs/immoapp-server-py314/Scripts/python.exe")
    ) | Where-Object { $_ }
    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) {
            return $candidate
        }
    }
    throw "Server venv python was not found. Expected under C:/ProgramData/ImmoApp/venvs."
}

function Invoke-PerfSeeder {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Args
    )
    $serverPython = Get-ServerPythonPath
    $djangoSecretEnvName = "DJANGO_" + "SECRET_KEY"
    $aleSearchSecretEnvName = "ALE_SEARCH_" + "SECRET"
    $original = @{
        DJANGO_SETTINGS_MODULE = $env:DJANGO_SETTINGS_MODULE
        DJANGO_DEBUG = $env:DJANGO_DEBUG
        DJANGO_ALLOWED_HOSTS = $env:DJANGO_ALLOWED_HOSTS
        ALE_SEARCH_SECRET_MASTER = $env:ALE_SEARCH_SECRET_MASTER
        IMMOAPP_SECRETS_BACKEND = $env:IMMOAPP_SECRETS_BACKEND
        IMMOAPP_ALLOW_ENV_SECRETS = $env:IMMOAPP_ALLOW_ENV_SECRETS
        IMMOAPP_SECRETS_REQUIRED = $env:IMMOAPP_SECRETS_REQUIRED
        IMMOAPP_SKIP_CELERY_APP = $env:IMMOAPP_SKIP_CELERY_APP
        POSTGRES_HOST = $env:POSTGRES_HOST
        POSTGRES_PORT = $env:POSTGRES_PORT
        POSTGRES_DB = $env:POSTGRES_DB
        POSTGRES_USER = $env:POSTGRES_USER
        POSTGRES_ADMIN_USER = $env:POSTGRES_ADMIN_USER
    }
    $djangoSecretItem = Get-Item -Path ("Env:{0}" -f $djangoSecretEnvName) -ErrorAction SilentlyContinue
    $aleSearchSecretItem = Get-Item -Path ("Env:{0}" -f $aleSearchSecretEnvName) -ErrorAction SilentlyContinue
    $original[$djangoSecretEnvName] = if ($null -ne $djangoSecretItem) { [string]$djangoSecretItem.Value } else { $null }
    $original[$aleSearchSecretEnvName] = if ($null -ne $aleSearchSecretItem) { [string]$aleSearchSecretItem.Value } else { $null }
    try {
        $env:DJANGO_SETTINGS_MODULE = "server.immoapp_server.settings"
        $env:DJANGO_DEBUG = "1"
        if (-not $env:DJANGO_SECRET_KEY) { $env:DJANGO_SECRET_KEY = "immoapp-local-perf-secret-key-change-me" }
        if (-not $env:DJANGO_ALLOWED_HOSTS) { $env:DJANGO_ALLOWED_HOSTS = "127.0.0.1,localhost" }
        if (-not $env:ALE_SEARCH_SECRET_MASTER -and -not $env:ALE_SEARCH_SECRET) {
            $env:ALE_SEARCH_SECRET_MASTER = "immoapp-local-perf-ale-search-secret"
        }
        $env:IMMOAPP_SECRETS_BACKEND = "env"
        $env:IMMOAPP_ALLOW_ENV_SECRETS = "1"
        $env:IMMOAPP_SECRETS_REQUIRED = "0"
        $env:IMMOAPP_SKIP_CELERY_APP = "1"
        if (-not $env:POSTGRES_HOST) { $env:POSTGRES_HOST = "127.0.0.1" }
        if (-not $env:POSTGRES_PORT) { $env:POSTGRES_PORT = "5432" }
        if (-not $env:POSTGRES_DB) { $env:POSTGRES_DB = "immoapp" }
        if (-not $env:POSTGRES_USER) { $env:POSTGRES_USER = "immoapp_app" }
        if (-not $env:POSTGRES_ADMIN_USER) { $env:POSTGRES_ADMIN_USER = "immoapp" }

        & $serverPython "scripts/perf/perf_seed_multitenant.py" @Args
        if ($LASTEXITCODE -ne 0) {
            throw "Perf seeder failed."
        }
    }
    finally {
        foreach ($entry in $original.GetEnumerator()) {
            if ($null -eq $entry.Value) {
                Remove-Item -Path ("Env:{0}" -f $entry.Key) -ErrorAction SilentlyContinue
            }
            else {
                Set-Item -Path ("Env:{0}" -f $entry.Key) -Value ([string]$entry.Value)
            }
        }
    }
}

function Invoke-Compose {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Args
    )
    & docker compose @composeArgs @Args
    if ($LASTEXITCODE -ne 0) {
        throw "docker compose failed: $($Args -join ' ')"
    }
}

function Wait-WebReadiness {
    param(
        [int]$TimeoutSeconds = 300
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $port = if ($env:WEB_PORT) { [string]$env:WEB_PORT } else { "8000" }
    $baseUrl = "http://127.0.0.1:{0}" -f $port
    $readyUrl = "$baseUrl/api/v1/health/ready/"

    while ((Get-Date) -lt $deadline) {
        try {
            $resp = Invoke-RestMethod -Method Get -Uri $readyUrl -TimeoutSec 5
            if ($resp.ready -eq $true) {
                return $baseUrl
            }
        }
        catch {
            Start-Sleep -Seconds 2
            continue
        }
        Start-Sleep -Seconds 2
    }
    throw "Web readiness timed out after $TimeoutSeconds seconds."
}

function Ensure-DatabaseSchema {
    Write-Host "[perf] applying database migrations (idempotent)" -ForegroundColor DarkGray
    Invoke-Compose -Args @("exec", "-T", "web", "python", "server/manage.py", "immoapp_db_prepare")
}

function Clear-PerfBrokerQueues {
    Write-Host "[perf] purging broker work queues for deterministic run" -ForegroundColor DarkGray
    Invoke-Compose -Args @(
        "exec", "-T", "rabbitmq", "sh", "-ec",
        'for q in default maintenance rebuild_batch match_pairs celery; do rabbitmqctl purge_queue "$q" >/dev/null 2>&1 || true; done'
    )
}

function Get-MetricValues {
    param(
        [Parameter(Mandatory = $true)]
        [object]$Summary,
        [Parameter(Mandatory = $true)]
        [string]$MetricName
    )
    $prop = $Summary.metrics.PSObject.Properties | Where-Object { $_.Name -eq $MetricName } | Select-Object -First 1
    if ($null -eq $prop) {
        return $null
    }
    $metric = $prop.Value
    if ($null -eq $metric) {
        return $null
    }
    $valuesProp = $metric.PSObject.Properties | Where-Object { $_.Name -eq "values" } | Select-Object -First 1
    if ($null -eq $valuesProp) {
        return $metric
    }
    return $valuesProp.Value
}

function Convert-PerfReportToJson {
    param(
        [Parameter(Mandatory = $true)]
        [hashtable]$Report
    )
    return ($Report | ConvertTo-Json -Depth 10)
}

function Get-MetricStatValue {
    param(
        [Parameter(Mandatory = $false)]
        [object]$MetricValues,
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [double]$Default = 0.0
    )
    if ($null -eq $MetricValues) {
        return $Default
    }
    $prop = $MetricValues.PSObject.Properties | Where-Object { $_.Name -eq $Name } | Select-Object -First 1
    if ($null -eq $prop) {
        return $Default
    }
    try {
        return [double]$prop.Value
    }
    catch {
        return $Default
    }
}

function Get-RateMetricValue {
    param(
        [Parameter(Mandatory = $false)]
        [object]$MetricValues
    )
    if ($null -eq $MetricValues) {
        return 0.0
    }
    $rate = Get-MetricStatValue -MetricValues $MetricValues -Name "rate" -Default -1.0
    if ($rate -ge 0.0) {
        return $rate
    }
    $value = Get-MetricStatValue -MetricValues $MetricValues -Name "value" -Default -1.0
    if ($value -ge 0.0 -and $value -le 1.0) {
        return $value
    }
    $passes = Get-MetricStatValue -MetricValues $MetricValues -Name "passes" -Default 0.0
    $fails = Get-MetricStatValue -MetricValues $MetricValues -Name "fails" -Default 0.0
    $total = $passes + $fails
    if ($total -le 0.0) {
        return 0.0
    }
    return ($fails / $total)
}

function Get-EndpointLatencyMetrics {
    param(
        [Parameter(Mandatory = $true)]
        [object]$Summary
    )
    $metricByEndpoint = @{
        clients = "read_clients_duration"
        listings = "read_listings_duration"
        users = "read_users_duration"
        invites = "read_invites_duration"
        notifications = "read_notifications_duration"
    }
    $result = @{}
    foreach ($entry in $metricByEndpoint.GetEnumerator()) {
        $values = Get-MetricValues -Summary $Summary -MetricName ([string]$entry.Value)
        if ($null -eq $values) {
            continue
        }
        $result[[string]$entry.Key] = @{
            avg_ms = Get-MetricStatValue -MetricValues $values -Name "avg" -Default 0.0
            p95_ms = Get-MetricStatValue -MetricValues $values -Name "p(95)" -Default 0.0
            p99_ms = Get-MetricStatValue -MetricValues $values -Name "p(99)" -Default 0.0
            max_ms = Get-MetricStatValue -MetricValues $values -Name "max" -Default 0.0
        }
    }
    return $result
}

function Get-StatusCounterBreakdown {
    param(
        [Parameter(Mandatory = $true)]
        [object]$Summary,
        [Parameter(Mandatory = $true)]
        [string]$MetricPrefix
    )
    $result = @{}
    $pattern = [regex]::new("^" + [regex]::Escape($MetricPrefix) + "\{status:(\d+)\}$")
    foreach ($prop in $Summary.metrics.PSObject.Properties) {
        $name = [string]$prop.Name
        $match = $pattern.Match($name)
        if (-not $match.Success) {
            continue
        }
        $status = $match.Groups[1].Value
        $values = $null
        $metric = $prop.Value
        if ($null -ne $metric) {
            $valuesProp = $metric.PSObject.Properties | Where-Object { $_.Name -eq "values" } | Select-Object -First 1
            if ($null -ne $valuesProp) {
                $values = $valuesProp.Value
            }
            else {
                $values = $metric
            }
        }
        $count = Get-MetricStatValue -MetricValues $values -Name "count" -Default 0.0
        $result[$status] = [int][Math]::Round($count, 0)
    }
    return $result
}

function Restore-ExplicitPerfOverrides {
    param(
        [Parameter(Mandatory = $true)]
        [hashtable]$Bound
    )
    $keys = @(
        "Tenants",
        "RowsPerTenant",
        "ActiveManagers",
        "ActiveOwners",
        "ReadRate",
        "ReadPreAllocatedVUs",
        "ReadMaxVUs",
        "RebuildVUs",
        "Duration",
        "AuthRetryMax",
        "AuthRetrySleepSec",
        "K6SetupTimeout",
        "SkipWarmupReadCache",
        "ReadP95Ms",
        "ReadP99Ms",
        "HttpFailedRate",
        "DbLatencyMs",
        "DbJitterMs",
        "DbDownstreamBandwidthKbps",
        "RabbitLatencyMs",
        "RabbitJitterMs"
    )
    foreach ($key in $keys) {
        if ($Bound.ContainsKey($key)) {
            Set-Variable -Name $key -Value $Bound[$key] -Scope Script
        }
    }
}

if ($Profile -ne "custom") {
    Apply-PerfProfile -Name $Profile
    Restore-ExplicitPerfOverrides -Bound $PSBoundParameters
}
Set-PerfRuntimeToxiproxyEnv

Write-Host "[perf] starting production-like perf pass (tag=$Tag profile=$Profile)" -ForegroundColor Cyan
Write-Host ("[perf] load profile: tenants={0} rows_per_tenant={1} read_rate={2}/s duration={3} rebuild_vus={4} active_managers={5} active_owners={6}" -f $Tenants, $RowsPerTenant, $ReadRate, $Duration, $RebuildVUs, $ActiveManagers, $ActiveOwners) -ForegroundColor DarkGray
Write-Host ("[perf] network profile: db_latency={0}ms db_jitter={1}ms db_bandwidth={2}kbps rabbit_latency={3}ms rabbit_jitter={4}ms" -f $DbLatencyMs, $DbJitterMs, $DbDownstreamBandwidthKbps, $RabbitLatencyMs, $RabbitJitterMs) -ForegroundColor DarkGray

$runtimeEnvFile = if ($env:IMMOAPP_RUNTIME_ENV_FILE) {
    [string]$env:IMMOAPP_RUNTIME_ENV_FILE
}
else {
    "C:/ProgramData/ImmoApp/config/.env.local"
}
Import-PerfEnvFile -Path $runtimeEnvFile
Set-DefaultPerfSecretsIfMissing
Assert-RequiredEnv -Names @("POSTGRES_ADMIN_PASSWORD", "POSTGRES_PASSWORD", "RABBITMQ_PASSWORD")

$startedStack = $false
$k6RunFailed = $false
$k6FailureMessage = ""
try {
    try {
        Invoke-Compose -Args @("down", "--remove-orphans")
    }
    catch {
        Write-Warning "Initial compose down failed: $($_.Exception.Message)"
    }

    $bootServices = @(
        "db", "rabbitmq", "valkey",
        "openbao", "openbao-init", "openbao-seed",
        "minio", "minio-init", "clamav",
        "app-data-init",
        "toxiproxy", "toxiproxy-init"
    )
    $bootArgs = @("up", "-d")
    $bootArgs += "--yes"
    if ($Build) {
        $bootArgs += "--build"
    }
    $bootArgs += $bootServices
    Invoke-Compose -Args $bootArgs

    $runtimeServices = @("web", "worker", "worker-rebuild", "worker-match", "beat")
    $runtimeArgs = @("up", "-d")
    $runtimeArgs += "--yes"
    if ($Build) {
        $runtimeArgs += "--build"
    }
    $runtimeArgs += $runtimeServices
    Invoke-Compose -Args $runtimeArgs
    $startedStack = $true

    $baseUrl = Wait-WebReadiness -TimeoutSeconds 420
    Write-Host "[perf] web is ready at $baseUrl" -ForegroundColor Green
    Ensure-DatabaseSchema
    Clear-PerfBrokerQueues

    if (-not $KeepData) {
        Write-Host "[perf] cleaning existing PERF_* seed data for deterministic run" -ForegroundColor DarkGray
        Invoke-PerfSeeder -Args @("--cleanup-all")
    }

    Write-Host "[perf] seeding $Tenants tenants x $RowsPerTenant rows" -ForegroundColor Yellow
    Invoke-PerfSeeder -Args @(
        "--tag", $Tag,
        "--tenants", "$Tenants",
        "--rows-per-tenant", "$RowsPerTenant",
        "--output-file", $seedFile
    )
    Clear-PerfBrokerQueues

    Write-Host "[perf] running k6 mixed workload (read + contention)" -ForegroundColor Yellow
    $defaultActiveManagers = [Math]::Min([Math]::Max($Tenants, 1), 60)
    $defaultActiveOwners = [Math]::Min([Math]::Max($Tenants, 1), 10)
    $activeManagers = if ($ActiveManagers -gt 0) {
        [Math]::Min([Math]::Max($Tenants, 1), $ActiveManagers)
    }
    else {
        $defaultActiveManagers
    }
    $activeOwners = if ($ActiveOwners -gt 0) {
        [Math]::Min([Math]::Max($Tenants, 1), $ActiveOwners)
    }
    else {
        $defaultActiveOwners
    }
    $warmupReadCache = if ($SkipWarmupReadCache -or $activeManagers -gt 80) { "0" } else { "1" }
    if (-not $PSBoundParameters.ContainsKey("K6SetupTimeout") -and $warmupReadCache -eq "1" -and $activeManagers -ge 40) {
        $K6SetupTimeout = "300s"
    }
    Write-Host ("[perf] setup profile: auth_retry_max={0} auth_retry_sleep={1}s setup_timeout={2} warmup_read_cache={3}" -f $AuthRetryMax, $AuthRetrySleepSec, $K6SetupTimeout, $warmupReadCache) -ForegroundColor DarkGray
    try {
        Invoke-Compose -Args @(
            "run", "--rm", "--no-deps",
            "-e", "PERF_BASE_URL=http://web:8000",
            "-e", "PERF_USERS_FILE=/perf_outputs/$seedFileName",
            "-e", "PERF_SUMMARY_FILE=/perf_outputs/$summaryFileName",
            "-e", "PERF_ACTIVE_MANAGERS=$activeManagers",
            "-e", "PERF_ACTIVE_OWNERS=$activeOwners",
            "-e", "PERF_AUTH_RETRY_MAX=$AuthRetryMax",
            "-e", "PERF_AUTH_RETRY_SLEEP_SEC=$AuthRetrySleepSec",
            "-e", "PERF_SETUP_TIMEOUT=$K6SetupTimeout",
            "-e", "PERF_WARMUP_READ_CACHE=$warmupReadCache",
            "-e", "PERF_DURATION=$Duration",
            "-e", "PERF_READ_RATE=$ReadRate",
            "-e", "PERF_READ_PREALLOCATED_VUS=$ReadPreAllocatedVUs",
            "-e", "PERF_READ_MAX_VUS=$ReadMaxVUs",
            "-e", "PERF_REBUILD_VUS=$RebuildVUs",
            "-e", "PERF_READ_P95_MS=$ReadP95Ms",
            "-e", "PERF_READ_P99_MS=$ReadP99Ms",
            "-e", "PERF_HTTP_FAILED_RATE=$HttpFailedRate",
            "-e", "K6_SUMMARY_TREND_STATS=avg,min,med,max,p(90),p(95),p(99)",
            "k6",
            "run", "/perf/k6_api_mix.js"
        )
    }
    catch {
        $k6RunFailed = $true
        $k6FailureMessage = [string]$_.Exception.Message
        Write-Warning "k6 run returned non-zero exit; collecting metrics and report anyway."
    }

    $seedJson = Get-Content -Path $seedFile -Raw | ConvertFrom-Json
    $superUser = $seedJson.superuser
    if ($null -eq $superUser) {
        throw "Seed payload does not include superuser credentials."
    }

    $latencyError = ""
    $latencyResp = @{
        total = 0
        window_seconds = 0
        items = @()
    }
    try {
        $tokenBody = @{
            username = [string]$superUser.username
            password = [string]$superUser.password
        } | ConvertTo-Json
        $tokenResp = Invoke-RestMethod -Method Post -Uri "$baseUrl/api/auth/token/" -Body $tokenBody -ContentType "application/json" -TimeoutSec 20
        $accessToken = [string]$tokenResp.access
        if (-not $accessToken) {
            throw "Failed to fetch access token for meta latency snapshot."
        }
        $latencyResp = Invoke-RestMethod -Method Get -Uri "$baseUrl/api/v1/meta/latency/?limit=50" -Headers @{ Authorization = "Bearer $accessToken" } -TimeoutSec 20
    }
    catch {
        $latencyError = [string]$_.Exception.Message
        Write-Warning "Latency snapshot endpoint unavailable: $latencyError"
    }
    @{
        total = $latencyResp.total
        window_seconds = $latencyResp.window_seconds
        items = $latencyResp.items
        error = $latencyError
    } | ConvertTo-Json -Depth 10 | Set-Content -Path $latencyFile -Encoding UTF8

    if (-not (Test-Path $summaryFile)) {
        throw "k6 summary file was not generated: $summaryFile"
    }
    $summaryJson = Get-Content -Path $summaryFile -Raw | ConvertFrom-Json
    if ($summaryJson.PSObject.Properties.Name -contains "setup_data") {
        [void]$summaryJson.PSObject.Properties.Remove("setup_data")
        $summaryJson | ConvertTo-Json -Depth 20 | Set-Content -Path $summaryFile -Encoding UTF8
    }
    $httpValues = Get-MetricValues -Summary $summaryJson -MetricName "http_req_duration"
    $readValues = Get-MetricValues -Summary $summaryJson -MetricName "http_req_duration{kind:read}"
    $failedValues = Get-MetricValues -Summary $summaryJson -MetricName "http_req_failed"
    $readFailedValues = Get-MetricValues -Summary $summaryJson -MetricName "read_req_failed"
    $checksReadValues = Get-MetricValues -Summary $summaryJson -MetricName "checks{kind:read}"
    $checksRebuildValues = Get-MetricValues -Summary $summaryJson -MetricName "checks{kind:rebuild}"
    $endpointLatency = Get-EndpointLatencyMetrics -Summary $summaryJson
    $readStatusBreakdown = Get-StatusCounterBreakdown -Summary $summaryJson -MetricPrefix "read_status_total"
    $rebuildStatusBreakdown = Get-StatusCounterBreakdown -Summary $summaryJson -MetricPrefix "rebuild_status_total"

    $readP95 = Get-MetricStatValue -MetricValues $readValues -Name "p(95)" -Default 0.0
    $readP99 = Get-MetricStatValue -MetricValues $readValues -Name "p(99)" -Default 0.0
    $failedRate = Get-RateMetricValue -MetricValues $readFailedValues
    $globalFailedRate = Get-RateMetricValue -MetricValues $failedValues

    $report = @{
        tag = $Tag
        profile = $Profile
        tenants = $Tenants
        rows_per_tenant = $RowsPerTenant
        duration = $Duration
        contention_profile = @{
            db_latency_ms = $DbLatencyMs
            db_jitter_ms = $DbJitterMs
            db_downstream_bandwidth_kbps = $DbDownstreamBandwidthKbps
            rabbit_latency_ms = $RabbitLatencyMs
            rabbit_jitter_ms = $RabbitJitterMs
        }
        k6 = @{
            http_req_duration = $httpValues
            http_req_duration_read = $readValues
            http_req_failed = $failedValues
            read_req_failed = $readFailedValues
            checks_read = $checksReadValues
            checks_rebuild = $checksRebuildValues
            read_endpoint_latency = $endpointLatency
            read_status_counts = $readStatusBreakdown
            rebuild_status_counts = $rebuildStatusBreakdown
            active_manager_tokens_target = $activeManagers
            active_owner_tokens_target = $activeOwners
            summary_file = $summaryFile
        }
        slo = @{
            read_p95_ms = @{
                value = $readP95
                budget = $ReadP95Ms
                pass = ($readP95 -le $ReadP95Ms)
            }
            read_p99_ms = @{
                value = $readP99
                budget = $ReadP99Ms
                pass = ($readP99 -le $ReadP99Ms)
            }
            http_failed_rate = @{
                value = $failedRate
                budget = $HttpFailedRate
                pass = ($failedRate -le $HttpFailedRate)
            }
            global_http_failed_rate = @{
                value = $globalFailedRate
            }
        }
        backend_latency_rollups = @{
            total = $latencyResp.total
            window_seconds = $latencyResp.window_seconds
            items = $latencyResp.items
            snapshot_file = $latencyFile
            error = $latencyError
        }
        k6_run_failed = $k6RunFailed
        k6_failure_message = $k6FailureMessage
        generated_at_utc = (Get-Date).ToUniversalTime().ToString("o")
    }

    Convert-PerfReportToJson -Report $report | Set-Content -Path $reportFile -Encoding UTF8

    Write-Host ""
    Write-Host "[perf] RESULT" -ForegroundColor Cyan
    Write-Host ("  read p95: {0} ms" -f $readP95)
    Write-Host ("  read p99: {0} ms" -f $readP99)
    Write-Host ("  read failed rate: {0}" -f $failedRate)
    Write-Host ("  global http failed rate: {0}" -f $globalFailedRate)
    Write-Host ("  p95 budget pass: {0}" -f ($readP95 -le $ReadP95Ms))
    Write-Host ("  p99 budget pass: {0}" -f ($readP99 -le $ReadP99Ms))
    Write-Host ("  failed-rate budget pass: {0}" -f ($failedRate -le $HttpFailedRate))
    foreach ($entry in $endpointLatency.GetEnumerator() | Sort-Object Name) {
        $values = $entry.Value
        Write-Host ("  endpoint[{0}] p95={1}ms p99={2}ms avg={3}ms" -f $entry.Key, $values.p95_ms, $values.p99_ms, $values.avg_ms)
    }
    if ($readStatusBreakdown.Count -gt 0) {
        Write-Host ("  read status counts: {0}" -f (($readStatusBreakdown.GetEnumerator() | Sort-Object Name | ForEach-Object { '{0}={1}' -f $_.Name, $_.Value }) -join ", "))
    }
    if ($rebuildStatusBreakdown.Count -gt 0) {
        Write-Host ("  rebuild status counts: {0}" -f (($rebuildStatusBreakdown.GetEnumerator() | Sort-Object Name | ForEach-Object { '{0}={1}' -f $_.Name, $_.Value }) -join ", "))
    }
    Write-Host ("  k6 summary: {0}" -f $summaryFile)
    Write-Host ("  backend rollups: {0}" -f $latencyFile)
    Write-Host ("  merged report: {0}" -f $reportFile)

    if ($k6RunFailed) {
        throw "k6 run failed threshold/policy gates. See report: $reportFile"
    }
}
finally {
    if (-not $KeepData -and $startedStack) {
        try {
            Write-Host "[perf] cleaning seeded perf data (tag=$Tag)" -ForegroundColor DarkGray
            Invoke-PerfSeeder -Args @("--cleanup", "--tag", $Tag)
        }
        catch {
            Write-Warning "Perf cleanup failed: $($_.Exception.Message)"
        }
    }
    if (-not $KeepStack -and $startedStack) {
        try {
            Write-Host "[perf] stopping perf stack services" -ForegroundColor DarkGray
            Invoke-Compose -Args @("stop", "web", "worker", "worker-rebuild", "worker-match", "beat", "toxiproxy")
        }
        catch {
            Write-Warning "Perf stack stop failed: $($_.Exception.Message)"
        }
    }
}
