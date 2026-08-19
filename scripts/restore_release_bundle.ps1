param(
    [Parameter(Mandatory = $true)]
    [string]$BundlePath,
    [string]$RestoreDatabase = "immoapp_restore_drill",
    [switch]$SkipObjectRestore,
    [switch]$CleanupRestoreObjects
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
        throw "Could not resolve Docker db container for restore fallback."
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
    Invoke-Checked -Label "MinIO object restore" -Command {
        & docker compose @composeInvocation run --rm --no-deps --entrypoint sh `
            --env IMMOAPP_RELEASE_MINIO_USER --env IMMOAPP_RELEASE_MINIO_PASSWORD `
            -v "${restoreRoot}:/backup" minio-init -c $ShellCommand
    }
}

function Quote-ShSingle {
    param([Parameter(Mandatory = $true)][string]$Value)
    $single = [string][char]39
    $double = [string][char]34
    return $single + $Value.Replace($single, "$single$double$single$double$single") + $single
}

function New-RestoreBucketName {
    $stamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddHHmmss")
    $suffix = [Guid]::NewGuid().ToString("N").Substring(0, 8)
    return "immoapp-restore-drill-$stamp-$suffix"
}

function Assert-RestoreDrillBucketName {
    param([Parameter(Mandatory = $true)][string]$BucketName)
    if ($BucketName -notmatch '^immoapp-restore-drill-[0-9]{14}-[0-9a-f]{8}$') {
        throw "Refusing to clean up non-drill restore bucket: $BucketName"
    }
}

function Assert-RestoreDatabaseName {
    param(
        [Parameter(Mandatory = $true)][string]$DatabaseName,
        [string]$ConfiguredPrimaryDb = ""
    )
    if ([string]::IsNullOrWhiteSpace($DatabaseName)) {
        throw "RestoreDatabase is required."
    }
    if ($DatabaseName.Length -gt 63 -or $DatabaseName -cnotmatch '^[a-z][a-z0-9_]*$') {
        throw "Invalid RestoreDatabase '$DatabaseName'. Use lowercase letter first, then lowercase letters, digits, or underscore, max 63 chars."
    }
    if ($DatabaseName -cin @("postgres", "template0", "template1")) {
        throw "Refusing to restore into reserved database '$DatabaseName'."
    }
    if ($ConfiguredPrimaryDb -and $DatabaseName -eq $ConfiguredPrimaryDb.Trim().ToLowerInvariant()) {
        throw "Refusing to restore over the configured primary database. Use a clean database name."
    }
}

function Quote-SqlIdentifier {
    param([Parameter(Mandatory = $true)][string]$Identifier)
    Assert-RestoreDatabaseName -DatabaseName $Identifier
    return '"' + $Identifier + '"'
}

function Assert-ReleaseSourceBucketName {
    param([Parameter(Mandatory = $true)][string]$BucketName)
    if ($BucketName -notmatch '^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$') {
        throw "Invalid release source bucket in manifest: $BucketName"
    }
}

function Assert-ReleaseMirrorRoot {
    param(
        [Parameter(Mandatory = $true)][string]$MirrorRoot,
        [Parameter(Mandatory = $true)][string]$BucketName
    )
    if ($MirrorRoot -ne "minio/$BucketName") {
        throw "Invalid release mirror root in manifest: $MirrorRoot"
    }
}

function Restore-DatabaseDump {
    param([Parameter(Mandatory = $true)][string]$DumpPath)
    $restoreIdentifier = Quote-SqlIdentifier -Identifier $RestoreDatabase
    $hasHostTools = (Get-Command psql -ErrorAction SilentlyContinue) -and (Get-Command pg_restore -ErrorAction SilentlyContinue)
    if ($hasHostTools) {
        $env:PGPASSWORD = $dbPass
        try {
            Invoke-Checked -Label "drop restore database" -Command { & psql -h $dbHost -p $dbPort -U $dbUser -d postgres -c "DROP DATABASE IF EXISTS $restoreIdentifier;" }
            Invoke-Checked -Label "create restore database" -Command { & psql -h $dbHost -p $dbPort -U $dbUser -d postgres -c "CREATE DATABASE $restoreIdentifier;" }
            Invoke-Checked -Label "pg_restore" -Command { & pg_restore -h $dbHost -p $dbPort -U $dbUser -d $RestoreDatabase --clean --if-exists $DumpPath }
        }
        finally {
            $env:PGPASSWORD = $null
        }
        return
    }

    $dbContainer = Get-DbContainerId
    $containerDumpPath = "/tmp/immoapp_release_restore.dump"
    Invoke-Checked -Label "docker cp restore dump" -Command {
        & docker cp $DumpPath "${dbContainer}:$containerDumpPath"
    }
    Invoke-DbContainer -DbArgs @("psql", "-U", $dbUser, "-d", "postgres", "-c", "DROP DATABASE IF EXISTS $restoreIdentifier;")
    Invoke-DbContainer -DbArgs @("psql", "-U", $dbUser, "-d", "postgres", "-c", "CREATE DATABASE $restoreIdentifier;")
    Invoke-DbContainer -DbArgs @("pg_restore", "-U", $dbUser, "-d", $RestoreDatabase, "--clean", "--if-exists", $containerDumpPath)
    Invoke-DbContainer -DbArgs @("rm", "-f", $containerDumpPath)
}

