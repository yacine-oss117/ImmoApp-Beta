param(
    [int]$DurationHours = 6,
    [int]$Tenants = 200,
    [int]$RowsPerTenant = 500,
    [int]$ReadRate = 60,
    [int]$ReadPreAllocatedVUs = 60,
    [int]$ReadMaxVUs = 240,
    [int]$RebuildVUs = 2,
    [string]$BaseUrl = "http://127.0.0.1:8000",
    [string]$Tag = "",
    [string]$OutputDir = "scripts/perf_outputs",
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
    $Tag = "soak_" + (Get-Date -Format "yyyyMMddHHmmss")
}

$outputRoot = Join-Path $repoRoot $OutputDir
New-Item -ItemType Directory -Force -Path $outputRoot | Out-Null
$seedFile = Join-Path $outputRoot ("perf_users_{0}.json" -f $Tag)
$healthFile = Join-Path $outputRoot ("soak_match_health_{0}.jsonl" -f $Tag)
$pulseFile = Join-Path $outputRoot ("soak_match_pulses_{0}.jsonl" -f $Tag)
$countFile = Join-Path $outputRoot ("soak_count_checks_{0}.jsonl" -f $Tag)
$summaryFile = Join-Path $outputRoot ("k6_summary_{0}.json" -f $Tag)
$reportFile = Join-Path $outputRoot ("soak_report_{0}.json" -f $Tag)

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

function Test-FreeSpaceGb {
    param([Parameter(Mandatory = $true)][double]$MinimumGb)
    $drive = Get-PSDrive -Name ((Get-Location).Drive.Name)
    $freeGb = [math]::Round($drive.Free / 1GB, 2)
    if ($freeGb -lt $MinimumGb) {
        throw "Insufficient disk space. Required ${MinimumGb}GB, found ${freeGb}GB."
    }
    return $freeGb
}

function Invoke-ComposeProd {
    param([Parameter(Mandatory = $true)][string[]]$Args)
    $composeArgs = Get-ImmoAppComposeArgs -Names @("compose.yml", "compose.prod.yml")
    & docker compose @(Get-ImmoAppComposeProjectArgs) @composeArgs @Args
    if ($LASTEXITCODE -ne 0) {
        throw "docker compose failed: $($Args -join ' ')"
    }
}

function Invoke-PerfSeeder {
    param([Parameter(Mandatory = $true)][string[]]$Args)
    $serverPython = Get-ServerPythonPath
    $env:DJANGO_SETTINGS_MODULE = "server.immoapp_server.settings"
    $env:DJANGO_DEBUG = "1"
    $env:IMMOAPP_SECRETS_BACKEND = "env"
    $env:IMMOAPP_ALLOW_ENV_SECRETS = "1"
    $env:IMMOAPP_SECRETS_REQUIRED = "0"
    $env:IMMOAPP_SKIP_CELERY_APP = "1"
    if (-not $env:POSTGRES_HOST) { $env:POSTGRES_HOST = "127.0.0.1" }
    if (-not $env:POSTGRES_PORT) { $env:POSTGRES_PORT = "5432" }
    if (-not $env:POSTGRES_DB) { $env:POSTGRES_DB = "immoapp" }
    if (-not $env:POSTGRES_USER) { $env:POSTGRES_USER = "immoapp_app" }
    & $serverPython "scripts/perf/perf_seed_multitenant.py" @Args
    if ($LASTEXITCODE -ne 0) {
        throw "Perf seeder failed."
    }
}

function Get-AuthToken {
    param([Parameter(Mandatory = $true)][string]$UsersFile)
    $payload = Get-Content $UsersFile -Raw | ConvertFrom-Json
    $superUser = $payload.superuser
    $body = @{
        username = [string]$superUser.username
        password = [string]$superUser.password
    } | ConvertTo-Json -Compress
    $tokenResp = Invoke-RestMethod -Method Post -Uri "$BaseUrl/api/auth/token/" -Body $body -ContentType "application/json" -TimeoutSec 30
    if (-not $tokenResp.access) {
        throw "Failed to fetch access token."
    }
    return [string]$tokenResp.access
}

function Get-PulseAgencyIds {
    param(
        [Parameter(Mandatory = $true)][string]$UsersFile,
        [Parameter(Mandatory = $true)][int]$Limit
    )
    $payload = Get-Content $UsersFile -Raw | ConvertFrom-Json
    $agencyIds = @()
    foreach ($entry in @($payload.owners) + @($payload.managers) + @($payload.agents)) {
        $agencyId = $entry.agency_id
        if ($null -ne $agencyId) {
            $agencyIds += [int]$agencyId
        }
    }
    return @($agencyIds | Sort-Object -Unique | Select-Object -First $Limit)
}

