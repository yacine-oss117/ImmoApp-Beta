param(
    [string]$OutputRoot = "",
    [string]$BundleName = ""
)

$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "common.ps1")
Set-ImmoAppSecurityEnv
Import-ImmoAppEnvFile
Set-ImmoAppHubRuntimeProfileEnv
Set-ImmoAppHostRuntimeEndpoints

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)][scriptblock]$Command,
        [Parameter(Mandatory = $true)][string]$Label
    )
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$Label failed with exit code $LASTEXITCODE"
    }
}

function Get-ReleaseComposeInvocationArgs {
    $composeArgs = Get-ImmoAppComposeArgs -Names @("compose.yml")
    if (Test-ImmoAppWindowsVolumeMode) {
        $composeArgs += Get-ImmoAppComposeArgs -Names @("compose.windows.yml")
    }
    $projectArgs = Get-ImmoAppComposeProjectArgs
    return @($composeArgs + $projectArgs)
}

function Get-DbContainerId {
    $composeInvocation = Get-ReleaseComposeInvocationArgs
    $containerId = (& docker compose @composeInvocation ps -q db).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $containerId) {
        throw "Could not resolve Docker db container for pg_dump fallback."
    }
    return $containerId
}

function Invoke-DbContainer {
    param([Parameter(Mandatory = $true)][string[]]$DbArgs)
    $composeInvocation = Get-ReleaseComposeInvocationArgs
    Invoke-Checked -Label "Docker db command" -Command {
        & docker compose @composeInvocation exec -T db @DbArgs
    }
}

function Invoke-MinioClient {
    param([Parameter(Mandatory = $true)][string]$ShellCommand)
    $composeInvocation = Get-ReleaseComposeInvocationArgs
    Invoke-Checked -Label "MinIO object mirror" -Command {
        & docker compose @composeInvocation run --rm --no-deps --entrypoint sh `
            --env IMMOAPP_RELEASE_MINIO_USER --env IMMOAPP_RELEASE_MINIO_PASSWORD `
            -v "${bundleRoot}:/backup" minio-init -c $ShellCommand
    }
}

function Quote-ShSingle {
    param([Parameter(Mandatory = $true)][string]$Value)
    $single = [string][char]39
    $double = [string][char]34
    return $single + $Value.Replace($single, "$single$double$single$double$single") + $single
}

function Assert-ReleaseBucketName {
    param([Parameter(Mandatory = $true)][string]$BucketName)
    if ($BucketName -notmatch '^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$') {
        throw "Invalid release source bucket name: $BucketName"
    }
}

function Invoke-ReleaseIntegrityCheck {
    param([Parameter(Mandatory = $true)][string]$JsonOut)

    $serverPython = Get-ImmoAppVenvPython -Kind server
    if (-not (Test-Path $serverPython)) {
        throw "Server venv python not found at $serverPython"
    }
    & $serverPython (Join-Path (Get-ImmoAppRepoRoot) "scripts\verify_release_backup_integrity.py") --json-out $JsonOut
    if ($LASTEXITCODE -ne 0) {
        throw "Release backup refused: database integrity check failed. Run explicit local-dev repair/reset or fix production data first."
    }
}

function Backup-DatabaseDump {
    param(
        [Parameter(Mandatory = $true)][string]$TargetPath
    )
    if (Get-Command pg_dump -ErrorAction SilentlyContinue) {
        $env:PGPASSWORD = $dbPass
        try {
            Invoke-Checked -Label "pg_dump" -Command { & pg_dump -h $dbHost -p $dbPort -U $dbUser -d $dbName -Fc -f $TargetPath }
        }
        finally {
            $env:PGPASSWORD = $null
        }
        return
    }

    $containerDumpPath = "/tmp/immoapp_release_backup.dump"
    Invoke-DbContainer -DbArgs @("pg_dump", "-U", $dbUser, "-d", $dbName, "-Fc", "-f", $containerDumpPath)
    $dbContainer = Get-DbContainerId
    Invoke-Checked -Label "docker cp database dump" -Command {
        & docker cp "${dbContainer}:$containerDumpPath" $TargetPath
    }
    Invoke-DbContainer -DbArgs @("rm", "-f", $containerDumpPath)
}

$paths = Get-ImmoAppRuntimePaths
if (-not $OutputRoot) {
    $OutputRoot = $paths.BackupsRoot
}
if (-not $BundleName) {
    $BundleName = "release_" + (Get-Date -Format "yyyyMMdd_HHmmss")
}
if ($BundleName -notmatch '^[A-Za-z0-9_.-]+$' -or $BundleName.Contains("..")) {
    throw "Invalid release bundle name: $BundleName"
}
if (-not (Test-Path $OutputRoot)) {
    New-Item -ItemType Directory -Path $OutputRoot | Out-Null
}
$existingBundleDir = Join-Path $OutputRoot $BundleName
$zipPath = Join-Path $OutputRoot "$BundleName.zip"
if (Test-Path $existingBundleDir) {
    throw "Release backup refused: bundle work directory already exists: $existingBundleDir"
}
if (Test-Path $zipPath) {
    throw "Release backup refused: bundle zip already exists: $zipPath"
}