if (-not (Test-Path $BundlePath)) {
    throw "Release backup bundle not found: $BundlePath"
}
if ($SkipObjectRestore.IsPresent) {
    throw "Object restore cannot be skipped for beta release proof."
}
$configuredDb = if ($env:POSTGRES_DB) { $env:POSTGRES_DB.Trim().ToLowerInvariant() } else { "" }
$RestoreDatabase = $RestoreDatabase.Trim()
Assert-RestoreDatabaseName -DatabaseName $RestoreDatabase -ConfiguredPrimaryDb $configuredDb

$paths = Get-ImmoAppRuntimePaths
$restoreRoot = Join-Path $paths.TmpRoot ("release_restore_" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $restoreRoot | Out-Null
$serverPython = Get-ImmoAppVenvPython -Kind server
if (-not (Test-Path $serverPython)) {
    throw "Server venv python not found at $serverPython"
}
$restoreBucket = New-RestoreBucketName
Assert-RestoreDrillBucketName -BucketName $restoreBucket

try {
    Invoke-Checked -Label "release bundle manifest verification" -Command {
        & $serverPython scripts/verify_release_bundle_manifest.py --bundle-path $BundlePath --extract-to $restoreRoot
    }

    $manifestPath = Join-Path $restoreRoot "manifest.json"
    $manifest = Get-Content -Path $manifestPath -Raw | ConvertFrom-Json

    $dumpPath = Join-Path $restoreRoot "database\immoapp.dump"

    $dbUser = $env:POSTGRES_ADMIN_USER
    $dbPass = $env:POSTGRES_ADMIN_PASSWORD
    $dbHost = if ($env:POSTGRES_HOST) { $env:POSTGRES_HOST } else { "127.0.0.1" }
    $dbPort = if ($env:POSTGRES_PORT) { $env:POSTGRES_PORT } else { "5432" }
    if (-not $dbUser -or -not $dbPass) {
        throw "POSTGRES_ADMIN_USER / POSTGRES_ADMIN_PASSWORD are required."
    }

    Write-Host "Release restore database: $RestoreDatabase" -ForegroundColor Yellow
    Write-Host "Release restore object bucket: $restoreBucket" -ForegroundColor Yellow
    Restore-DatabaseDump -DumpPath $dumpPath

    $bucket = [string]$manifest.object_storage.bucket
    $mirrorRootRelative = [string]$manifest.object_storage.mirror_root
    Assert-ReleaseSourceBucketName -BucketName $bucket
    Assert-ReleaseMirrorRoot -MirrorRoot $mirrorRootRelative -BucketName $bucket
    $mirrorRoot = Join-Path $restoreRoot ($mirrorRootRelative.Replace("/", "\"))
    if (-not (Test-Path $mirrorRoot)) {
        throw "Object storage mirror missing from release bundle: $mirrorRoot"
    }

    $minioUser = if ($env:MINIO_ROOT_USER) { $env:MINIO_ROOT_USER } elseif ($env:STORAGE_ACCESS_KEY) { $env:STORAGE_ACCESS_KEY } else { "immoapp" }
    $minioPass = if ($env:MINIO_ROOT_PASSWORD) { $env:MINIO_ROOT_PASSWORD } elseif ($env:STORAGE_SECRET_KEY) { $env:STORAGE_SECRET_KEY } else { "" }
    if (-not $minioPass) {
        throw "MINIO_ROOT_PASSWORD or STORAGE_SECRET_KEY is required for release bundle object restore."
    }

    $oldMinioUser = $env:IMMOAPP_RELEASE_MINIO_USER
    $oldMinioPassword = $env:IMMOAPP_RELEASE_MINIO_PASSWORD
    $env:IMMOAPP_RELEASE_MINIO_USER = $minioUser
    $env:IMMOAPP_RELEASE_MINIO_PASSWORD = $minioPass
    $restoreCommand = "mc alias set release http://minio:9000 " + '"$IMMOAPP_RELEASE_MINIO_USER" "$IMMOAPP_RELEASE_MINIO_PASSWORD"' +
        " && mc mb --ignore-existing " + (Quote-ShSingle "release/$restoreBucket") +
        " && mc mirror --overwrite " + (Quote-ShSingle "/backup/$mirrorRootRelative") + " " + (Quote-ShSingle "release/$restoreBucket")
    try {
        Invoke-MinioClient -ShellCommand $restoreCommand
    }
    finally {
        if ($null -ne $oldMinioUser) { $env:IMMOAPP_RELEASE_MINIO_USER = $oldMinioUser } else { Remove-Item Env:IMMOAPP_RELEASE_MINIO_USER -ErrorAction SilentlyContinue }
        if ($null -ne $oldMinioPassword) { $env:IMMOAPP_RELEASE_MINIO_PASSWORD = $oldMinioPassword } else { Remove-Item Env:IMMOAPP_RELEASE_MINIO_PASSWORD -ErrorAction SilentlyContinue }
    }

    $oldDb = $env:POSTGRES_DB
    $oldRestoreBucket = $env:IMMOAPP_RESTORE_BUCKET_OVERRIDE
    try {
        $env:POSTGRES_DB = $RestoreDatabase
        $env:IMMOAPP_RESTORE_BUCKET_OVERRIDE = $restoreBucket
        Invoke-Checked -Label "release restore verification" -Command { & $serverPython scripts/verify_release_restore_bundle.py --bundle-path $restoreRoot --require-storage-object }
    }
    finally {
        if ($null -ne $oldDb) { $env:POSTGRES_DB = $oldDb } else { Remove-Item Env:POSTGRES_DB -ErrorAction SilentlyContinue }
        if ($null -ne $oldRestoreBucket) { $env:IMMOAPP_RESTORE_BUCKET_OVERRIDE = $oldRestoreBucket } else { Remove-Item Env:IMMOAPP_RESTORE_BUCKET_OVERRIDE -ErrorAction SilentlyContinue }
    }

    if ($CleanupRestoreObjects.IsPresent) {
        Assert-RestoreDrillBucketName -BucketName $restoreBucket
        $oldMinioUser = $env:IMMOAPP_RELEASE_MINIO_USER
        $oldMinioPassword = $env:IMMOAPP_RELEASE_MINIO_PASSWORD
        $env:IMMOAPP_RELEASE_MINIO_USER = $minioUser
        $env:IMMOAPP_RELEASE_MINIO_PASSWORD = $minioPass
        $cleanupCommand = "mc alias set release http://minio:9000 " + '"$IMMOAPP_RELEASE_MINIO_USER" "$IMMOAPP_RELEASE_MINIO_PASSWORD"' +
            " && mc rb --force " + (Quote-ShSingle "release/$restoreBucket")
        try {
            Invoke-MinioClient -ShellCommand $cleanupCommand
        }
        finally {
            if ($null -ne $oldMinioUser) { $env:IMMOAPP_RELEASE_MINIO_USER = $oldMinioUser } else { Remove-Item Env:IMMOAPP_RELEASE_MINIO_USER -ErrorAction SilentlyContinue }
            if ($null -ne $oldMinioPassword) { $env:IMMOAPP_RELEASE_MINIO_PASSWORD = $oldMinioPassword } else { Remove-Item Env:IMMOAPP_RELEASE_MINIO_PASSWORD -ErrorAction SilentlyContinue }
        }
        Write-Host "Release restore object bucket cleaned up: $restoreBucket" -ForegroundColor Yellow
    }

    Write-Host "Release restore drill passed on database '$RestoreDatabase' with object data restored to isolated bucket '$restoreBucket'." -ForegroundColor Green
    Write-Host "Source bucket '$bucket' was not used as the restore target." -ForegroundColor Green
}
finally {
    if (Test-Path $restoreRoot) {
        Remove-Item -LiteralPath $restoreRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}