function Get-SampledClientIds {
    param(
        [Parameter(Mandatory = $true)][int[]]$AgencyIds,
        [Parameter(Mandatory = $true)][int]$PulseNumber,
        [Parameter(Mandatory = $true)][int]$Limit
    )
    $serverPython = Get-ServerPythonPath
    $agencyCsv = ($AgencyIds | ForEach-Object { [string]$_ }) -join ","
    $script = @"
import json
import os
import random
import sys
from pathlib import Path
repo_root = Path(r'$repoRoot')
sys.path.insert(0, str(repo_root))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'server.immoapp_server.settings')
import django
django.setup()
from server.pg.uow import admin_transaction
agency_ids = [int(v) for v in '$agencyCsv'.split(',') if v]
pulse = int('$PulseNumber')
limit = int('$Limit')
output = {}
with admin_transaction() as session:
    for agency_id in agency_ids:
        rows = session.execute(
            """
            SELECT id
            FROM clients
            WHERE agency_id = %s
              AND status = 'active'
              AND deleted_at IS NULL
            ORDER BY id
            """,
            (agency_id,),
        ).fetchall()
        ids = [int(row['id'] if isinstance(row, dict) else row[0]) for row in rows]
        rng = random.Random(f"{agency_id}:{pulse}")
        if len(ids) > limit:
            ids = sorted(rng.sample(ids, limit))
        output[str(agency_id)] = ids
print(json.dumps(output))
"@
    $json = $script | & $serverPython -
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to sample client ids for count integrity check."
    }
    return $json | ConvertFrom-Json -AsHashtable
}

function Invoke-CountIntegritySpotCheck {
    param(
        [Parameter(Mandatory = $true)][string]$Token,
        [Parameter(Mandatory = $true)][hashtable]$ClientMap,
        [Parameter(Mandatory = $true)][int]$PulseNumber,
        [Parameter(Mandatory = $true)][string]$Profile
    )
    $headers = @{ Authorization = "Bearer $Token" }
    foreach ($agencyId in $ClientMap.Keys) {
        $clientIds = @($ClientMap[$agencyId])
        if (-not $clientIds.Count) { continue }
        $deadline = (Get-Date).AddSeconds(60)
        do {
            $payload = @{ ids = $clientIds } | ConvertTo-Json -Compress
            $cached = Invoke-RestMethod -Method Post -Uri "$BaseUrl/api/v1/cache/match/get/" -Headers $headers -Body $payload -ContentType "application/json" -TimeoutSec 30
            $direct = Invoke-RestMethod -Method Post -Uri "$BaseUrl/api/v1/matches/clients/counts/" -Headers $headers -Body $payload -ContentType "application/json" -TimeoutSec 30
            $mismatches = @()
            foreach ($clientId in $clientIds) {
                $cachedCount = 0
                $directCount = 0
                if ($cached.counts.PSObject.Properties.Name -contains [string]$clientId) { $cachedCount = [int]$cached.counts.([string]$clientId) }
                if ($direct.counts.PSObject.Properties.Name -contains [string]$clientId) { $directCount = [int]$direct.counts.([string]$clientId) }
                if ($cachedCount -ne $directCount) {
                    $mismatches += [pscustomobject]@{
                        ok = $false
                        checked_at = (Get-Date).ToUniversalTime().ToString("o")
                        agency_id = [int]$agencyId
                        pulse_number = $PulseNumber
                        client_id = [int]$clientId
                        cached_count = $cachedCount
                        direct_count = $directCount
                        settle_seconds = [int]([timespan]((Get-Date) - $deadline.AddSeconds(-60))).TotalSeconds
                        profile = $Profile
                    }
                }
            }
            if (-not $mismatches.Count) {
                [pscustomobject]@{
                    ok = $true
                    checked_at = (Get-Date).ToUniversalTime().ToString("o")
                    agency_id = [int]$agencyId
                    pulse_number = $PulseNumber
                    checked_clients = $clientIds.Count
                    settle_seconds = [int]([timespan]((Get-Date) - $deadline.AddSeconds(-60))).TotalSeconds
                    profile = $Profile
                } | ConvertTo-Json -Compress | Add-Content -Path $countFile
                break
            }
            if ((Get-Date) -ge $deadline) {
                foreach ($mismatch in $mismatches) {
                    $mismatch | ConvertTo-Json -Compress | Add-Content -Path $countFile
                }
                break
            }
            Start-Sleep -Seconds 5
        } while ($true)
    }
}