$integrityTempRoot = Join-Path $paths.TmpRoot ("release_backup_integrity_" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $integrityTempRoot | Out-Null
$integrityTempReport = Join-Path $integrityTempRoot "release_backup_integrity.json"
try {
    Invoke-ReleaseIntegrityCheck -JsonOut $integrityTempReport
}
catch {
    if (Test-Path $integrityTempRoot) {
        Remove-Item -LiteralPath $integrityTempRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
    throw
}

$bundleRoot = Join-Path $OutputRoot (".rb_" + [Guid]::NewGuid().ToString("N").Substring(0, 8))
$dbDir = Join-Path $bundleRoot "database"
$objectDir = Join-Path $bundleRoot "minio"
$integrityDir = Join-Path $bundleRoot "integrity"
try {
    New-Item -ItemType Directory -Path $dbDir, $objectDir, $integrityDir | Out-Null
    Copy-Item -LiteralPath $integrityTempReport -Destination (Join-Path $integrityDir "release_backup_integrity.json")
    if (Test-Path $integrityTempRoot) {
        Remove-Item -LiteralPath $integrityTempRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
    $bundleRootResolved = (Resolve-Path -LiteralPath $bundleRoot).Path

    $dbName = $env:POSTGRES_DB
    $dbUser = $env:POSTGRES_ADMIN_USER
    $dbPass = $env:POSTGRES_ADMIN_PASSWORD
    $dbHost = if ($env:POSTGRES_HOST) { $env:POSTGRES_HOST } else { "127.0.0.1" }
    $dbPort = if ($env:POSTGRES_PORT) { $env:POSTGRES_PORT } else { "5432" }
    $bucket = if ($env:STORAGE_BUCKET) { $env:STORAGE_BUCKET } else { "immoapp" }
    $minioUser = if ($env:MINIO_ROOT_USER) { $env:MINIO_ROOT_USER } elseif ($env:STORAGE_ACCESS_KEY) { $env:STORAGE_ACCESS_KEY } else { "immoapp" }
    $minioPass = if ($env:MINIO_ROOT_PASSWORD) { $env:MINIO_ROOT_PASSWORD } elseif ($env:STORAGE_SECRET_KEY) { $env:STORAGE_SECRET_KEY } else { "" }
    Assert-ReleaseBucketName -BucketName $bucket

    if (-not $dbName -or -not $dbUser -or -not $dbPass) {
        throw "POSTGRES_DB / POSTGRES_ADMIN_USER / POSTGRES_ADMIN_PASSWORD are required."
    }
    if (-not $minioPass) {
        throw "MINIO_ROOT_PASSWORD or STORAGE_SECRET_KEY is required for release bundle object backup."
    }

    $dumpPath = Join-Path $dbDir "immoapp.dump"
    Backup-DatabaseDump -TargetPath $dumpPath

    $oldMinioUser = $env:IMMOAPP_RELEASE_MINIO_USER
    $oldMinioPassword = $env:IMMOAPP_RELEASE_MINIO_PASSWORD
    $env:IMMOAPP_RELEASE_MINIO_USER = $minioUser
    $env:IMMOAPP_RELEASE_MINIO_PASSWORD = $minioPass
    $mirrorCommand = "mc alias set release http://minio:9000 " + '"$IMMOAPP_RELEASE_MINIO_USER" "$IMMOAPP_RELEASE_MINIO_PASSWORD"' +
        " && mkdir -p /backup/minio && mc mirror --overwrite " + (Quote-ShSingle "release/$bucket") + " " + (Quote-ShSingle "/backup/minio/$bucket")
    try {
        Invoke-MinioClient -ShellCommand $mirrorCommand
    }
    finally {
        if ($null -ne $oldMinioUser) { $env:IMMOAPP_RELEASE_MINIO_USER = $oldMinioUser } else { Remove-Item Env:IMMOAPP_RELEASE_MINIO_USER -ErrorAction SilentlyContinue }
        if ($null -ne $oldMinioPassword) { $env:IMMOAPP_RELEASE_MINIO_PASSWORD = $oldMinioPassword } else { Remove-Item Env:IMMOAPP_RELEASE_MINIO_PASSWORD -ErrorAction SilentlyContinue }
    }

    $files = Get-ChildItem -LiteralPath $bundleRoot -Recurse -File |
        Where-Object { $_.Name -ne "manifest.json" } |
        ForEach-Object {
            @{
                path = $_.FullName.Substring($bundleRootResolved.Length + 1).Replace("\", "/")
                bytes = $_.Length
                sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
            }
        }

    $manifest = @{
        created_at_utc = (Get-Date).ToUniversalTime().ToString("o")
        kind = "immoapp_release_backup_bundle"
        database = @{
            name = $dbName
            host = $dbHost
            port = $dbPort
            dump = "database/immoapp.dump"
        }
        object_storage = @{
            bucket = $bucket
            mirror_root = "minio/$bucket"
            tool = "mc mirror"
        }
        integrity = @{
            report = "integrity/release_backup_integrity.json"
        }
        files = @($files)
    } | ConvertTo-Json -Depth 8
    Set-Content -Path (Join-Path $bundleRoot "manifest.json") -Value $manifest -Encoding UTF8

    $serverPython = Get-ImmoAppVenvPython -Kind server
    Invoke-Checked -Label "release bundle directory manifest verification" -Command {
        & $serverPython scripts/verify_release_bundle_manifest.py --bundle-path $bundleRoot
    }
    Compress-Archive -Path (Join-Path $bundleRoot "*") -DestinationPath $zipPath
    Invoke-Checked -Label "release bundle zip manifest verification" -Command {
        & $serverPython scripts/verify_release_bundle_manifest.py --bundle-path $zipPath
    }

    Write-Host "Release backup bundle created: $zipPath" -ForegroundColor Green
}
catch {
    if (Test-Path $zipPath) {
        Remove-Item -LiteralPath $zipPath -Force -ErrorAction SilentlyContinue
    }
    throw
}
finally {
    if (Test-Path $integrityTempRoot) {
        Remove-Item -LiteralPath $integrityTempRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
    if (Test-Path $bundleRoot) {
        Remove-Item -LiteralPath $bundleRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}