function Invoke-HealthSample {
    param([Parameter(Mandatory = $true)][string]$Token)
    $serverPython = Get-ServerPythonPath
    & $serverPython scripts/perf/collect_pg_match_health.py --mode api --base-url $BaseUrl --token $Token --output $healthFile --jsonl | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "Health sample collection failed"
    }
}

function Invoke-ComputePulse {
    param([Parameter(Mandatory = $true)][string]$TagValue)
    $serverPython = Get-ServerPythonPath
    $tempPulse = Join-Path $outputRoot ("pulse_{0}_{1}.json" -f $TagValue, [guid]::NewGuid().ToString("N"))
    & $serverPython scripts/perf/perf_match_pairs_capacity.py --tag $TagValue --tenants 50 --demandes-per-tenant 250 --mode batch --demande-batch-size 250 --timeout-seconds 1800 --output-file $tempPulse | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Compute pulse failed."
    }
    Get-Content $tempPulse | Add-Content -Path $pulseFile
    $payload = Get-Content $tempPulse -Raw | ConvertFrom-Json
    Remove-Item $tempPulse -ErrorAction SilentlyContinue
    return $payload
}

function Start-SoakLoad {
    $env:BASE_URL = $BaseUrl
    $env:USERS_FILE = $seedFile
    $env:SUMMARY_FILE = $summaryFile
    $env:READ_RATE = [string]$ReadRate
    $env:READ_PREALLOCATED_VUS = [string]$ReadPreAllocatedVUs
    $env:READ_MAX_VUS = [string]$ReadMaxVUs
    $env:REBUILD_VUS = [string]$RebuildVUs
    $env:DURATION = "${DurationHours}h"
    $env:READ_P95_MS = "999999"
    $env:READ_P99_MS = "999999"
    $env:HTTP_FAILED_RATE = "1"
    Start-Process -FilePath "k6" -ArgumentList @("run", "scripts/perf/k6_api_mix.js") -NoNewWindow -PassThru
}

Test-FreeSpaceGb -MinimumGb 10 | Out-Null

if ($Build) {
    Invoke-ComposeProd -Args @("up", "-d", "--build", "--force-recreate", "web", "worker", "worker-match", "worker-rebuild", "beat")
}
else {
    Invoke-ComposeProd -Args @("up", "-d", "--force-recreate", "web", "worker", "worker-match", "worker-rebuild", "beat")
}

Invoke-PerfSeeder -Args @("--tag", $Tag, "--tenants", [string]$Tenants, "--rows-per-tenant", [string]$RowsPerTenant, "--output-file", $seedFile)
$token = Get-AuthToken -UsersFile $seedFile
$loadProcess = Start-SoakLoad

$startedAt = Get-Date
$nextHealth = Get-Date
$nextPulse = (Get-Date).AddHours(1)
$pulseNumber = 0

try {
    while (-not $loadProcess.HasExited) {
        if ((Get-Date) -ge $nextHealth) {
            Invoke-HealthSample -Token $token
            $drive = Get-PSDrive -Name ((Get-Location).Drive.Name)
            $freeGb = [math]::Round($drive.Free / 1GB, 2)
            if ($freeGb -lt 5) {
                Write-Warning "Soak free disk dropped below 5GB: ${freeGb}GB"
            }
            $nextHealth = (Get-Date).AddMinutes(5)
        }
        if ((Get-Date) -ge $nextPulse) {
            $pulseNumber += 1
            $pulse = Invoke-ComputePulse -TagValue $Tag
            $pulseAgencyIds = Get-PulseAgencyIds -UsersFile $seedFile -Limit ([Math]::Min(50, $Tenants))
            $clientMap = Get-SampledClientIds -AgencyIds $pulseAgencyIds -PulseNumber $pulseNumber -Limit 10
            Invoke-CountIntegritySpotCheck -Token $token -ClientMap $clientMap -PulseNumber $pulseNumber -Profile "auto"
            $nextPulse = (Get-Date).AddHours(1)
        }
        Start-Sleep -Seconds 5
        $loadProcess.Refresh()
    }

    $serverPython = Get-ServerPythonPath
    & $serverPython scripts/perf/compare_soak_reports.py --k6-summary $summaryFile --pulse-jsonl $pulseFile --health-jsonl $healthFile --count-jsonl $countFile --output $reportFile | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to compare soak reports."
    }
}
finally {
    if (-not $KeepData) {
        Invoke-PerfSeeder -Args @("--tag", $Tag, "--cleanup")
    }
    if (-not $KeepStack) {
        Invoke-ComposeProd -Args @("stop", "web", "worker", "worker-match", "worker-rebuild", "beat")
    }
}
