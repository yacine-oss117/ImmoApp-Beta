$ErrorActionPreference = "Stop"

function Get-ImmoAppCanonicalAppDataRoot {
    return "C:\ProgramData\ImmoApp"
}

function Get-ImmoAppAppDataRoot {
    if (
        $env:IMMOAPP_TEST_PROGRAMDATA_ROOT -and
        $env:IMMOAPP_ALLOW_TEST_PROGRAMDATA_ROOT -in @("1", "true", "yes", "on")
    ) {
        return $env:IMMOAPP_TEST_PROGRAMDATA_ROOT
    }
    if ($env:IMMOAPP_APPDATA_ROOT) {
        return $env:IMMOAPP_APPDATA_ROOT
    }
    return "C:\ProgramData\ImmoApp"
}

function Get-ImmoAppRuntimeRootSource {
    if (
        $env:IMMOAPP_TEST_PROGRAMDATA_ROOT -and
        $env:IMMOAPP_ALLOW_TEST_PROGRAMDATA_ROOT -in @("1", "true", "yes", "on")
    ) {
        return "test_programdata_root"
    }
    if ($env:IMMOAPP_APPDATA_ROOT) {
        return "appdata_override"
    }
    return "canonical_programdata"
}

function New-ImmoAppRuntimePaths {
    param([Parameter(Mandatory = $true)][string]$AppDataRoot)
    $resolvedAppDataRoot = Get-ImmoAppAppDataRoot
    if (-not [string]::IsNullOrWhiteSpace($AppDataRoot)) {
        $resolvedAppDataRoot = $AppDataRoot
    }
    $configRoot = Join-Path $resolvedAppDataRoot "config"
    $secretsRoot = Join-Path $resolvedAppDataRoot "secrets"
    $dataRoot = Join-Path $resolvedAppDataRoot "data"
    $dataAppRoot = Join-Path $dataRoot "app"
    $toolsRoot = Join-Path $resolvedAppDataRoot "tools"
    $cacheRoot = Join-Path $resolvedAppDataRoot "cache"
    $venvsRoot = Join-Path $resolvedAppDataRoot "venvs"

    return @{
        AppDataRoot = $resolvedAppDataRoot
        ConfigRoot = $configRoot
        EnvFile = Join-Path $configRoot ".env.local"
        EnvBootstrapOpenBaoFile = Join-Path $configRoot ".env.bootstrap.openbao"
        SecretsRoot = $secretsRoot
        BootstrapSecretsFile = Join-Path $secretsRoot "immoapp-dev-secrets.json"
        OpenBaoTokenFile = Join-Path $secretsRoot "openbao.token"
        OpenBaoUnsealFile = Join-Path $secretsRoot "openbao.unseal"
        OpenBaoAppRoleFile = Join-Path $secretsRoot "openbao-approle.json"
        DataRoot = $dataRoot
        DataPgRoot = Join-Path $dataRoot "pgdata"
        DataRabbitMqRoot = Join-Path $dataRoot "rabbitmq"
        DataValkeyRoot = Join-Path $dataRoot "valkey"
        DataMinioRoot = Join-Path $dataRoot "minio"
        DataClamAvRoot = Join-Path $dataRoot "clamav"
        DataCaddyRoot = Join-Path $dataRoot "caddy"
        DataCaddyDataRoot = Join-Path $dataRoot "caddy\data"
        DataCaddyConfigRoot = Join-Path $dataRoot "caddy\config"
        DataAppRoot = $dataAppRoot
        DataAppCacheRoot = Join-Path $dataAppRoot "cache"
        DataAppMediaRoot = Join-Path $dataAppRoot "media"
        DataAppStaticRoot = Join-Path $dataAppRoot "static"
        DataAppLogsRoot = Join-Path $dataAppRoot "logs"
        DataAppBackupsRoot = Join-Path $dataAppRoot "backups"
        DataAppConfigRoot = Join-Path $dataAppRoot "config"
        DataAppToolsRoot = Join-Path $dataAppRoot "tools"
        DataAppTmpRoot = Join-Path $dataAppRoot "tmp"
        VenvsRoot = $venvsRoot
        RuntimeRoot = Join-Path $resolvedAppDataRoot "runtime"
        InstalledAppRoot = Join-Path $resolvedAppDataRoot "app"
        InstalledScriptsRoot = Join-Path $resolvedAppDataRoot "app\scripts"
        ToolsRoot = $toolsRoot
        CacheRoot = $cacheRoot
        PycacheRoot = Join-Path $cacheRoot "pycache"
        LogsRoot = Join-Path $resolvedAppDataRoot "logs"
        MediaRoot = Join-Path $resolvedAppDataRoot "media"
        TmpRoot = Join-Path $resolvedAppDataRoot "tmp"
        BackupsRoot = Join-Path $resolvedAppDataRoot "backups"
        ImportsRoot = Join-Path $resolvedAppDataRoot "imports"
        OfflineSyncRoot = Join-Path $resolvedAppDataRoot "offline_sync"
        ApiWriteQueueRoot = Join-Path $resolvedAppDataRoot "api_write_queue"
    }
}

function Get-ImmoAppRuntimePaths {
    return (New-ImmoAppRuntimePaths -AppDataRoot (Get-ImmoAppAppDataRoot))
}

function Get-ImmoAppCanonicalRuntimePaths {
    return (New-ImmoAppRuntimePaths -AppDataRoot (Get-ImmoAppCanonicalAppDataRoot))
}

function Test-ImmoAppUsingCanonicalRuntimeRoot {
    $active = [System.IO.Path]::GetFullPath((Get-ImmoAppRuntimePaths).AppDataRoot).TrimEnd("\", "/")
    $canonical = [System.IO.Path]::GetFullPath((Get-ImmoAppCanonicalRuntimePaths).AppDataRoot).TrimEnd("\", "/")
    return (
        (Get-ImmoAppRuntimeRootSource) -eq "canonical_programdata" -and
        $active.Equals($canonical, [System.StringComparison]::OrdinalIgnoreCase)
    )
}

function Get-ImmoAppRepoRoot {
    return (Resolve-Path (Join-Path $PSScriptRoot ".."))
}

function Test-ImmoAppIsAdministrator {
    if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
        return $false
    }
    try {
        $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
        $principal = New-Object System.Security.Principal.WindowsPrincipal($identity)
        return $principal.IsInRole([System.Security.Principal.WindowsBuiltInRole]::Administrator)
    }
    catch {
        return $false
    }
}

function Get-ImmoAppDesktopUserSid {
    param([string]$PreferredSid = "")

    foreach ($candidate in @($PreferredSid, $env:IMMOAPP_DESKTOP_USER_SID)) {
        $value = [string]$candidate
        if (-not [string]::IsNullOrWhiteSpace($value) -and $value.Trim() -match '^S-\d(?:-\d+)+$') {
            return $value.Trim()
        }
    }

    try {
        $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
        if ($identity -and $identity.User -and -not [string]::IsNullOrWhiteSpace($identity.User.Value)) {
            return [string]$identity.User.Value
        }
    }
    catch {
    }
    throw "Could not resolve the Windows desktop user SID."
}

function Test-ImmoAppDirectoryWritable {
    param([Parameter(Mandatory = $true)][string]$Path)

    if (-not (Test-Path -LiteralPath $Path -PathType Container)) {
        return $false
    }
    $probe = Join-Path $Path (".immoapp-write-probe-{0}-{1}.tmp" -f $PID, [Guid]::NewGuid().ToString("N"))
    try {
        [System.IO.File]::WriteAllText($probe, "ok", [System.Text.UTF8Encoding]::new($false))
        Remove-Item -LiteralPath $probe -Force -ErrorAction SilentlyContinue
        return $true
    }
    catch {
        Remove-Item -LiteralPath $probe -Force -ErrorAction SilentlyContinue
        return $false
    }
}

function Repair-ImmoAppHostRuntimePermissions {
    param([string]$DesktopUserSid = "")

    if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
        return
    }
    if (-not (Test-ImmoAppUsingCanonicalRuntimeRoot)) {
        return
    }
    if (-not (Test-ImmoAppIsAdministrator)) {
        throw "Administrator permission is required to repair C:\ProgramData\ImmoApp permissions."
    }

    $sid = Get-ImmoAppDesktopUserSid -PreferredSid $DesktopUserSid
    $paths = Get-ImmoAppRuntimePaths

    # These roots are intentionally writable by the interactive desktop owner.
    # They hold non-secret configuration, logs, caches, local queues, imports,
    # backups and other host-local state. Apply recursively so an existing
    # ProgramData tree created by an older elevated bootstrap self-heals too.
    $writableRoots = @(
        $paths.ConfigRoot,
        $paths.RuntimeRoot,
        $paths.ToolsRoot,
        $paths.CacheRoot,
        $paths.LogsRoot,
        $paths.MediaRoot,
        $paths.TmpRoot,
        $paths.BackupsRoot,
        $paths.ImportsRoot,
        $paths.OfflineSyncRoot,
        $paths.ApiWriteQueueRoot
    )

    foreach ($path in $writableRoots) {
        if (-not (Test-Path -LiteralPath $path -PathType Container)) { continue }
        & icacls.exe $path /grant "*$($sid):(OI)(CI)M" /T /C | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "Could not grant desktop-user write access to runtime path: $path"
        }
    }

    # The desktop owner must be able to create/update local bootstrap identity
    # files, while SYSTEM and Administrators retain recovery access. Individual
    # secret files are tightened further by the scripts that create them.
    if (Test-Path -LiteralPath $paths.SecretsRoot -PathType Container) {
        & icacls.exe $paths.SecretsRoot /grant "*$($sid):(OI)(CI)M" /T /C | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "Could not grant desktop-user access to the local secrets root: $($paths.SecretsRoot)"
        }
    }

    # Venvs are provisioned by bootstrap. Normal desktop use only needs to read
    # and execute them; package mutation remains an elevated bootstrap action.
    if (Test-Path -LiteralPath $paths.VenvsRoot -PathType Container) {
        & icacls.exe $paths.VenvsRoot /grant "*$($sid):(OI)(CI)RX" /T /C | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "Could not grant desktop-user execute access to the local Python environments."
        }
    }
}

function Invoke-ImmoAppRuntimePermissionRepairIfNeeded {
    param([switch]$AutoRepair)

    if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
        return $false
    }
    if (-not (Test-ImmoAppUsingCanonicalRuntimeRoot)) {
        return $false
    }

    $paths = Get-ImmoAppRuntimePaths
    if (-not (Test-Path -LiteralPath $paths.AppDataRoot -PathType Container)) {
        return $false
    }

    $probeRoots = @($paths.ConfigRoot, $paths.LogsRoot, $paths.CacheRoot)
    $needsRepair = $false
    foreach ($path in $probeRoots) {
        if ((Test-Path -LiteralPath $path -PathType Container) -and -not (Test-ImmoAppDirectoryWritable -Path $path)) {
            $needsRepair = $true
            break
        }
    }
    if (-not $needsRepair) {
        return $false
    }

    if (-not $AutoRepair) {
        throw "The local ImmoApp runtime exists but your Windows account cannot write its host-local runtime directories. Run scripts\repair_runtime_permissions.ps1 once."
    }

    $sid = Get-ImmoAppDesktopUserSid
    if (Test-ImmoAppIsAdministrator) {
        Repair-ImmoAppHostRuntimePermissions -DesktopUserSid $sid
    }
    else {
        $repairScript = Join-Path $PSScriptRoot "repair_runtime_permissions.ps1"
        if (-not (Test-Path -LiteralPath $repairScript)) {
            throw "Runtime permission repair helper is missing: $repairScript"
        }
        $arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$repairScript`" -DesktopUserSid `"$sid`""
        $process = Start-Process -FilePath "powershell.exe" -ArgumentList $arguments -WorkingDirectory (Get-ImmoAppRepoRoot) -Verb RunAs -Wait -PassThru
        if ($null -eq $process -or $process.ExitCode -ne 0) {
            throw "Windows runtime permission repair did not complete successfully."
        }
    }

    foreach ($path in $probeRoots) {
        if ((Test-Path -LiteralPath $path -PathType Container) -and -not (Test-ImmoAppDirectoryWritable -Path $path)) {
            throw "Runtime permission repair completed, but the current account still cannot write: $path"
        }
    }
    return $true
}

function Get-ImmoAppDeploymentRoot {
    return (Join-Path (Get-ImmoAppRepoRoot) "deployment")
}

function Get-ImmoAppComposeRoot {
    return (Join-Path (Get-ImmoAppDeploymentRoot) "compose")
}

function Get-ImmoAppComposeFile {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name
    )
    return (Join-Path (Get-ImmoAppComposeRoot) $Name)
}

function Get-ImmoAppDockerfilePath {
    return (Join-Path (Join-Path (Get-ImmoAppDeploymentRoot) "docker") "Dockerfile")
}

function Get-ImmoAppProxyFile {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name
    )
    return (Join-Path (Join-Path (Get-ImmoAppDeploymentRoot) "proxy") $Name)
}

function Get-ImmoAppEnvTemplatePath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name
    )
    return (Join-Path (Join-Path (Get-ImmoAppDeploymentRoot) "env") $Name)
}

function Get-ImmoAppAlembicRoot {
    return (Join-Path (Join-Path (Get-ImmoAppRepoRoot) "server") "alembic")
}

function Get-ImmoAppAlembicConfigPath {
    return (Join-Path (Join-Path (Get-ImmoAppRepoRoot) "server") "alembic.ini")
}

function Get-ImmoAppComposeArgs {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Names
    )

    $args = @()
    foreach ($name in $Names) {
        $path = Get-ImmoAppComposeFile -Name $name
        if (-not (Test-Path $path)) {
            throw "Compose file not found: $path"
        }
        $args += @("-f", $path)
    }
    return $args
}

function Get-ImmoAppComposeProjectArgs {
    return @("--project-directory", (Get-ImmoAppRepoRoot))
}

function Get-ImmoAppHubRuntimeProviderConfigPath {
    return (Join-Path (Get-ImmoAppRuntimePaths).ConfigRoot "hub_runtime_provider.json")
}

function Get-ImmoAppHubIdentityPath {
    return (Join-Path (Get-ImmoAppRuntimePaths).ConfigRoot "hub_identity.json")
}

function Get-ImmoAppHubStateManifestPath {
    return (Join-Path (Get-ImmoAppRuntimePaths).ConfigRoot "hub_state_manifest.json")
}

function Get-ImmoAppCanonicalHubRuntimeProviderConfigPath {
    return (Join-Path (Get-ImmoAppCanonicalRuntimePaths).ConfigRoot "hub_runtime_provider.json")
}

function Get-ImmoAppHubIdentityDisplayNameHelp {
    return "Choose a simple name your team will recognize, like Main Office or Reception PC."
}

function Get-ImmoAppProviderMutationLockPath {
    return (Join-Path (Get-ImmoAppRuntimePaths).ConfigRoot "hub_runtime_provider.lock")
}

function Test-ImmoAppPathUnderRoot {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string]$Path
    )
    $rootFull = [System.IO.Path]::GetFullPath($Root).TrimEnd("\", "/")
    $pathFull = [System.IO.Path]::GetFullPath($Path)
    return (
        $pathFull.Equals($rootFull, [System.StringComparison]::OrdinalIgnoreCase) -or
        $pathFull.StartsWith($rootFull + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)
    )
}

function Test-ImmoAppResolvedPathUnderRoot {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string]$Path
    )
    $rootFull = [System.IO.Path]::GetFullPath($Root).TrimEnd("\", "/")
    $pathFull = if (Test-Path -LiteralPath $Path) {
        [System.IO.Path]::GetFullPath((Resolve-Path -LiteralPath $Path).Path)
    } else {
        [System.IO.Path]::GetFullPath($Path)
    }
    return (
        $pathFull.Equals($rootFull, [System.StringComparison]::OrdinalIgnoreCase) -or
        $pathFull.StartsWith($rootFull + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)
    )
}

function Test-ImmoAppPathHasReparsePoint {
    param([Parameter(Mandatory = $true)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return $false }
    $current = (Get-Item -LiteralPath $Path -Force).FullName
    while (-not [string]::IsNullOrWhiteSpace($current)) {
        if (Test-Path -LiteralPath $current) {
            $item = Get-Item -LiteralPath $current -Force
            if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
                return $true
            }
        }
        $parent = Split-Path -Parent $current
        if ([string]::IsNullOrWhiteSpace($parent) -or $parent -eq $current) { break }
        $current = $parent
    }
    return $false
}

function Enter-ImmoAppProviderMutationLock {
    param([int]$TimeoutSeconds = 60)

    $paths = Ensure-ImmoAppRuntimeLayout
    $lockPath = [System.IO.Path]::GetFullPath((Get-ImmoAppProviderMutationLockPath))
    Assert-ImmoAppCanonicalProviderConfigPathSafe -Path (Get-ImmoAppHubRuntimeProviderConfigPath) -AllowNonCanonical | Out-Null
    if (-not (Test-ImmoAppPathUnderRoot -Root $paths.ConfigRoot -Path $lockPath)) {
        throw "provider_lock_path_invalid|Provider mutation lock must be under the active config root."
    }
    if (Test-ImmoAppPathHasReparsePoint -Path $paths.ConfigRoot) {
        throw "provider_lock_reparse_point|Provider mutation lock parent contains a reparse point, symlink, or junction."
    }

    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    while ($true) {
        try {
            $stream = [System.IO.File]::Open($lockPath, [System.IO.FileMode]::OpenOrCreate, [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::Read)
            $payload = [ordered]@{
                kind = "immoapp_provider_mutation_lock"
                schema_version = 1
                pid = $PID
                acquired_at_utc = (Get-Date).ToUniversalTime().ToString("o")
            } | ConvertTo-Json -Depth 4
            $bytes = [System.Text.UTF8Encoding]::new($false).GetBytes($payload)
            $stream.SetLength(0)
            $stream.Write($bytes, 0, $bytes.Length)
            $stream.Flush($true)
            return [ordered]@{
                acquired = $true
                path = $lockPath
                stream = $stream
            }
        }
        catch [System.IO.IOException] {
            if ([DateTime]::UtcNow -ge $deadline) {
                throw "provider_lock_timeout|Timed out waiting for Hub runtime provider mutation lock."
            }
            Start-Sleep -Milliseconds 200
        }
    }
}

function Exit-ImmoAppProviderMutationLock {
    param([object]$Lock)
    if ($null -ne $Lock -and $null -ne $Lock.stream) {
        $Lock.stream.Dispose()
    }
}

function Assert-ImmoAppProviderMutationLockHeld {
    param([Parameter(Mandatory = $true)]$Lock)
    if ($null -eq $Lock -or $null -eq $Lock.stream) {
        throw "provider_lock_required|Managed runtime provider writes require the provider mutation lock."
    }
    $expectedPath = [System.IO.Path]::GetFullPath((Get-ImmoAppProviderMutationLockPath))
    $actualPath = [System.IO.Path]::GetFullPath([string]$Lock.path)
    if (-not $actualPath.Equals($expectedPath, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "provider_lock_required|Managed runtime provider writes require the active provider mutation lock."
    }
    if (-not $Lock.stream.CanWrite) {
        throw "provider_lock_required|Managed runtime provider mutation lock stream is not writable."
    }
    $probe = $null
    try {
        $probe = [System.IO.File]::Open($expectedPath, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Write, [System.IO.FileShare]::None)
        throw "provider_lock_required|Managed runtime provider mutation lock is not exclusively held."
    }
    catch [System.IO.IOException] {
        return $true
    }
    finally {
        if ($null -ne $probe) { $probe.Dispose() }
    }
}

function Assert-ImmoAppCanonicalProviderConfigPathSafe {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [switch]$AllowNonCanonical
    )
    $actual = [System.IO.Path]::GetFullPath($Path)
    $canonical = [System.IO.Path]::GetFullPath((Get-ImmoAppCanonicalHubRuntimeProviderConfigPath))
    $configRoot = [System.IO.Path]::GetFullPath((Get-ImmoAppCanonicalRuntimePaths).ConfigRoot)
    if (-not $AllowNonCanonical -and -not $actual.Equals($canonical, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "managed_runtime_noncanonical_provider_config|Provider config path must be the canonical ProgramData path for agency readiness: $canonical"
    }
    if (-not $AllowNonCanonical -and -not (Test-ImmoAppPathUnderRoot -Root $configRoot -Path $actual)) {
        throw "managed_runtime_provider_config_path_unsafe|Provider config path must be under the canonical config root: $actual"
    }

    $existing = if (Test-Path -LiteralPath $actual) { $actual } else { Split-Path -Parent $actual }
    while (-not [string]::IsNullOrWhiteSpace($existing) -and -not (Test-Path -LiteralPath $existing)) {
        $parent = Split-Path -Parent $existing
        if ([string]::IsNullOrWhiteSpace($parent) -or $parent -eq $existing) { break }
        $existing = $parent
    }
    if (-not [string]::IsNullOrWhiteSpace($existing) -and (Test-Path -LiteralPath $existing)) {
        if (Test-ImmoAppPathHasReparsePoint -Path $existing) {
            throw "managed_runtime_provider_config_path_unsafe|Provider config path or parent contains a reparse point, symlink, or junction: $existing"
        }
        if (
            -not $AllowNonCanonical -and
            (Test-Path -LiteralPath $configRoot) -and
            -not (Test-ImmoAppResolvedPathUnderRoot -Root $configRoot -Path $existing)
        ) {
            throw "managed_runtime_provider_config_resolved_outside_canonical_root|Provider config path resolves outside the canonical config root: $existing"
        }
    }
    if (Test-Path -LiteralPath $actual) {
        if (Test-ImmoAppPathHasReparsePoint -Path $actual) {
            throw "managed_runtime_provider_config_path_unsafe|Provider config file contains a reparse point, symlink, or junction: $actual"
        }
        if (-not $AllowNonCanonical -and -not (Test-ImmoAppResolvedPathUnderRoot -Root $configRoot -Path $actual)) {
            throw "managed_runtime_provider_config_resolved_outside_canonical_root|Provider config file resolves outside the canonical config root: $actual"
        }
    }
    return $actual
}

function Assert-ImmoAppProviderSnapshotPathSafe {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [switch]$AllowNonCanonical
    )
    $actual = Assert-ImmoAppCanonicalProviderConfigPathSafe -Path $Path -AllowNonCanonical:$AllowNonCanonical
    $parent = Split-Path -Parent $actual
    if ($parent -and (Test-Path -LiteralPath $parent) -and (Test-ImmoAppPathHasReparsePoint -Path $parent)) {
        throw "managed_runtime_provider_config_path_unsafe|Provider config snapshot parent contains a reparse point, symlink, or junction: $parent"
    }
    if (Test-Path -LiteralPath $actual) {
        if (Test-ImmoAppPathHasReparsePoint -Path $actual) {
            throw "managed_runtime_provider_config_path_unsafe|Provider config snapshot target contains a reparse point, symlink, or junction: $actual"
        }
    }
    return $actual
}

function Get-ImmoAppSensitiveFieldPattern {
    return "(?i)(authorization|password|passwd|secret|token|refresh|access_token|accessToken|refresh_token|refreshToken|sessionToken|idToken|access|client_secret|clientSecret|credential|presigned|signature|apikey|api[_-]?key|xApiKey|privatekey|private[_-]?key|certificate|cert|key_material|\.env)"
}

function Get-ImmoAppFileSha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Get-ImmoAppTextSha256 {
    param([Parameter(Mandatory = $true)][string]$Text)
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($Text)
        return (($sha.ComputeHash($bytes) | ForEach-Object { $_.ToString("x2") }) -join "")
    }
    finally {
        $sha.Dispose()
    }
}

function Assert-ImmoAppNoSensitiveObjectFields {
    param(
        [Parameter(Mandatory = $true)][object]$Node,
        [string]$Path = "object"
    )
    if ($null -eq $Node) { return }
    foreach ($property in @($Node.PSObject.Properties)) {
        $name = [string]$property.Name
        $childPath = "$Path.$name"
        if ($name -match (Get-ImmoAppSensitiveFieldPattern)) {
            throw "managed_runtime_secret_in_config|Sensitive field name is not allowed in runtime provenance/config: $childPath"
        }
        $value = $property.Value
        if ($null -eq $value -or $value -is [string] -or $value -is [ValueType]) {
            continue
        }
        if ($value -is [System.Collections.IEnumerable]) {
            $index = 0
            foreach ($item in @($value)) {
                if ($null -ne $item -and -not ($item -is [string]) -and -not ($item -is [ValueType])) {
                    Assert-ImmoAppNoSensitiveObjectFields -Node $item -Path "${childPath}[$index]"
                }
                $index += 1
            }
        }
        else {
            Assert-ImmoAppNoSensitiveObjectFields -Node $value -Path $childPath
        }
    }
}

function Test-ImmoAppUnsafeArchivePath {
    param([Parameter(Mandatory = $true)][string]$RelativePath)
    if ([string]::IsNullOrWhiteSpace($RelativePath)) { return $true }
    $clean = $RelativePath.Replace("\", "/")
    return (
        $clean.StartsWith("/") -or
        $clean.StartsWith("../") -or
        $clean.Contains("/../") -or
        $clean.Contains(":") -or
        $clean -match "[\x00-\x1f]"
    )
}

function Get-ImmoAppStrictRuntimeTreeInventory {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [switch]$RequireNonEmpty
    )
    if (-not (Test-Path -LiteralPath $Root -PathType Container)) {
        throw "managed_runtime_tree_missing|Runtime tree root does not exist: $Root"
    }
    $rootFull = [System.IO.Path]::GetFullPath($Root)
    if (Test-ImmoAppPathHasReparsePoint -Path $rootFull) {
        throw "managed_runtime_tree_reparse_point|Runtime tree root or parent contains a reparse point, symlink, or junction: $rootFull"
    }

    $entries = New-Object System.Collections.Generic.List[object]
    $forbidden = New-Object System.Collections.Generic.List[object]
    $seen = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::OrdinalIgnoreCase)
    $totalBytes = 0L
    foreach ($item in Get-ChildItem -LiteralPath $rootFull -Recurse -Force) {
        $itemFull = [System.IO.Path]::GetFullPath($item.FullName)
        $relative = $itemFull.Substring($rootFull.TrimEnd("\", "/").Length + 1).Replace("\", "/")
        if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0 -or (Test-ImmoAppPathHasReparsePoint -Path $itemFull)) {
            $forbidden.Add([ordered]@{ path = $relative; reason = "managed_runtime_tree_reparse_point" })
            continue
        }
        if ($item.PSIsContainer) { continue }
        if (Test-ImmoAppUnsafeArchivePath -RelativePath $relative) {
            $forbidden.Add([ordered]@{ path = $relative; reason = "unsafe_archive_path" })
            continue
        }
        if (-not $seen.Add($relative)) {
            $forbidden.Add([ordered]@{ path = $relative; reason = "duplicate_archive_entry" })
            continue
        }
        $reason = Get-ImmoAppForbiddenRuntimePackageReason -RelativePath $relative
        if (-not [string]::IsNullOrWhiteSpace($reason)) {
            $forbidden.Add([ordered]@{ path = $relative; reason = $reason })
            continue
        }
        $bytes = [int64]$item.Length
        $totalBytes += $bytes
        $entries.Add([ordered]@{
            path = $relative
            bytes = $bytes
            sha256 = Get-ImmoAppFileSha256 -Path $itemFull
        })
    }

    if ($forbidden.Count -gt 0) {
        $first = $forbidden[0]
        throw "$($first.reason)|Runtime tree contains forbidden or unsafe content: $($first.path)"
    }
    if ($RequireNonEmpty -and $entries.Count -le 0) {
        throw "managed_runtime_tree_empty|Runtime tree must contain at least one file."
    }

    $files = @($entries.ToArray() | Sort-Object { [string]$_.path })
    $json = ($files | ConvertTo-Json -Depth 5 -Compress)
    if ([string]::IsNullOrWhiteSpace($json)) { $json = "[]" }
    return [ordered]@{
        sha256 = Get-ImmoAppTextSha256 -Text $json
        file_count = [int]$files.Count
        total_bytes = [int64]$totalBytes
        forbidden_matches = @()
        files = @($files)
    }
}

function Get-ImmoAppRuntimeTreeInventorySha256 {
    param([Parameter(Mandatory = $true)][string]$Root)
    return [string](Get-ImmoAppStrictRuntimeTreeInventory -Root $Root).sha256
}

function Get-ImmoAppManagedWsl2RuntimeArtifactRequiredEntries {
    return @(
        "bin/immoapp-managed-wsl2-runtime.ps1",
        "bin/immoapp-managed-wsl2-compose.ps1",
        "bin/start-managed-hub.ps1",
        "bin/status-managed-hub.ps1",
        "bin/health-managed-hub.ps1",
        "bin/logs-managed-hub.ps1",
        "bin/backup-managed-hub.ps1",
        "bin/stop-managed-hub.ps1",
        "bin/restart-managed-hub.ps1",
        "bin/bootstrap-managed-runtime.ps1",
        "bin/keepalive-managed-hub.ps1"
    )
}

function Get-ImmoAppManagedWsl2ImageBundleArchivePath {
    return (Join-Path (Get-ImmoAppRuntimePaths).RuntimeRoot "images\immoapp-runtime-images.tar")
}

function Get-ImmoAppManagedWsl2ImageBundleInventoryPath {
    return (Join-Path (Get-ImmoAppRuntimePaths).ConfigRoot "managed_wsl2_runtime_image_bundle_inventory.json")
}

function Convert-ImmoAppManagedWsl2CanonicalHostPathToWslPath {
    param([Parameter(Mandatory = $true)][string]$Path)
    $full = [System.IO.Path]::GetFullPath($Path)
    $canonicalRoot = [System.IO.Path]::GetFullPath((Get-ImmoAppCanonicalRuntimePaths).AppDataRoot).TrimEnd("\", "/")
    if (-not $full.StartsWith($canonicalRoot + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "managed_runtime_image_archive_wsl_path_missing|Only canonical C:\ProgramData\ImmoApp paths can be converted to WSL paths."
    }
    $drive = [System.IO.Path]::GetPathRoot($full).TrimEnd("\", ":").ToLowerInvariant()
    if ($drive -ne "c") {
        throw "managed_runtime_image_archive_wsl_path_missing|Only canonical C: ProgramData paths can be converted to WSL paths."
    }
    $suffix = $full.Substring($canonicalRoot.Length).TrimStart("\", "/").Replace("\", "/")
    return "/mnt/c/ProgramData/ImmoApp/$suffix"
}

function Get-ImmoAppManagedWsl2RootfsTarPath {
    return (Join-Path (Get-ImmoAppRuntimePaths).RuntimeRoot "rootfs\ImmoAppRuntime.rootfs.tar")
}

function Get-ImmoAppManagedWsl2RootfsInventoryPath {
    return (Join-Path (Get-ImmoAppRuntimePaths).ConfigRoot "managed_wsl2_runtime_rootfs_inventory.json")
}

function Get-ImmoAppManagedWsl2RuntimeComposePayloadPath {
    return "/opt/immoapp/runtime/compose/compose.yaml"
}

function Get-ImmoAppManagedWsl2RuntimeRequiredComposeServices {
    return @(
        "db",
        "rabbitmq",
        "valkey",
        "minio",
        "clamav",
        "openbao",
        "web",
        "worker",
        "worker-import",
        "worker-rebuild",
        "worker-match",
        "beat",
        "caddy"
    )
}

function Assert-ImmoAppManagedWsl2ImageBundleInventoryReady {
    param(
        [Parameter(Mandatory = $true)]$Inventory,
        [string]$ExpectedInventorySha256 = "",
        [string]$ExpectedSourceCommitSha = "",
        [string]$ImageBundleInventoryPath = "",
        [switch]$AllowTestOnlyPath
    )

    if ([string](Get-ImmoAppObjectValue -Data $Inventory -Name "kind") -ne "immoapp_managed_wsl2_runtime_image_bundle_inventory") {
        throw "managed_runtime_image_bundle_inventory_invalid|Managed WSL2 runtime image bundle inventory has the wrong kind."
    }
    if ([int](Get-ImmoAppObjectValue -Data $Inventory -Name "schema_version") -ne 1) {
        throw "managed_runtime_image_bundle_inventory_invalid|Managed WSL2 runtime image bundle inventory has an unsupported schema_version."
    }
    if ([string](Get-ImmoAppObjectValue -Data $Inventory -Name "proof_result") -ne "GO") {
        throw "managed_runtime_image_bundle_inventory_not_go|Managed WSL2 runtime image bundle inventory must be GO."
    }
    Assert-ImmoAppNoSensitiveObjectFields -Node $Inventory -Path "image_bundle_inventory"

    $paths = Get-ImmoAppRuntimePaths
    $canonicalPaths = Get-ImmoAppCanonicalRuntimePaths
    $runtimeRoots = if ($AllowTestOnlyPath) {
        Get-ImmoAppProofApprovedRoots -CanonicalPaths $canonicalPaths -ActivePaths $paths -Kind "runtime"
    } else {
        @($canonicalPaths.RuntimeRoot)
    }
    $configRoots = if ($AllowTestOnlyPath) {
        Get-ImmoAppProofApprovedRoots -CanonicalPaths $canonicalPaths -ActivePaths $paths -Kind "config"
    } else {
        @($canonicalPaths.ConfigRoot)
    }

    if (-not [string]::IsNullOrWhiteSpace($ImageBundleInventoryPath)) {
        $resolvedInventoryPath = Assert-ImmoAppManagedRuntimeExistingFile -Path $ImageBundleInventoryPath -Label "ImageBundleInventoryPath" -AllowTestOnlyPath:$AllowTestOnlyPath
        Assert-ImmoAppProofOnlyPathApproved -Path $resolvedInventoryPath -Roots $configRoots -Label "ImageBundleInventoryPath"
        if (-not [string]::IsNullOrWhiteSpace($ExpectedInventorySha256)) {
            Assert-ImmoAppLowerHexSha256 -Value $ExpectedInventorySha256 -Name "image_bundle_inventory_sha256"
            $actualInventorySha = Get-ImmoAppFileSha256 -Path $resolvedInventoryPath
            if ($actualInventorySha -ne $ExpectedInventorySha256) {
                throw "managed_runtime_image_bundle_inventory_hash_mismatch|Managed WSL2 runtime image bundle inventory hash does not match provider config."
            }
        }
    }

    if (-not [string]::IsNullOrWhiteSpace($ExpectedSourceCommitSha)) {
        if ([string](Get-ImmoAppObjectValue -Data $Inventory -Name "source_commit_sha") -ne $ExpectedSourceCommitSha) {
            throw "managed_runtime_image_bundle_commit_mismatch|Managed WSL2 runtime image bundle source_commit_sha does not match provider config."
        }
    }
    $inventorySourceCommitSha = [string](Get-ImmoAppObjectValue -Data $Inventory -Name "source_commit_sha")
    Assert-ImmoAppLowerGitSha -Value $inventorySourceCommitSha -Name "image_bundle.source_commit_sha"
    $appImageSourceCommitSha = [string](Get-ImmoAppObjectValue -Data $Inventory -Name "app_image_source_commit_sha")
    Assert-ImmoAppLowerGitSha -Value $appImageSourceCommitSha -Name "image_bundle.app_image_source_commit_sha"
    $appImageRevisionLabel = [string](Get-ImmoAppObjectValue -Data $Inventory -Name "app_image_revision_label")
    if ($appImageRevisionLabel -ne "org.opencontainers.image.revision") {
        throw "managed_runtime_app_image_commit_mismatch|Managed WSL2 runtime image bundle app image revision label is missing or invalid."
    }
    if (-not [bool](Get-ImmoAppObjectValue -Data $Inventory -Name "app_image_revision_verified")) {
        throw "managed_runtime_app_image_commit_mismatch|Managed WSL2 runtime image bundle app image revision proof is missing."
    }
    if ($appImageSourceCommitSha -ne $inventorySourceCommitSha) {
        throw "managed_runtime_app_image_commit_mismatch|Managed WSL2 runtime image bundle app image commit does not match source_commit_sha."
    }
    if (-not [string]::IsNullOrWhiteSpace($ExpectedSourceCommitSha) -and $appImageSourceCommitSha -ne $ExpectedSourceCommitSha) {
        throw "managed_runtime_app_image_commit_mismatch|Managed WSL2 runtime image bundle app image commit does not match the expected release commit."
    }

    $archivePath = [string](Get-ImmoAppObjectValue -Data $Inventory -Name "image_archive_host_path")
    if ([string]::IsNullOrWhiteSpace($archivePath)) {
        $archivePath = [string](Get-ImmoAppObjectValue -Data $Inventory -Name "image_archive_path")
    }
    if ([string]::IsNullOrWhiteSpace($archivePath)) {
        throw "managed_runtime_image_archive_missing|Managed WSL2 runtime image bundle inventory requires image_archive_host_path."
    }
    if (-not (Test-Path -LiteralPath $archivePath -PathType Leaf)) {
        throw "managed_runtime_image_archive_missing|Managed WSL2 runtime image archive is missing."
    }
    $archivePath = Assert-ImmoAppManagedRuntimeExistingFile -Path $archivePath -Label "image_archive_path" -AllowTestOnlyPath:$AllowTestOnlyPath
    Assert-ImmoAppProofOnlyPathApproved -Path $archivePath -Roots $runtimeRoots -Label "image_archive_path"
    $archiveSha = [string](Get-ImmoAppObjectValue -Data $Inventory -Name "image_archive_sha256")
    Assert-ImmoAppLowerHexSha256 -Value $archiveSha -Name "image_archive_sha256"
    $actualArchiveSha = Get-ImmoAppFileSha256 -Path $archivePath
    if ($actualArchiveSha -ne $archiveSha) {
        throw "managed_runtime_image_archive_hash_mismatch|Managed WSL2 runtime image archive hash does not match inventory."
    }
    $archiveWslPath = [string](Get-ImmoAppObjectValue -Data $Inventory -Name "image_archive_wsl_path")
    if ([string]::IsNullOrWhiteSpace($archiveWslPath)) {
        $archiveWslPath = Convert-ImmoAppManagedWsl2CanonicalHostPathToWslPath -Path $archivePath
    }
    if (-not $archiveWslPath.StartsWith("/mnt/c/ProgramData/ImmoApp/", [System.StringComparison]::Ordinal)) {
        throw "managed_runtime_image_archive_wsl_path_missing|Managed WSL2 runtime image archive WSL path must be under /mnt/c/ProgramData/ImmoApp."
    }
    $inventoryWslPath = [string](Get-ImmoAppObjectValue -Data $Inventory -Name "image_bundle_inventory_wsl_path")
    if ([string]::IsNullOrWhiteSpace($inventoryWslPath) -and -not [string]::IsNullOrWhiteSpace($ImageBundleInventoryPath)) {
        $inventoryWslPath = Convert-ImmoAppManagedWsl2CanonicalHostPathToWslPath -Path $ImageBundleInventoryPath
    }

    $images = @(Get-ImmoAppObjectValue -Data $Inventory -Name "images")
    if ($images.Count -le 0) {
        throw "managed_runtime_image_bundle_inventory_invalid|Managed WSL2 runtime image bundle inventory must list images."
    }
    foreach ($image in $images) {
        $tag = [string](Get-ImmoAppObjectValue -Data $image -Name "tag")
        if ([string]::IsNullOrWhiteSpace($tag) -or $tag -match "\s") {
            throw "managed_runtime_image_bundle_inventory_invalid|Managed WSL2 runtime image bundle contains an invalid image tag."
        }
        $sourceImage = [string](Get-ImmoAppObjectValue -Data $image -Name "source_image")
        if ($sourceImage -match "(:latest$|/latest$)" -or ([string]::IsNullOrWhiteSpace($sourceImage) -and $tag -match ":latest$")) {
            throw "managed_runtime_image_source_not_pinned|Managed WSL2 runtime image bundle contains an unpinned source image."
        }
    }

    return [ordered]@{
        image_archive_path = $archivePath
        image_archive_host_path = $archivePath
        image_archive_wsl_path = $archiveWslPath
        image_archive_sha256 = $archiveSha
        image_bundle_inventory_path = $ImageBundleInventoryPath
        image_bundle_inventory_host_path = $ImageBundleInventoryPath
        image_bundle_inventory_wsl_path = $inventoryWslPath
        image_bundle_inventory_sha256 = $ExpectedInventorySha256
        image_count = [int]$images.Count
        images = @($images)
    }
}

function Assert-ImmoAppManagedWsl2RuntimeArtifactInventoryReady {
    param(
        [Parameter(Mandatory = $true)]$Inventory,
        [string]$ExpectedInventorySha256 = "",
        [string]$ExpectedSourceCommitSha = "",
        [string]$ArtifactInventoryPath = "",
        [switch]$AllowTestOnlyPath
    )

    if ([string](Get-ImmoAppObjectValue -Data $Inventory -Name "kind") -ne "immoapp_managed_wsl2_runtime_artifact_inventory") {
        throw "managed_wsl2_runtime_artifact_inventory_invalid|Managed WSL2 runtime artifact inventory has the wrong kind."
    }
    if ([int](Get-ImmoAppObjectValue -Data $Inventory -Name "schema_version") -ne 1) {
        throw "managed_wsl2_runtime_artifact_inventory_invalid|Managed WSL2 runtime artifact inventory has an unsupported schema_version."
    }
    if ([string](Get-ImmoAppObjectValue -Data $Inventory -Name "proof_result") -ne "GO") {
        throw "managed_wsl2_runtime_artifact_inventory_not_go|Managed WSL2 runtime artifact inventory must be GO."
    }
    if ([string](Get-ImmoAppObjectValue -Data $Inventory -Name "runtime_artifact_status") -ne "GO") {
        throw "managed_wsl2_runtime_artifact_not_go|Managed WSL2 runtime artifact status must be GO."
    }
    if ([string](Get-ImmoAppObjectValue -Data $Inventory -Name "runtime_start_status") -eq "GO") {
        throw "managed_wsl2_runtime_start_unproven|Managed WSL2 runtime artifact inventory cannot claim runtime_start_status=GO."
    }

    $paths = Get-ImmoAppRuntimePaths
    $canonicalPaths = Get-ImmoAppCanonicalRuntimePaths
    $artifactRoot = [string](Get-ImmoAppObjectValue -Data $Inventory -Name "artifact_root")
    if ([string]::IsNullOrWhiteSpace($artifactRoot)) {
        throw "managed_wsl2_runtime_artifact_root_missing|Managed WSL2 runtime artifact inventory requires artifact_root."
    }
    $artifactRoot = Assert-ImmoAppManagedRuntimeExistingDirectory -Path $artifactRoot -Label "artifact_root" -AllowTestOnlyPath:$AllowTestOnlyPath
    $runtimeRoots = if ($AllowTestOnlyPath) {
        Get-ImmoAppProofApprovedRoots -CanonicalPaths $canonicalPaths -ActivePaths $paths -Kind "runtime"
    } else {
        @($canonicalPaths.RuntimeRoot)
    }
    Assert-ImmoAppProofOnlyPathApproved -Path $artifactRoot -Roots $runtimeRoots -Label "artifact_root"

    if (-not [string]::IsNullOrWhiteSpace($ArtifactInventoryPath)) {
        $inventoryRoots = if ($AllowTestOnlyPath) {
            @(
                (Get-ImmoAppProofApprovedRoots -CanonicalPaths $canonicalPaths -ActivePaths $paths -Kind "config") +
                (Get-ImmoAppProofApprovedRoots -CanonicalPaths $canonicalPaths -ActivePaths $paths -Kind "logs")
            ) | Select-Object -Unique
        } else {
            @($canonicalPaths.ConfigRoot, $canonicalPaths.LogsRoot)
        }
        $resolvedInventoryPath = Assert-ImmoAppManagedRuntimeExistingFile -Path $ArtifactInventoryPath -Label "RuntimeArtifactInventoryJson" -AllowTestOnlyPath:$AllowTestOnlyPath
        Assert-ImmoAppProofOnlyPathApproved -Path $resolvedInventoryPath -Roots $inventoryRoots -Label "RuntimeArtifactInventoryJson"
        if (-not [string]::IsNullOrWhiteSpace($ExpectedInventorySha256)) {
            Assert-ImmoAppLowerHexSha256 -Value $ExpectedInventorySha256 -Name "runtime_artifact_inventory_sha256"
            $actualInventorySha = Get-ImmoAppFileSha256 -Path $resolvedInventoryPath
            if ($actualInventorySha -ne $ExpectedInventorySha256) {
                throw "managed_wsl2_runtime_artifact_inventory_hash_mismatch|Managed WSL2 runtime artifact inventory hash does not match provider config."
            }
        }
    }

    if (-not [string]::IsNullOrWhiteSpace($ExpectedSourceCommitSha)) {
        if ([string](Get-ImmoAppObjectValue -Data $Inventory -Name "source_commit_sha") -ne $ExpectedSourceCommitSha) {
            throw "managed_wsl2_runtime_artifact_commit_mismatch|Managed WSL2 runtime artifact inventory source_commit_sha does not match provider config."
        }
    }

    $treeInventory = Get-ImmoAppStrictRuntimeTreeInventory -Root $artifactRoot -RequireNonEmpty
    $artifactTreeSha = [string](Get-ImmoAppObjectValue -Data $Inventory -Name "artifact_tree_sha256")
    Assert-ImmoAppLowerHexSha256 -Value $artifactTreeSha -Name "artifact_tree_sha256"
    if ([string]$treeInventory.sha256 -ne $artifactTreeSha) {
        throw "managed_wsl2_runtime_artifact_tree_hash_mismatch|Managed WSL2 runtime artifact tree hash does not match inventory."
    }
    if ([int64](Get-ImmoAppObjectValue -Data $Inventory -Name "forbidden_path_count") -ne 0) {
        throw "managed_wsl2_runtime_artifact_forbidden_content|Managed WSL2 runtime artifact inventory contains forbidden content."
    }

    $filesByPath = @{}
    foreach ($file in @($treeInventory.files)) {
        $filesByPath[[string]$file.path] = $file
    }
    $requiredStatus = Get-ImmoAppObjectValue -Data $Inventory -Name "required_entries"
    foreach ($requiredEntry in Get-ImmoAppManagedWsl2RuntimeArtifactRequiredEntries) {
        if (-not $filesByPath.ContainsKey($requiredEntry)) {
            throw "managed_wsl2_runtime_required_entry_missing|Managed WSL2 runtime artifact missing required entry: $requiredEntry"
        }
        $entryStatus = Get-ImmoAppObjectValue -Data $requiredStatus -Name $requiredEntry
        if ($null -ne $entryStatus) {
            if ([string](Get-ImmoAppObjectValue -Data $entryStatus -Name "status") -ne "present") {
                throw "managed_wsl2_runtime_required_entry_missing|Managed WSL2 runtime artifact required entry is not marked present: $requiredEntry"
            }
        }
    }

    $runtimeExecutablePath = [string](Get-ImmoAppObjectValue -Data $Inventory -Name "runtime_executable_path")
    $composeExecutablePath = [string](Get-ImmoAppObjectValue -Data $Inventory -Name "compose_executable_path")
    $startCommandPath = [string](Get-ImmoAppObjectValue -Data $Inventory -Name "start_command_path")
    $statusCommandPath = [string](Get-ImmoAppObjectValue -Data $Inventory -Name "status_command_path")
    $logsCommandPath = [string](Get-ImmoAppObjectValue -Data $Inventory -Name "logs_command_path")
    $backupCommandPath = [string](Get-ImmoAppObjectValue -Data $Inventory -Name "backup_command_path")
    $healthCommandPath = [string](Get-ImmoAppObjectValue -Data $Inventory -Name "health_command_path")
    $stopCommandPath = [string](Get-ImmoAppObjectValue -Data $Inventory -Name "stop_command_path")
    $restartCommandPath = [string](Get-ImmoAppObjectValue -Data $Inventory -Name "restart_command_path")
    $bootstrapCommandPath = [string](Get-ImmoAppObjectValue -Data $Inventory -Name "bootstrap_command_path")
    if ([string]::IsNullOrWhiteSpace($runtimeExecutablePath) -or [string]::IsNullOrWhiteSpace($composeExecutablePath)) {
        throw "managed_wsl2_runtime_artifact_executable_missing|Managed WSL2 runtime artifact inventory requires runtime and compose executable paths."
    }
    if ([string]::IsNullOrWhiteSpace($startCommandPath) -or [string]::IsNullOrWhiteSpace($statusCommandPath)) {
        throw "managed_wsl2_runtime_artifact_start_command_missing|Managed WSL2 runtime artifact inventory requires start and status command paths."
    }
    if ([string]::IsNullOrWhiteSpace($logsCommandPath) -or [string]::IsNullOrWhiteSpace($backupCommandPath) -or [string]::IsNullOrWhiteSpace($healthCommandPath) -or [string]::IsNullOrWhiteSpace($bootstrapCommandPath)) {
        throw "managed_wsl2_runtime_artifact_bootstrap_command_missing|Managed WSL2 runtime artifact inventory requires logs, backup, and bootstrap command paths."
    }
    if ([string]::IsNullOrWhiteSpace($stopCommandPath) -or [string]::IsNullOrWhiteSpace($restartCommandPath)) {
        throw "managed_wsl2_runtime_artifact_start_command_missing|Managed WSL2 runtime artifact inventory requires stop and restart command paths."
    }
    $runtimeExecutablePath = Assert-ImmoAppManagedRuntimeExistingFile -Path $runtimeExecutablePath -Label "runtime_executable_path" -AllowTestOnlyPath:$AllowTestOnlyPath
    $composeExecutablePath = Assert-ImmoAppManagedRuntimeExistingFile -Path $composeExecutablePath -Label "compose_executable_path" -AllowTestOnlyPath:$AllowTestOnlyPath
    $startCommandPath = Assert-ImmoAppManagedRuntimeExistingFile -Path $startCommandPath -Label "start_command_path" -AllowTestOnlyPath:$AllowTestOnlyPath
    $statusCommandPath = Assert-ImmoAppManagedRuntimeExistingFile -Path $statusCommandPath -Label "status_command_path" -AllowTestOnlyPath:$AllowTestOnlyPath
    $logsCommandPath = Assert-ImmoAppManagedRuntimeExistingFile -Path $logsCommandPath -Label "logs_command_path" -AllowTestOnlyPath:$AllowTestOnlyPath
    $backupCommandPath = Assert-ImmoAppManagedRuntimeExistingFile -Path $backupCommandPath -Label "backup_command_path" -AllowTestOnlyPath:$AllowTestOnlyPath
    $healthCommandPath = Assert-ImmoAppManagedRuntimeExistingFile -Path $healthCommandPath -Label "health_command_path" -AllowTestOnlyPath:$AllowTestOnlyPath
    $stopCommandPath = Assert-ImmoAppManagedRuntimeExistingFile -Path $stopCommandPath -Label "stop_command_path" -AllowTestOnlyPath:$AllowTestOnlyPath
    $restartCommandPath = Assert-ImmoAppManagedRuntimeExistingFile -Path $restartCommandPath -Label "restart_command_path" -AllowTestOnlyPath:$AllowTestOnlyPath
    $bootstrapCommandPath = Assert-ImmoAppManagedRuntimeExistingFile -Path $bootstrapCommandPath -Label "bootstrap_command_path" -AllowTestOnlyPath:$AllowTestOnlyPath
    Assert-ImmoAppProofOnlyPathApproved -Path $runtimeExecutablePath -Roots @($artifactRoot) -Label "runtime_executable_path"
    Assert-ImmoAppProofOnlyPathApproved -Path $composeExecutablePath -Roots @($artifactRoot) -Label "compose_executable_path"
    Assert-ImmoAppProofOnlyPathApproved -Path $startCommandPath -Roots @($artifactRoot) -Label "start_command_path"
    Assert-ImmoAppProofOnlyPathApproved -Path $statusCommandPath -Roots @($artifactRoot) -Label "status_command_path"
    Assert-ImmoAppProofOnlyPathApproved -Path $logsCommandPath -Roots @($artifactRoot) -Label "logs_command_path"
    Assert-ImmoAppProofOnlyPathApproved -Path $backupCommandPath -Roots @($artifactRoot) -Label "backup_command_path"
    Assert-ImmoAppProofOnlyPathApproved -Path $healthCommandPath -Roots @($artifactRoot) -Label "health_command_path"
    Assert-ImmoAppProofOnlyPathApproved -Path $stopCommandPath -Roots @($artifactRoot) -Label "stop_command_path"
    Assert-ImmoAppProofOnlyPathApproved -Path $restartCommandPath -Roots @($artifactRoot) -Label "restart_command_path"
    Assert-ImmoAppProofOnlyPathApproved -Path $bootstrapCommandPath -Roots @($artifactRoot) -Label "bootstrap_command_path"

    return [ordered]@{
        artifact_root = $artifactRoot
        artifact_tree_sha256 = [string]$treeInventory.sha256
        file_count = [int]$treeInventory.file_count
        total_bytes = [int64]$treeInventory.total_bytes
        runtime_executable_path = $runtimeExecutablePath
        compose_executable_path = $composeExecutablePath
        start_command_path = $startCommandPath
        status_command_path = $statusCommandPath
        health_command_path = $healthCommandPath
        logs_command_path = $logsCommandPath
        backup_command_path = $backupCommandPath
        stop_command_path = $stopCommandPath
        restart_command_path = $restartCommandPath
        bootstrap_command_path = $bootstrapCommandPath
    }
}

function Get-ImmoAppForbiddenRuntimePackageReason {
    param([Parameter(Mandatory = $true)][string]$RelativePath)
    $lower = $RelativePath.Replace("/", "\").ToLowerInvariant()
    $parts = @($lower.Split("\") | Where-Object { $_ })
    foreach ($segment in @(
        ".git",
        ".tmp",
        "tests",
        "test",
        "docs",
        "e2e",
        "scripts",
        "__pycache__",
        "pgdata",
        "postgres",
        "minio",
        "secrets",
        "credentials",
        "tokens",
        "dumps"
    )) {
        if ($parts -contains $segment) { return "forbidden_runtime_package_path" }
    }
    $fileName = [System.IO.Path]::GetFileName($lower)
    if ($fileName -in @(".env", "id_rsa", "id_dsa", "id_ed25519", "config")) {
        if ($parts -contains "kube" -or $fileName -ne "config") {
            return "forbidden_sensitive_file"
        }
    }
    if ($fileName.StartsWith(".env")) {
        return "forbidden_sensitive_file"
    }
    if ($lower -match "\.(env|pem|key|pfx|p12|dump|bak|sql|sqlite|db|mdf|ldf)$") {
        return "forbidden_sensitive_extension"
    }
    if ($lower -match "(secret|password|token|credential|private[_-]?key)") {
        return "forbidden_sensitive_name"
    }
    return ""
}

function Get-ImmoAppSafeZipInventory {
    param(
        [Parameter(Mandatory = $true)][string]$ArtifactPath,
        [int]$MaxFileCount = 20000,
        [int64]$MaxTotalBytes = 2147483648,
        [int64]$MaxSingleFileBytes = 536870912,
        [double]$MaxCompressionRatio = 100.0
    )
    if (-not (Test-Path -LiteralPath $ArtifactPath -PathType Leaf)) {
        throw "managed_runtime_vendor_provenance_missing|Vendor runtime artifact does not exist: $ArtifactPath"
    }
    if (Test-ImmoAppPathHasReparsePoint -Path $ArtifactPath) {
        throw "managed_runtime_vendor_provenance_invalid|Vendor runtime artifact contains a reparse point, symlink, or junction: $ArtifactPath"
    }

    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem

    $tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("immoapp_vendor_runtime_" + [System.Guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Path $tempRoot -Force | Out-Null
    $seen = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::OrdinalIgnoreCase)
    $fileCount = 0
    $stream = $null
    $archive = $null
    try {
        $stream = [System.IO.File]::OpenRead([System.IO.Path]::GetFullPath($ArtifactPath))
        $archive = [System.IO.Compression.ZipArchive]::new($stream, [System.IO.Compression.ZipArchiveMode]::Read)
        $totalUncompressedBytes = 0L
        foreach ($entry in $archive.Entries) {
            $relative = ([string]$entry.FullName).Replace("\", "/")
            if ([string]::IsNullOrWhiteSpace($relative) -or $relative.EndsWith("/")) {
                continue
            }
            if (($fileCount + 1) -gt $MaxFileCount) {
                throw "managed_runtime_vendor_zip_too_many_files|Vendor runtime ZIP exceeds max file count: $MaxFileCount"
            }
            if ([int64]$entry.Length -gt $MaxSingleFileBytes) {
                throw "managed_runtime_vendor_zip_file_too_large|Vendor runtime ZIP entry exceeds max file size: $relative"
            }
            $totalUncompressedBytes += [int64]$entry.Length
            if ($totalUncompressedBytes -gt $MaxTotalBytes) {
                throw "managed_runtime_vendor_zip_total_bytes_exceeded|Vendor runtime ZIP exceeds max extracted bytes: $MaxTotalBytes"
            }
            $compressedLength = [int64]$entry.CompressedLength
            if ($compressedLength -le 0 -and [int64]$entry.Length -gt 0) {
                throw "managed_runtime_vendor_zip_suspicious_compression_ratio|Vendor runtime ZIP entry has invalid compressed size: $relative"
            }
            if ($compressedLength -gt 0) {
                $ratio = [double]$entry.Length / [double]$compressedLength
                if ($ratio -gt $MaxCompressionRatio) {
                    throw "managed_runtime_vendor_zip_suspicious_compression_ratio|Vendor runtime ZIP entry exceeds max compression ratio: $relative"
                }
            }
            if (Test-ImmoAppUnsafeArchivePath -RelativePath $relative) {
                throw "managed_runtime_vendor_zip_unsafe_path|Vendor runtime ZIP contains unsafe entry path: $relative"
            }
            if (-not $seen.Add($relative)) {
                throw "managed_runtime_vendor_zip_duplicate_entry|Vendor runtime ZIP contains duplicate entry path: $relative"
            }
            $forbiddenReason = Get-ImmoAppForbiddenRuntimePackageReason -RelativePath $relative
            if (-not [string]::IsNullOrWhiteSpace($forbiddenReason)) {
                throw "managed_runtime_vendor_zip_forbidden_content|Vendor runtime ZIP contains forbidden content: $relative ($forbiddenReason)"
            }
            $destination = [System.IO.Path]::GetFullPath((Join-Path $tempRoot ($relative.Replace("/", [System.IO.Path]::DirectorySeparatorChar))))
            if (-not (Test-ImmoAppPathUnderRoot -Root $tempRoot -Path $destination)) {
                throw "managed_runtime_vendor_zip_unsafe_path|Vendor runtime ZIP entry resolves outside extraction root: $relative"
            }
            $parent = Split-Path -Parent $destination
            if ($parent -and -not (Test-Path -LiteralPath $parent)) {
                New-Item -ItemType Directory -Path $parent -Force | Out-Null
            }
            $entryStream = $entry.Open()
            try {
                $fileStream = [System.IO.File]::Open($destination, [System.IO.FileMode]::CreateNew)
                try {
                    $entryStream.CopyTo($fileStream)
                }
                finally {
                    $fileStream.Dispose()
                }
            }
            finally {
                $entryStream.Dispose()
            }
            if (Test-ImmoAppPathHasReparsePoint -Path $destination) {
                throw "managed_runtime_vendor_zip_reparse_entry|Vendor runtime ZIP extracted a reparse point: $relative"
            }
            $fileCount += 1
        }
        if ($fileCount -le 0) {
            throw "managed_runtime_vendor_zip_empty|Vendor runtime ZIP contains no files."
        }
        return Get-ImmoAppStrictRuntimeTreeInventory -Root $tempRoot -RequireNonEmpty
    }
    finally {
        if ($null -ne $archive) { $archive.Dispose() }
        if ($null -ne $stream) { $stream.Dispose() }
        if (Test-Path -LiteralPath $tempRoot) {
            Remove-Item -LiteralPath $tempRoot -Recurse -Force
        }
    }
}

function Get-ImmoAppSafeZipInventorySha256 {
    param([Parameter(Mandatory = $true)][string]$ArtifactPath)
    return [string](Get-ImmoAppSafeZipInventory -ArtifactPath $ArtifactPath).sha256
}

function Assert-ImmoAppManagedRuntimeVendorProvenance {
    param(
        [Parameter(Mandatory = $true)][string]$ProvenancePath,
        [string]$ExpectedSourceCommitSha = "",
        [string]$ExpectedExtractedInventorySha256 = "",
        [switch]$AllowNonCanonicalRoot
    )
    $paths = if ($AllowNonCanonicalRoot) { Get-ImmoAppRuntimePaths } else { Get-ImmoAppCanonicalRuntimePaths }
    $runtimeRoot = [System.IO.Path]::GetFullPath($paths.RuntimeRoot)
    $configRoot = [System.IO.Path]::GetFullPath($paths.ConfigRoot)
    $provenanceFull = [System.IO.Path]::GetFullPath($ProvenancePath)
    if (-not (Test-Path -LiteralPath $provenanceFull -PathType Leaf)) {
        throw "managed_runtime_vendor_provenance_missing|Vendor provenance manifest does not exist: $provenanceFull"
    }
    if (
        -not (Test-ImmoAppPathUnderRoot -Root $runtimeRoot -Path $provenanceFull) -and
        -not (Test-ImmoAppPathUnderRoot -Root $configRoot -Path $provenanceFull)
    ) {
        throw "managed_runtime_vendor_provenance_invalid|Vendor provenance manifest must be under approved runtime or config root: $provenanceFull"
    }
    if (Test-ImmoAppPathHasReparsePoint -Path $provenanceFull) {
        throw "managed_runtime_vendor_provenance_invalid|Vendor provenance manifest contains a reparse point, symlink, or junction: $provenanceFull"
    }
    if (
        -not (Test-ImmoAppResolvedPathUnderRoot -Root $runtimeRoot -Path $provenanceFull) -and
        -not (Test-ImmoAppResolvedPathUnderRoot -Root $configRoot -Path $provenanceFull)
    ) {
        throw "managed_runtime_vendor_provenance_invalid|Vendor provenance manifest resolves outside approved runtime or config root: $provenanceFull"
    }
    $manifest = Get-Content -LiteralPath $provenanceFull -Raw | ConvertFrom-Json
    Assert-ImmoAppNoSensitiveObjectFields -Node $manifest -Path "vendor_provenance"
    if ([string]$manifest.kind -ne "immoapp_managed_runtime_vendor_provenance") {
        throw "managed_runtime_vendor_provenance_invalid|Vendor provenance kind is invalid."
    }
    if ([int]$manifest.schema_version -ne 1) {
        throw "managed_runtime_vendor_provenance_invalid|Vendor provenance schema_version must be 1."
    }
    foreach ($required in @("vendor_name", "runtime_name", "runtime_version", "runtime_license", "artifact_kind", "artifact_path", "artifact_sha256", "artifact_bytes", "extracted_inventory_sha256", "approval_reason", "source_commit_sha", "approved_by", "approved_at_utc", "license_review_status")) {
        $value = [string](Get-ImmoAppObjectValue -Data $manifest -Name $required)
        if ([string]::IsNullOrWhiteSpace($value)) {
            throw "managed_runtime_vendor_provenance_invalid|Vendor provenance is missing required field '$required'."
        }
    }
    if ([string]$manifest.artifact_kind -ne "zip") {
        throw "managed_runtime_vendor_provenance_invalid|Vendor provenance artifact_kind must be zip."
    }
    if ($manifest.license_distribution_allowed -ne $true) {
        throw "managed_runtime_vendor_license_not_approved|Vendor provenance must record license_distribution_allowed=true."
    }
    if ([string]$manifest.license_review_status -ne "approved") {
        throw "managed_runtime_vendor_license_not_approved|Vendor provenance license_review_status must be approved."
    }
    $sourceUrl = [string](Get-ImmoAppObjectValue -Data $manifest -Name "runtime_source_url")
    $internalRef = [string](Get-ImmoAppObjectValue -Data $manifest -Name "internal_source_reference")
    if ([string]::IsNullOrWhiteSpace($sourceUrl) -and [string]::IsNullOrWhiteSpace($internalRef)) {
        throw "managed_runtime_vendor_provenance_invalid|Vendor provenance must include runtime_source_url or internal_source_reference."
    }
    if ($manifest.approved_by_immoapp -ne $true) {
        throw "managed_runtime_vendor_not_approved|Vendor provenance must be approved_by_immoapp=true."
    }
    $sourceCommit = [string]$manifest.source_commit_sha
    if ($sourceCommit -notmatch "^[0-9a-f]{40}$") {
        throw "managed_runtime_vendor_provenance_invalid|Vendor provenance source_commit_sha must be a 40-character lowercase git SHA."
    }
    if (-not [string]::IsNullOrWhiteSpace($ExpectedSourceCommitSha) -and $sourceCommit -ne $ExpectedSourceCommitSha) {
        throw "managed_runtime_vendor_provenance_invalid|Vendor provenance source_commit_sha does not match the expected release commit."
    }
    $artifactPath = [System.IO.Path]::GetFullPath([string]$manifest.artifact_path)
    if (-not (Test-Path -LiteralPath $artifactPath -PathType Leaf)) {
        throw "managed_runtime_vendor_provenance_missing|Vendor runtime artifact does not exist: $artifactPath"
    }
    if (Test-ImmoAppPathHasReparsePoint -Path $artifactPath) {
        throw "managed_runtime_vendor_provenance_invalid|Vendor runtime artifact contains a reparse point, symlink, or junction: $artifactPath"
    }
    if (-not (Test-ImmoAppResolvedPathUnderRoot -Root $runtimeRoot -Path $artifactPath) -and -not $AllowNonCanonicalRoot) {
        throw "managed_runtime_vendor_provenance_invalid|Vendor runtime artifact resolves outside canonical runtime root: $artifactPath"
    }
    $actualBytes = [int64](Get-Item -LiteralPath $artifactPath).Length
    if ($actualBytes -ne [int64]$manifest.artifact_bytes) {
        throw "managed_runtime_vendor_artifact_hash_mismatch|Vendor runtime artifact byte size does not match provenance."
    }
    $actualSha = Get-ImmoAppFileSha256 -Path $artifactPath
    if ($actualSha -ne [string]$manifest.artifact_sha256) {
        throw "managed_runtime_vendor_artifact_hash_mismatch|Vendor runtime artifact SHA-256 does not match provenance."
    }
    if ([string]$manifest.extracted_inventory_sha256 -notmatch "^[0-9a-f]{64}$") {
        throw "managed_runtime_vendor_provenance_invalid|Vendor provenance extracted_inventory_sha256 must be 64 lowercase hex characters."
    }
    $actualZipInventory = Get-ImmoAppSafeZipInventory -ArtifactPath $artifactPath
    $actualExtractedInventorySha = [string]$actualZipInventory.sha256
    if ($actualExtractedInventorySha -ne [string]$manifest.extracted_inventory_sha256) {
        throw "managed_runtime_vendor_inventory_hash_mismatch|Vendor runtime artifact extracted inventory SHA-256 does not match provenance."
    }
    if (-not [string]::IsNullOrWhiteSpace($ExpectedExtractedInventorySha256) -and [string]$manifest.extracted_inventory_sha256 -ne $ExpectedExtractedInventorySha256) {
        throw "managed_runtime_vendor_inventory_hash_mismatch|Vendor extracted inventory SHA-256 does not match the staged runtime tree."
    }
    return [ordered]@{
        path = $provenanceFull
        sha256 = Get-ImmoAppFileSha256 -Path $provenanceFull
        manifest = $manifest
        zip_inventory = $actualZipInventory
    }
}

function Assert-ImmoAppLowerHexSha256 {
    param(
        [Parameter(Mandatory = $true)][string]$Value,
        [string]$Name = "sha256"
    )
    if ($Value -notmatch "^[0-9a-f]{64}$") {
        throw "invalid_provider_config|$Name must be 64 lowercase hex characters."
    }
}

function Assert-ImmoAppLowerGitSha {
    param(
        [Parameter(Mandatory = $true)][string]$Value,
        [string]$Name = "source_commit_sha"
    )
    if ($Value -notmatch "^[0-9a-f]{40}$") {
        throw "managed_runtime_missing_source_provenance|$Name must be a 40-character lowercase git SHA."
    }
}

function Get-ImmoAppRelativePathUnderRoot {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string]$Path
    )
    $rootFull = [System.IO.Path]::GetFullPath($Root).TrimEnd("\", "/")
    $pathFull = [System.IO.Path]::GetFullPath($Path)
    $separator = [System.IO.Path]::DirectorySeparatorChar
    if ($pathFull.Equals($rootFull, [System.StringComparison]::OrdinalIgnoreCase)) {
        return ""
    }
    if ($pathFull.StartsWith($rootFull + $separator, [System.StringComparison]::OrdinalIgnoreCase)) {
        return $pathFull.Substring($rootFull.Length + 1).Replace("\", "/")
    }
    return $pathFull.Replace("\", "/")
}

function Get-ImmoAppInventoryFileEntry {
    param(
        [Parameter(Mandatory = $true)]$Inventory,
        [Parameter(Mandatory = $true)][string]$RelativePath
    )
    $normalized = $RelativePath.Replace("\", "/")
    foreach ($entry in @($Inventory.files)) {
        if ([string]$entry.path -eq $normalized) {
            return $entry
        }
    }
    return $null
}

function Assert-ImmoAppInstalledFileMatchesInventory {
    param(
        [Parameter(Mandatory = $true)][string]$InstallRoot,
        [Parameter(Mandatory = $true)][string]$InstalledPath,
        [Parameter(Mandatory = $true)]$Inventory,
        [Parameter(Mandatory = $true)][string]$CriticalPath,
        [Parameter(Mandatory = $true)][string]$Label
    )
    $relative = Get-ImmoAppRelativePathUnderRoot -Root $InstallRoot -Path $InstalledPath
    if ($relative -ne $CriticalPath) {
        throw "managed_runtime_missing_inventory|$Label must match inventory critical executable path '$CriticalPath'. actual=$relative"
    }
    $entry = Get-ImmoAppInventoryFileEntry -Inventory $Inventory -RelativePath $relative
    if ($null -eq $entry) {
        throw "managed_runtime_missing_inventory|$Label is not listed in package inventory files: $relative"
    }
    $actualSha = Get-ImmoAppFileSha256 -Path $InstalledPath
    if ($actualSha -ne [string]$entry.sha256) {
        throw "managed_runtime_installed_file_hash_mismatch|$Label hash does not match package inventory for $relative."
    }
}

function Assert-ImmoAppManagedRuntimePackageInventoryReady {
    param(
        [Parameter(Mandatory = $true)]$Inventory,
        [string]$ExpectedPackageSha256 = "",
        [Parameter(Mandatory = $true)][string]$ExpectedSourceCommitSha,
        [Parameter(Mandatory = $true)][string]$PackageInventoryPath,
        [Parameter(Mandatory = $true)][string]$RuntimeExecutablePath,
        [string]$ComposeExecutablePath = "",
        [Parameter(Mandatory = $true)][string]$InstallRoot,
        [Parameter(Mandatory = $true)]$RuntimePaths
    )
    if ([string](Get-ImmoAppObjectValue -Data $Inventory -Name "kind") -ne "immoapp_managed_hub_runtime_package_inventory") {
        throw "invalid_provider_config|Package inventory kind must be immoapp_managed_hub_runtime_package_inventory."
    }
    if ([int](Get-ImmoAppObjectValue -Data $Inventory -Name "schema_version") -ne 2) {
        throw "managed_runtime_missing_inventory|Production package inventory schema_version must be 2."
    }
    if ([string](Get-ImmoAppObjectValue -Data $Inventory -Name "proof_result") -ne "GO") {
        throw "managed_runtime_missing_inventory|Package inventory proof_result must be GO for production managed runtime."
    }
    if ((Get-ImmoAppObjectValue -Data $Inventory -Name "proof_only") -eq $true) {
        throw "managed_runtime_proof_only|Package inventory is proof_only and cannot be agency-ready."
    }
    if ((Get-ImmoAppObjectValue -Data $Inventory -Name "source_tree_clean") -ne $true) {
        throw "managed_runtime_dirty_source_tree|Package inventory source_tree_clean must be true for agency-ready runtime."
    }
    if ((Get-ImmoAppObjectValue -Data $Inventory -Name "source_commit_override") -eq $true) {
        throw "managed_runtime_source_commit_override|Package inventory source_commit_override must be false for agency-ready runtime."
    }
    if ([int](Get-ImmoAppObjectValue -Data $Inventory -Name "dirty_files_summary_count") -ne 0) {
        throw "managed_runtime_dirty_source_tree|Package inventory dirty_files_summary_count must be zero for agency-ready runtime."
    }
    $runtimeSourceOrigin = [string](Get-ImmoAppObjectValue -Data $Inventory -Name "runtime_source_origin")
    if ($runtimeSourceOrigin -ne "repo") {
        if ($runtimeSourceOrigin -ne "external_artifact") {
            throw "managed_runtime_external_artifact_requires_vendor_provenance|External runtime artifacts require a vendor provenance manifest before agency readiness."
        }
        $vendorProvenancePath = [string](Get-ImmoAppObjectValue -Data $Inventory -Name "vendor_provenance_path")
        if ([string]::IsNullOrWhiteSpace($vendorProvenancePath)) {
            throw "managed_runtime_external_artifact_requires_vendor_provenance|External runtime artifacts require a vendor provenance manifest before agency readiness."
        }
        Assert-ImmoAppManagedRuntimeVendorProvenance `
            -ProvenancePath $vendorProvenancePath `
            -ExpectedSourceCommitSha $ExpectedSourceCommitSha `
            -ExpectedExtractedInventorySha256 ([string](Get-ImmoAppObjectValue -Data $Inventory -Name "extracted_inventory_sha256")) | Out-Null
    }
    $forbidden = @(Get-ImmoAppObjectValue -Data $Inventory -Name "forbidden_matches")
    if ($forbidden.Count -gt 0) {
        throw "managed_runtime_inventory_forbidden_content|Package inventory contains forbidden runtime package content."
    }
    if ([int](Get-ImmoAppObjectValue -Data $Inventory -Name "file_count") -le 0 -or [int64](Get-ImmoAppObjectValue -Data $Inventory -Name "total_bytes") -le 0) {
        throw "managed_runtime_missing_inventory|Package inventory must contain at least one file and non-zero bytes."
    }
    if ([int](Get-ImmoAppObjectValue -Data $Inventory -Name "package_file_count") -le 0 -or [int64](Get-ImmoAppObjectValue -Data $Inventory -Name "package_bytes") -le 0) {
        throw "managed_runtime_missing_inventory|Package inventory package_file_count and package_bytes must be greater than zero."
    }
    $inventoryPackageSha = [string](Get-ImmoAppObjectValue -Data $Inventory -Name "package_sha256")
    Assert-ImmoAppLowerHexSha256 -Value $inventoryPackageSha -Name "package_sha256"
    if (-not [string]::IsNullOrWhiteSpace($ExpectedPackageSha256) -and $inventoryPackageSha -ne $ExpectedPackageSha256) {
        throw "managed_runtime_inventory_hash_mismatch|Package inventory package_sha256 does not match provider package_sha256."
    }
    Assert-ImmoAppLowerGitSha -Value $ExpectedSourceCommitSha -Name "source_commit_sha"
    $inventorySourceCommitSha = [string](Get-ImmoAppObjectValue -Data $Inventory -Name "source_commit_sha")
    Assert-ImmoAppLowerGitSha -Value $inventorySourceCommitSha -Name "inventory.source_commit_sha"
    if ($inventorySourceCommitSha -ne $ExpectedSourceCommitSha) {
        throw "invalid_provider_config|Package inventory source_commit_sha does not match provider source_commit_sha."
    }
    $packagePath = [string](Get-ImmoAppObjectValue -Data $Inventory -Name "package_path")
    if ([string]::IsNullOrWhiteSpace($packagePath) -or -not (Test-Path -LiteralPath $packagePath)) {
        throw "managed_runtime_package_missing|Package inventory package_path is missing or does not exist."
    }
    if (
        -not (Test-ImmoAppPathUnderRoot -Root $RuntimePaths.RuntimeRoot -Path $packagePath) -and
        -not (Test-ImmoAppPathUnderRoot -Root $RuntimePaths.ConfigRoot -Path $packagePath)
    ) {
        throw "managed_runtime_outside_approved_root|Package artifact must live under approved runtime or config root: $packagePath"
    }
    if (Test-ImmoAppPathHasReparsePoint -Path $packagePath) {
        throw "managed_runtime_reparse_point_not_allowed|Package artifact contains a reparse point: $packagePath"
    }
    if (
        -not (Test-ImmoAppResolvedPathUnderRoot -Root $RuntimePaths.RuntimeRoot -Path $packagePath) -and
        -not (Test-ImmoAppResolvedPathUnderRoot -Root $RuntimePaths.ConfigRoot -Path $packagePath)
    ) {
        throw "managed_runtime_resolved_path_outside_approved_root|Package artifact resolves outside approved runtime or config root: $packagePath"
    }
    $actualPackageSha = Get-ImmoAppFileSha256 -Path $packagePath
    if ($actualPackageSha -ne $inventoryPackageSha) {
        throw "managed_runtime_package_hash_mismatch|Package artifact SHA-256 does not match package inventory."
    }
    if (
        -not (Test-ImmoAppPathUnderRoot -Root $RuntimePaths.RuntimeRoot -Path $PackageInventoryPath) -and
        -not (Test-ImmoAppPathUnderRoot -Root $RuntimePaths.ConfigRoot -Path $PackageInventoryPath)
    ) {
        throw "managed_runtime_outside_approved_root|PackageInventoryJson must be under approved ProgramData runtime or config root: $PackageInventoryPath"
    }
    if (Test-ImmoAppPathHasReparsePoint -Path $PackageInventoryPath) {
        throw "managed_runtime_reparse_point_not_allowed|PackageInventoryJson contains a reparse point, symlink, or junction: $PackageInventoryPath"
    }
    if (
        -not (Test-ImmoAppResolvedPathUnderRoot -Root $RuntimePaths.RuntimeRoot -Path $PackageInventoryPath) -and
        -not (Test-ImmoAppResolvedPathUnderRoot -Root $RuntimePaths.ConfigRoot -Path $PackageInventoryPath)
    ) {
        throw "managed_runtime_resolved_path_outside_approved_root|PackageInventoryJson resolves outside approved ProgramData runtime or config root: $PackageInventoryPath"
    }
    $critical = Get-ImmoAppObjectValue -Data $Inventory -Name "critical_executables"
    $runtimeCritical = [string](Get-ImmoAppObjectValue -Data $critical -Name "runtime_executable_relative_path")
    $composeCritical = [string](Get-ImmoAppObjectValue -Data $critical -Name "compose_executable_relative_path")
    if ([string]::IsNullOrWhiteSpace($runtimeCritical) -or [string]::IsNullOrWhiteSpace($composeCritical)) {
        throw "managed_runtime_missing_inventory|Package inventory critical_executables must include runtime and compose relative paths."
    }
    Assert-ImmoAppInstalledFileMatchesInventory -InstallRoot $InstallRoot -InstalledPath $RuntimeExecutablePath -Inventory $Inventory -CriticalPath $runtimeCritical -Label "Runtime executable"
    if ([string]::IsNullOrWhiteSpace($ComposeExecutablePath)) {
        Assert-ImmoAppInstalledFileMatchesInventory -InstallRoot $InstallRoot -InstalledPath $RuntimeExecutablePath -Inventory $Inventory -CriticalPath $composeCritical -Label "Compose executable"
    }
    else {
        Assert-ImmoAppInstalledFileMatchesInventory -InstallRoot $InstallRoot -InstalledPath $ComposeExecutablePath -Inventory $Inventory -CriticalPath $composeCritical -Label "Compose executable"
    }
}

function Assert-ImmoAppManagedRuntimePathAllowed {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Label,
        [switch]$AllowTestOnlyPath
    )
    $full = [System.IO.Path]::GetFullPath($Path)
    $repoRoot = (Get-ImmoAppRepoRoot).Path
    $tmpRoot = Join-Path $repoRoot ".tmp"
    $downloads = Join-Path ([Environment]::GetFolderPath("UserProfile")) "Downloads"
    if (-not $AllowTestOnlyPath) {
        foreach ($blocked in @($repoRoot, $tmpRoot, $downloads)) {
            if ((Test-Path -LiteralPath $blocked) -and (Test-ImmoAppPathUnderRoot -Root $blocked -Path $full)) {
                throw "$Label cannot be under repo, .tmp, or Downloads for managed-runtime proof: $full"
            }
        }
    }
    return $full
}

function Assert-ImmoAppManagedRuntimeNoReparseUnderRoot {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string]$Label
    )
    if (-not (Test-ImmoAppPathUnderRoot -Root $Root -Path $Path)) {
        throw "$Label must be under approved canonical ProgramData root ${Root}: $Path"
    }
    if (Test-ImmoAppPathHasReparsePoint -Path $Path) {
        throw "$Label contains a reparse point, symlink, or junction, which is not allowed for agency-ready runtime: $Path"
    }
    if (-not (Test-ImmoAppResolvedPathUnderRoot -Root $Root -Path $Path)) {
        throw "$Label resolves outside approved canonical ProgramData root ${Root}: $Path"
    }
}

function Test-ImmoAppPathUnderAnyApprovedRoot {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string[]]$Roots
    )
    foreach ($root in $Roots) {
        if (
            (Test-ImmoAppPathUnderRoot -Root $root -Path $Path) -and
            (Test-ImmoAppResolvedPathUnderRoot -Root $root -Path $Path)
        ) {
            return $true
        }
    }
    return $false
}

function Get-ImmoAppProofApprovedRoots {
    param(
        [Parameter(Mandatory = $true)]$CanonicalPaths,
        [Parameter(Mandatory = $true)]$ActivePaths,
        [Parameter(Mandatory = $true)][ValidateSet("runtime", "data", "logs", "config")][string]$Kind
    )
    $roots = New-Object System.Collections.Generic.List[string]
    if ($Kind -eq "runtime") {
        $roots.Add([string]$CanonicalPaths.RuntimeRoot)
    }
    elseif ($Kind -eq "data") {
        $roots.Add([string]$CanonicalPaths.DataRoot)
    }
    elseif ($Kind -eq "logs") {
        $roots.Add([string]$CanonicalPaths.LogsRoot)
    }
    elseif ($Kind -eq "config") {
        $roots.Add([string]$CanonicalPaths.ConfigRoot)
        $roots.Add([string]$CanonicalPaths.RuntimeRoot)
    }
    if ((Get-ImmoAppRuntimeRootSource) -eq "test_programdata_root") {
        if ($Kind -eq "runtime") {
            $roots.Add([string]$ActivePaths.RuntimeRoot)
        }
        elseif ($Kind -eq "data") {
            $roots.Add([string]$ActivePaths.DataRoot)
        }
        elseif ($Kind -eq "logs") {
            $roots.Add([string]$ActivePaths.LogsRoot)
        }
        elseif ($Kind -eq "config") {
            $roots.Add([string]$ActivePaths.ConfigRoot)
            $roots.Add([string]$ActivePaths.RuntimeRoot)
        }
    }
    return @($roots.ToArray() | Select-Object -Unique)
}

function Assert-ImmoAppProofOnlyPathApproved {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string[]]$Roots,
        [Parameter(Mandatory = $true)][string]$Label
    )
    if (Test-ImmoAppPathHasReparsePoint -Path $Path) {
        throw "$Label contains a reparse point, symlink, or junction: $Path"
    }
    if (-not (Test-ImmoAppPathUnderAnyApprovedRoot -Path $Path -Roots $Roots)) {
        throw "managed_runtime_proof_provider_path_not_approved|Proof-only provider $Label must be under canonical ProgramData runtime roots or the explicit test ProgramData root: $Path"
    }
}

function Assert-ImmoAppManagedRuntimeExistingFile {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Label,
        [switch]$AllowTestOnlyPath
    )
    $full = Assert-ImmoAppManagedRuntimePathAllowed -Path $Path -Label $Label -AllowTestOnlyPath:$AllowTestOnlyPath
    if (-not (Test-Path -LiteralPath $full)) {
        throw "$Label does not exist: $full"
    }
    $item = Get-Item -LiteralPath $full
    if ($item.PSIsContainer) {
        throw "$Label must be a file: $full"
    }
    if (Test-ImmoAppPathHasReparsePoint -Path $item.FullName) {
        throw "$Label contains a reparse point, symlink, or junction: $($item.FullName)"
    }
    return $item.FullName
}

function Assert-ImmoAppManagedRuntimeExistingDirectory {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Label,
        [switch]$AllowTestOnlyPath
    )
    $full = Assert-ImmoAppManagedRuntimePathAllowed -Path $Path -Label $Label -AllowTestOnlyPath:$AllowTestOnlyPath
    if (-not (Test-Path -LiteralPath $full)) {
        throw "$Label does not exist: $full"
    }
    $item = Get-Item -LiteralPath $full
    if (-not $item.PSIsContainer) {
        throw "$Label must be a directory: $full"
    }
    if (Test-ImmoAppPathHasReparsePoint -Path $item.FullName) {
        throw "$Label contains a reparse point, symlink, or junction: $($item.FullName)"
    }
    return $item.FullName
}

function Test-ImmoAppUserVisibleRuntimePath {
    param([string]$Path)
    $clean = $Path.ToLowerInvariant()
    return (
        $clean.EndsWith("docker desktop.exe") -or
        $clean.Contains("\docker\docker\") -or
        $clean.Contains("/docker/docker/")
    )
}

function Invoke-ImmoAppManagedRuntimeVersionCheck {
    param(
        [Parameter(Mandatory = $true)][string]$Command,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$Label
    )
    $output = & $Command @Arguments 2>$null
    if ($LASTEXITCODE -ne 0) {
        throw "$Label version check failed."
    }
    return (($output | Out-String).Trim())
}

function Invoke-ImmoAppManagedRuntimeProviderRegistration {
    param(
        [ValidateSet("managed_container_runtime", "managed_wsl2_container_runtime_candidate", "managed_wsl2_container_runtime_artifact")]
        [string]$RuntimeDependencyMode = "managed_container_runtime",
        [string]$RuntimeExecutablePath = "",
        [string]$ComposeExecutablePath = "",
        [string]$InstallRoot = "",
        [string]$DataRoot = "",
        [string]$LogsRoot = "",
        [string]$ManagedServiceName = "",
        [string]$PackageInventoryJson = "",
        [string]$RuntimeArtifactInventoryJson = "",
        [string]$WslPolicyJsonPath = "",
        [string]$WslConfigPlanJsonPath = "",
        [string]$SourceCommitSha = "",
        [string]$InstallerSha256 = "",
        [AllowNull()]$ProviderLock = $null,
        [bool]$WriteProvider = $true,
        [switch]$WhatIfMode,
        [switch]$ConfirmManagedRuntimeProof,
        [switch]$AllowTestOnlyPath
    )

    if (-not $ConfirmManagedRuntimeProof) {
        throw "Registering a managed Hub runtime provider requires -ConfirmManagedRuntimeProof."
    }
    if ($WriteProvider) {
        Assert-ImmoAppProviderMutationLockHeld -Lock $ProviderLock | Out-Null
    }

    $paths = Ensure-ImmoAppRuntimeLayout
    $canonicalPaths = Get-ImmoAppCanonicalRuntimePaths
    $providerPath = Get-ImmoAppHubRuntimeProviderConfigPath

    if ($RuntimeDependencyMode -eq "managed_wsl2_container_runtime_candidate") {
        if ([string]::IsNullOrWhiteSpace($WslPolicyJsonPath)) {
            throw "wsl_policy_json_missing|WSL2 runtime candidate registration requires -WslPolicyJsonPath."
        }
        if ([string]::IsNullOrWhiteSpace($WslConfigPlanJsonPath)) {
            throw "wsl_config_plan_json_missing|WSL2 runtime candidate registration requires -WslConfigPlanJsonPath."
        }
        $policyPath = Assert-ImmoAppManagedRuntimeExistingFile -Path $WslPolicyJsonPath -Label "WslPolicyJsonPath" -AllowTestOnlyPath:$AllowTestOnlyPath
        $configPlanPath = Assert-ImmoAppManagedRuntimeExistingFile -Path $WslConfigPlanJsonPath -Label "WslConfigPlanJsonPath" -AllowTestOnlyPath:$AllowTestOnlyPath
        $policyRoots = @(
            (Get-ImmoAppProofApprovedRoots -CanonicalPaths $canonicalPaths -ActivePaths $paths -Kind "config") +
            (Get-ImmoAppProofApprovedRoots -CanonicalPaths $canonicalPaths -ActivePaths $paths -Kind "logs")
        ) | Select-Object -Unique
        Assert-ImmoAppProofOnlyPathApproved -Path $policyPath -Roots $policyRoots -Label "WslPolicyJsonPath"
        Assert-ImmoAppProofOnlyPathApproved -Path $configPlanPath -Roots $policyRoots -Label "WslConfigPlanJsonPath"
        $policySha = Get-ImmoAppFileSha256 -Path $policyPath
        $configPlanSha = Get-ImmoAppFileSha256 -Path $configPlanPath
        $policy = Get-Content -LiteralPath $policyPath -Raw | ConvertFrom-Json
        $configPlan = Get-Content -LiteralPath $configPlanPath -Raw | ConvertFrom-Json
        if ([string](Get-ImmoAppObjectValue -Data $policy -Name "kind") -ne "immoapp_managed_wsl2_runtime_policy") {
            throw "wsl_policy_invalid|WSL2 policy JSON has the wrong kind."
        }
        if ([int](Get-ImmoAppObjectValue -Data $policy -Name "schema_version") -ne 1) {
            throw "wsl_policy_invalid|WSL2 policy JSON has an unsupported schema_version."
        }
        if ([string](Get-ImmoAppObjectValue -Data $policy -Name "policy_result") -ne "GO") {
            throw "wsl_policy_not_go|WSL2 policy must be GO before candidate registration."
        }
        if ([double](Get-ImmoAppObjectValue -Data $policy -Name "total_memory_gb") -lt 8) {
            throw "machine_below_minimum_hub_ram|WSL2 policy cannot register Hub candidate below 8 GB RAM."
        }
        if ([string](Get-ImmoAppObjectValue -Data $policy -Name "global_wsl_config_scope") -ne "True") {
            throw "wsl_policy_invalid|WSL2 policy must record global_wsl_config_scope=true."
        }
        if ([string](Get-ImmoAppObjectValue -Data $policy -Name "cap_is_ceiling_not_reservation") -ne "True") {
            throw "wsl_policy_invalid|WSL2 policy must record cap_is_ceiling_not_reservation=true."
        }
        if ([string](Get-ImmoAppObjectValue -Data $configPlan -Name "kind") -ne "immoapp_managed_wsl2_runtime_config_plan") {
            throw "wsl_config_plan_invalid|WSL2 config plan JSON has the wrong kind."
        }
        if ([int](Get-ImmoAppObjectValue -Data $configPlan -Name "schema_version") -ne 1) {
            throw "wsl_config_plan_invalid|WSL2 config plan JSON has an unsupported schema_version."
        }
        if ([string](Get-ImmoAppObjectValue -Data $configPlan -Name "plan_result") -ne "GO") {
            throw "wsl_config_plan_not_go|WSL2 config plan must be GO before candidate registration."
        }
        $configPolicy = Get-ImmoAppObjectValue -Data $configPlan -Name "policy_json"
        if (
            [int](Get-ImmoAppObjectValue -Data $configPolicy -Name "planned_wsl_memory_gb") -ne [int](Get-ImmoAppObjectValue -Data $policy -Name "planned_wsl_memory_gb") -or
            [int](Get-ImmoAppObjectValue -Data $configPolicy -Name "planned_wsl_processors") -ne [int](Get-ImmoAppObjectValue -Data $policy -Name "planned_wsl_processors") -or
            [int](Get-ImmoAppObjectValue -Data $configPolicy -Name "planned_wsl_swap_gb") -ne [int](Get-ImmoAppObjectValue -Data $policy -Name "planned_wsl_swap_gb") -or
            [string](Get-ImmoAppObjectValue -Data $configPolicy -Name "planned_auto_memory_reclaim") -ne [string](Get-ImmoAppObjectValue -Data $policy -Name "planned_auto_memory_reclaim") -or
            [string](Get-ImmoAppObjectValue -Data $configPolicy -Name "selected_hub_runtime_profile") -ne [string](Get-ImmoAppObjectValue -Data $policy -Name "selected_hub_runtime_profile")
        ) {
            throw "wsl_config_plan_policy_mismatch|WSL2 config plan does not match the registered policy evidence."
        }

        Assert-ImmoAppCanonicalProviderConfigPathSafe -Path $providerPath -AllowNonCanonical | Out-Null
        if ($WriteProvider -and (Test-Path -LiteralPath $providerPath -PathType Leaf)) {
            try {
                $existingProvider = Get-Content -LiteralPath $providerPath -Raw | ConvertFrom-Json
                $existingProviderMode = [string](Get-ImmoAppObjectValue -Data $existingProvider -Name "provider_mode")
            }
            catch {
                $existingProviderMode = "unreadable"
            }
            if ($existingProviderMode -ne "managed_wsl2_container_runtime_candidate") {
                throw "existing_managed_runtime_provider_refuses_candidate_overwrite|WSL2 candidate registration refuses to overwrite existing provider mode: $existingProviderMode"
            }
        }
        $payload = [ordered]@{
            kind = "immoapp_hub_runtime_provider"
            schema_version = 1
            provider_mode = "managed_wsl2_container_runtime_candidate"
            runtime_dependency_mode = "managed_wsl2_container_runtime_candidate"
            runtime_provider = "wsl2"
            installed_by_immoapp = $false
            user_visible_runtime = $false
            proof_only = $true
            created_at_utc = (Get-Date).ToUniversalTime().ToString("o")
            wsl_policy_json_path = $policyPath
            wsl_policy_sha256 = $policySha
            wsl_config_plan_json_path = $configPlanPath
            wsl_config_plan_sha256 = $configPlanSha
            planned_wsl_memory_gb = [int](Get-ImmoAppObjectValue -Data $policy -Name "planned_wsl_memory_gb")
            planned_wsl_processors = [int](Get-ImmoAppObjectValue -Data $policy -Name "planned_wsl_processors")
            planned_wsl_swap_gb = [int](Get-ImmoAppObjectValue -Data $policy -Name "planned_wsl_swap_gb")
            planned_auto_memory_reclaim = [string](Get-ImmoAppObjectValue -Data $policy -Name "planned_auto_memory_reclaim")
            wsl_config_apply_performed = [bool](Get-ImmoAppObjectValue -Data $configPlan -Name "apply_performed")
            wsl_shutdown_required = [bool](Get-ImmoAppObjectValue -Data $configPlan -Name "wsl_shutdown_required")
            global_wsl_config_scope = $true
            agency_install_status = "NO_GO"
        }

        $providerWritten = $false
        $providerConfigSha256AfterWrite = ""
        if ($WriteProvider) {
            $safeWrite = Write-ImmoAppSafeJson -Path $providerPath -Payload $payload -ApprovedRoots @($paths.ConfigRoot) -Depth 8
            $providerConfigSha256AfterWrite = [string]$safeWrite.sha256
            $providerWritten = $true
        }

        return [ordered]@{
            kind = "immoapp_hub_runtime_provider_registration"
            schema_version = 1
            created_at_utc = (Get-Date).ToUniversalTime().ToString("o")
            provider_config_path = $providerPath
            proof_only = $true
            provider = $payload
            provider_config_sha256_after_write = $providerConfigSha256AfterWrite
            provider_lock_status = if ($WriteProvider) { "held" } elseif ($WhatIfMode) { "not_required_whatif" } else { "not_required_validation" }
            provider_write_status = if ($providerWritten) { "GO" } elseif ($WhatIfMode) { "not_written_whatif" } else { "not_written" }
            internal_proof_status = if ($providerWritten -or (-not $WhatIfMode)) { "GO" } else { "NO_GO" }
            agency_install_status = "NO_GO"
            proof_result = "NO-GO"
            reason_code = "managed_wsl2_runtime_artifact_missing"
        }
    }

    if ($RuntimeDependencyMode -eq "managed_wsl2_container_runtime_artifact") {
        if ([string]::IsNullOrWhiteSpace($WslPolicyJsonPath)) {
            throw "wsl_policy_json_missing|Managed WSL2 runtime artifact registration requires -WslPolicyJsonPath."
        }
        if ([string]::IsNullOrWhiteSpace($WslConfigPlanJsonPath)) {
            throw "wsl_config_plan_json_missing|Managed WSL2 runtime artifact registration requires -WslConfigPlanJsonPath."
        }
        if ([string]::IsNullOrWhiteSpace($RuntimeArtifactInventoryJson)) {
            throw "managed_wsl2_runtime_artifact_inventory_missing|Managed WSL2 runtime artifact registration requires -RuntimeArtifactInventoryJson."
        }
        $policyPath = Assert-ImmoAppManagedRuntimeExistingFile -Path $WslPolicyJsonPath -Label "WslPolicyJsonPath" -AllowTestOnlyPath:$AllowTestOnlyPath
        $configPlanPath = Assert-ImmoAppManagedRuntimeExistingFile -Path $WslConfigPlanJsonPath -Label "WslConfigPlanJsonPath" -AllowTestOnlyPath:$AllowTestOnlyPath
        $artifactInventoryPath = Assert-ImmoAppManagedRuntimeExistingFile -Path $RuntimeArtifactInventoryJson -Label "RuntimeArtifactInventoryJson" -AllowTestOnlyPath:$AllowTestOnlyPath
        $policyRoots = @(
            (Get-ImmoAppProofApprovedRoots -CanonicalPaths $canonicalPaths -ActivePaths $paths -Kind "config") +
            (Get-ImmoAppProofApprovedRoots -CanonicalPaths $canonicalPaths -ActivePaths $paths -Kind "logs")
        ) | Select-Object -Unique
        Assert-ImmoAppProofOnlyPathApproved -Path $policyPath -Roots $policyRoots -Label "WslPolicyJsonPath"
        Assert-ImmoAppProofOnlyPathApproved -Path $configPlanPath -Roots $policyRoots -Label "WslConfigPlanJsonPath"
        Assert-ImmoAppProofOnlyPathApproved -Path $artifactInventoryPath -Roots $policyRoots -Label "RuntimeArtifactInventoryJson"
        $policySha = Get-ImmoAppFileSha256 -Path $policyPath
        $configPlanSha = Get-ImmoAppFileSha256 -Path $configPlanPath
        $artifactInventorySha = Get-ImmoAppFileSha256 -Path $artifactInventoryPath
        $policy = Get-Content -LiteralPath $policyPath -Raw | ConvertFrom-Json
        $configPlan = Get-Content -LiteralPath $configPlanPath -Raw | ConvertFrom-Json
        $artifactInventory = Get-Content -LiteralPath $artifactInventoryPath -Raw | ConvertFrom-Json
        if ([string]::IsNullOrWhiteSpace($SourceCommitSha)) {
            $SourceCommitSha = [string](Get-ImmoAppObjectValue -Data $artifactInventory -Name "source_commit_sha")
        }
        if ([string](Get-ImmoAppObjectValue -Data $policy -Name "kind") -ne "immoapp_managed_wsl2_runtime_policy") {
            throw "wsl_policy_invalid|WSL2 policy JSON has the wrong kind."
        }
        if ([int](Get-ImmoAppObjectValue -Data $policy -Name "schema_version") -ne 1) {
            throw "wsl_policy_invalid|WSL2 policy JSON has an unsupported schema_version."
        }
        if ([string](Get-ImmoAppObjectValue -Data $policy -Name "policy_result") -ne "GO") {
            throw "wsl_policy_not_go|WSL2 policy must be GO before artifact registration."
        }
        if ([string](Get-ImmoAppObjectValue -Data $configPlan -Name "kind") -ne "immoapp_managed_wsl2_runtime_config_plan") {
            throw "wsl_config_plan_invalid|WSL2 config plan JSON has the wrong kind."
        }
        if ([int](Get-ImmoAppObjectValue -Data $configPlan -Name "schema_version") -ne 1) {
            throw "wsl_config_plan_invalid|WSL2 config plan JSON has an unsupported schema_version."
        }
        if ([string](Get-ImmoAppObjectValue -Data $configPlan -Name "plan_result") -ne "GO") {
            throw "wsl_config_plan_not_go|WSL2 config plan must be GO before artifact registration."
        }
        $configPolicy = Get-ImmoAppObjectValue -Data $configPlan -Name "policy_json"
        if (
            [int](Get-ImmoAppObjectValue -Data $configPolicy -Name "planned_wsl_memory_gb") -ne [int](Get-ImmoAppObjectValue -Data $policy -Name "planned_wsl_memory_gb") -or
            [int](Get-ImmoAppObjectValue -Data $configPolicy -Name "planned_wsl_processors") -ne [int](Get-ImmoAppObjectValue -Data $policy -Name "planned_wsl_processors") -or
            [int](Get-ImmoAppObjectValue -Data $configPolicy -Name "planned_wsl_swap_gb") -ne [int](Get-ImmoAppObjectValue -Data $policy -Name "planned_wsl_swap_gb") -or
            [string](Get-ImmoAppObjectValue -Data $configPolicy -Name "planned_auto_memory_reclaim") -ne [string](Get-ImmoAppObjectValue -Data $policy -Name "planned_auto_memory_reclaim") -or
            [string](Get-ImmoAppObjectValue -Data $configPolicy -Name "selected_hub_runtime_profile") -ne [string](Get-ImmoAppObjectValue -Data $policy -Name "selected_hub_runtime_profile")
        ) {
            throw "wsl_config_plan_policy_mismatch|WSL2 config plan does not match the registered policy evidence."
        }
        $artifactSummary = Assert-ImmoAppManagedWsl2RuntimeArtifactInventoryReady `
            -Inventory $artifactInventory `
            -ExpectedInventorySha256 $artifactInventorySha `
            -ExpectedSourceCommitSha $SourceCommitSha `
            -ArtifactInventoryPath $artifactInventoryPath `
            -AllowTestOnlyPath:$AllowTestOnlyPath

        Assert-ImmoAppCanonicalProviderConfigPathSafe -Path $providerPath -AllowNonCanonical | Out-Null
        if ($WriteProvider -and (Test-Path -LiteralPath $providerPath -PathType Leaf)) {
            try {
                $existingProvider = Get-Content -LiteralPath $providerPath -Raw | ConvertFrom-Json
                $existingProviderMode = [string](Get-ImmoAppObjectValue -Data $existingProvider -Name "provider_mode")
            }
            catch {
                $existingProviderMode = "unreadable"
            }
            if ($existingProviderMode -notin @("managed_wsl2_container_runtime_candidate", "managed_wsl2_container_runtime_artifact")) {
                throw "existing_managed_runtime_provider_refuses_wsl_artifact_overwrite|Managed WSL2 artifact registration refuses to overwrite existing provider mode: $existingProviderMode"
            }
        }
        $payload = [ordered]@{
            kind = "immoapp_hub_runtime_provider"
            schema_version = 1
            provider_mode = "managed_wsl2_container_runtime_artifact"
            runtime_dependency_mode = "managed_wsl2_container_runtime_artifact"
            runtime_provider = "wsl2"
            installed_by_immoapp = $true
            user_visible_runtime = $false
            proof_only = $true
            created_at_utc = (Get-Date).ToUniversalTime().ToString("o")
            source_commit_sha = $SourceCommitSha
            runtime_artifact_status = "GO"
            runtime_start_status = "NO-GO"
            runtime_artifact_root = [string]$artifactSummary.artifact_root
            runtime_artifact_tree_sha256 = [string]$artifactSummary.artifact_tree_sha256
            runtime_artifact_inventory_path = $artifactInventoryPath
            runtime_artifact_inventory_sha256 = $artifactInventorySha
            runtime_executable_path = [string]$artifactSummary.runtime_executable_path
            compose_executable_path = [string]$artifactSummary.compose_executable_path
            managed_runtime_command_path = [string]$artifactSummary.start_command_path
            managed_status_command_path = [string]$artifactSummary.status_command_path
            managed_health_command_path = [string]$artifactSummary.health_command_path
            managed_logs_command_path = [string]$artifactSummary.logs_command_path
            managed_backup_command_path = [string]$artifactSummary.backup_command_path
            managed_stop_command_path = [string]$artifactSummary.stop_command_path
            managed_restart_command_path = [string]$artifactSummary.restart_command_path
            managed_bootstrap_command_path = [string]$artifactSummary.bootstrap_command_path
            image_bundle_archive_path = Get-ImmoAppManagedWsl2ImageBundleArchivePath
            image_bundle_inventory_path = Get-ImmoAppManagedWsl2ImageBundleInventoryPath
            compose_payload_path = Get-ImmoAppManagedWsl2RuntimeComposePayloadPath
            compose_pull_policy = "never"
            required_compose_services = @(Get-ImmoAppManagedWsl2RuntimeRequiredComposeServices)
            expected_distro_name = "ImmoAppRuntime"
            wsl_policy_json_path = $policyPath
            wsl_policy_sha256 = $policySha
            wsl_config_plan_json_path = $configPlanPath
            wsl_config_plan_sha256 = $configPlanSha
            planned_wsl_memory_gb = [int](Get-ImmoAppObjectValue -Data $policy -Name "planned_wsl_memory_gb")
            planned_wsl_processors = [int](Get-ImmoAppObjectValue -Data $policy -Name "planned_wsl_processors")
            planned_wsl_swap_gb = [int](Get-ImmoAppObjectValue -Data $policy -Name "planned_wsl_swap_gb")
            planned_auto_memory_reclaim = [string](Get-ImmoAppObjectValue -Data $policy -Name "planned_auto_memory_reclaim")
            selected_hub_runtime_profile = [string](Get-ImmoAppObjectValue -Data $policy -Name "selected_hub_runtime_profile")
            agency_install_status = "NO_GO"
        }

        $providerWritten = $false
        $providerConfigSha256AfterWrite = ""
        if ($WriteProvider) {
            $safeWrite = Write-ImmoAppSafeJson -Path $providerPath -Payload $payload -ApprovedRoots @($paths.ConfigRoot) -Depth 10
            $providerConfigSha256AfterWrite = [string]$safeWrite.sha256
            $providerWritten = $true
        }

        return [ordered]@{
            kind = "immoapp_hub_runtime_provider_registration"
            schema_version = 1
            created_at_utc = (Get-Date).ToUniversalTime().ToString("o")
            provider_config_path = $providerPath
            proof_only = $true
            provider = $payload
            provider_config_sha256_after_write = $providerConfigSha256AfterWrite
            provider_lock_status = if ($WriteProvider) { "held" } elseif ($WhatIfMode) { "not_required_whatif" } else { "not_required_validation" }
            provider_write_status = if ($providerWritten) { "GO" } elseif ($WhatIfMode) { "not_written_whatif" } else { "not_written" }
            runtime_artifact_status = "GO"
            runtime_start_status = "NO-GO"
            internal_proof_status = if ($providerWritten -or (-not $WhatIfMode)) { "GO" } else { "NO_GO" }
            agency_install_status = "NO_GO"
            proof_result = "NO-GO"
            reason_code = "managed_wsl2_runtime_artifact_registered_start_not_proven"
        }
    }

    foreach ($required in @(
        @{ Name = "RuntimeExecutablePath"; Value = $RuntimeExecutablePath },
        @{ Name = "InstallRoot"; Value = $InstallRoot },
        @{ Name = "DataRoot"; Value = $DataRoot },
        @{ Name = "LogsRoot"; Value = $LogsRoot }
    )) {
        if ([string]::IsNullOrWhiteSpace([string]$required.Value)) {
            throw "invalid_provider_config|$($required.Name) is required for managed_container_runtime registration."
        }
    }

    $runtimePath = Assert-ImmoAppManagedRuntimeExistingFile -Path $RuntimeExecutablePath -Label "RuntimeExecutablePath" -AllowTestOnlyPath:$AllowTestOnlyPath
    if (Test-ImmoAppUserVisibleRuntimePath -Path $runtimePath) {
        throw "A user-visible Docker Desktop executable cannot be registered as an ImmoApp-managed runtime."
    }
    $installRootPath = Assert-ImmoAppManagedRuntimeExistingDirectory -Path $InstallRoot -Label "InstallRoot" -AllowTestOnlyPath:$AllowTestOnlyPath
    $dataRootPath = Assert-ImmoAppManagedRuntimeExistingDirectory -Path $DataRoot -Label "DataRoot" -AllowTestOnlyPath:$AllowTestOnlyPath
    $logsRootPath = Assert-ImmoAppManagedRuntimeExistingDirectory -Path $LogsRoot -Label "LogsRoot" -AllowTestOnlyPath:$AllowTestOnlyPath
    $composePath = ""
    $composeMode = "docker_cli_plugin"
    if (-not [string]::IsNullOrWhiteSpace($ComposeExecutablePath)) {
        $composePath = Assert-ImmoAppManagedRuntimeExistingFile -Path $ComposeExecutablePath -Label "ComposeExecutablePath" -AllowTestOnlyPath:$AllowTestOnlyPath
        $composeMode = "standalone"
    }

    if ([string]::IsNullOrWhiteSpace($SourceCommitSha)) {
        try {
            $SourceCommitSha = (& git -C (Get-ImmoAppRepoRoot).Path rev-parse HEAD 2>$null | Out-String).Trim().ToLowerInvariant()
        }
        catch {
            $SourceCommitSha = ""
        }
    }

    $usingCanonicalRuntimeRoot = Test-ImmoAppUsingCanonicalRuntimeRoot
    $packageInventoryPath = ""
    $packageSha256 = ""
    $proofOnly = $true
    if ([string]::IsNullOrWhiteSpace($PackageInventoryJson) -and -not $AllowTestOnlyPath) {
        throw "Production managed runtime provider registration requires -PackageInventoryJson. Use -AllowTestOnlyPath only for internal proof-only providers."
    }
    if (-not [string]::IsNullOrWhiteSpace($PackageInventoryJson)) {
        $packageInventoryPath = Assert-ImmoAppManagedRuntimeExistingFile -Path $PackageInventoryJson -Label "PackageInventoryJson" -AllowTestOnlyPath:$AllowTestOnlyPath
        $inventory = Get-Content -LiteralPath $packageInventoryPath -Raw | ConvertFrom-Json
        Assert-ImmoAppManagedRuntimePackageInventoryReady `
            -Inventory $inventory `
            -ExpectedSourceCommitSha $SourceCommitSha `
            -PackageInventoryPath $packageInventoryPath `
            -RuntimeExecutablePath $runtimePath `
            -ComposeExecutablePath $composePath `
            -InstallRoot $installRootPath `
            -RuntimePaths $paths
        $packageSha256 = [string]$inventory.package_sha256
        $proofOnly = [bool]$AllowTestOnlyPath
    }

    if (-not $proofOnly) {
        if (-not $usingCanonicalRuntimeRoot) {
            throw "Production managed runtime provider registration requires canonical C:\ProgramData\ImmoApp roots."
        }
        Assert-ImmoAppCanonicalProviderConfigPathSafe -Path $providerPath | Out-Null
        Assert-ImmoAppLowerHexSha256 -Value $InstallerSha256.ToLowerInvariant() -Name "installer_sha256"
        foreach ($entry in @(
            @{ Path = $runtimePath; Root = $canonicalPaths.RuntimeRoot; Label = "RuntimeExecutablePath" },
            @{ Path = $installRootPath; Root = $canonicalPaths.RuntimeRoot; Label = "InstallRoot" },
            @{ Path = $dataRootPath; Root = $canonicalPaths.DataRoot; Label = "DataRoot" },
            @{ Path = $logsRootPath; Root = $canonicalPaths.LogsRoot; Label = "LogsRoot" }
        )) {
            Assert-ImmoAppManagedRuntimeNoReparseUnderRoot -Path $entry.Path -Root $entry.Root -Label $entry.Label
        }
        if (
            -not (Test-ImmoAppPathUnderRoot -Root $canonicalPaths.RuntimeRoot -Path $packageInventoryPath) -and
            -not (Test-ImmoAppPathUnderRoot -Root $canonicalPaths.ConfigRoot -Path $packageInventoryPath)
        ) {
            throw "PackageInventoryJson must be under approved ProgramData runtime or config root: $packageInventoryPath"
        }
        if (Test-ImmoAppPathHasReparsePoint -Path $packageInventoryPath) {
            throw "PackageInventoryJson contains a reparse point, symlink, or junction: $packageInventoryPath"
        }
        if (
            -not (Test-ImmoAppResolvedPathUnderRoot -Root $canonicalPaths.RuntimeRoot -Path $packageInventoryPath) -and
            -not (Test-ImmoAppResolvedPathUnderRoot -Root $canonicalPaths.ConfigRoot -Path $packageInventoryPath)
        ) {
            throw "PackageInventoryJson resolves outside approved ProgramData runtime or config root: $packageInventoryPath"
        }
        if ($composeMode -eq "standalone") {
            Assert-ImmoAppManagedRuntimeNoReparseUnderRoot -Path $composePath -Root $canonicalPaths.RuntimeRoot -Label "ComposeExecutablePath"
        }
    }
    else {
        Assert-ImmoAppCanonicalProviderConfigPathSafe -Path $providerPath -AllowNonCanonical | Out-Null
        $proofRuntimeRoots = Get-ImmoAppProofApprovedRoots -CanonicalPaths $canonicalPaths -ActivePaths $paths -Kind "runtime"
        $proofDataRoots = Get-ImmoAppProofApprovedRoots -CanonicalPaths $canonicalPaths -ActivePaths $paths -Kind "data"
        $proofLogsRoots = Get-ImmoAppProofApprovedRoots -CanonicalPaths $canonicalPaths -ActivePaths $paths -Kind "logs"
        $proofInventoryRoots = Get-ImmoAppProofApprovedRoots -CanonicalPaths $canonicalPaths -ActivePaths $paths -Kind "config"
        Assert-ImmoAppProofOnlyPathApproved -Path $runtimePath -Roots $proofRuntimeRoots -Label "RuntimeExecutablePath"
        Assert-ImmoAppProofOnlyPathApproved -Path $installRootPath -Roots $proofRuntimeRoots -Label "InstallRoot"
        Assert-ImmoAppProofOnlyPathApproved -Path $dataRootPath -Roots $proofDataRoots -Label "DataRoot"
        Assert-ImmoAppProofOnlyPathApproved -Path $logsRootPath -Roots $proofLogsRoots -Label "LogsRoot"
        if ($composeMode -eq "standalone") {
            Assert-ImmoAppProofOnlyPathApproved -Path $composePath -Roots $proofRuntimeRoots -Label "ComposeExecutablePath"
        }
        if ($packageInventoryPath) {
            Assert-ImmoAppProofOnlyPathApproved -Path $packageInventoryPath -Roots $proofInventoryRoots -Label "PackageInventoryJson"
        }
    }

    $runtimeVersion = Invoke-ImmoAppManagedRuntimeVersionCheck -Command $runtimePath -Arguments @("version") -Label "Runtime"
    if ($composeMode -eq "standalone") {
        $composeVersion = Invoke-ImmoAppManagedRuntimeVersionCheck -Command $composePath -Arguments @("version") -Label "Compose"
    }
    else {
        $composeVersion = Invoke-ImmoAppManagedRuntimeVersionCheck -Command $runtimePath -Arguments @("compose", "version") -Label "Compose plugin"
    }

    $payload = [ordered]@{
        kind = "immoapp_hub_runtime_provider"
        schema_version = 1
        provider_mode = "managed_container_runtime"
        installed_by_immoapp = $true
        user_visible_runtime = $false
        proof_only = $proofOnly
        runtime_executable_path = $runtimePath
        compose_executable_path = $composePath
        compose_mode = $composeMode
        runtime_version = $runtimeVersion
        compose_version = $composeVersion
        install_root = $installRootPath
        data_root = $dataRootPath
        logs_root = $logsRootPath
        managed_service_name = $ManagedServiceName
        created_at_utc = (Get-Date).ToUniversalTime().ToString("o")
        source_commit_sha = $SourceCommitSha
        installer_sha256 = $InstallerSha256.ToLowerInvariant()
        package_sha256 = $packageSha256
        package_inventory_path = $packageInventoryPath
    }

    $providerWritten = $false
    $providerConfigSha256AfterWrite = ""
    $providerLockStatus = if ($WriteProvider) { "held" } elseif ($WhatIfMode) { "not_required_whatif" } else { "not_required_validation" }
    if ($WriteProvider) {
        $safeWrite = Write-ImmoAppSafeJson -Path $providerPath -Payload $payload -ApprovedRoots @($paths.ConfigRoot) -Depth 8
        $providerConfigSha256AfterWrite = [string]$safeWrite.sha256
        $providerWritten = $true
    }

    $providerWriteStatus = if ($providerWritten) { "GO" } elseif ($WhatIfMode) { "not_written_whatif" } else { "not_written" }
    $registrationProofResult = if ($providerWritten -and -not $proofOnly) { "GO" } else { "NO-GO" }
    $registrationAgencyStatus = if ($providerWritten -and -not $proofOnly) { "PENDING_DETECTION" } else { "NO_GO" }
    $registrationReasonCode = if (-not $providerWritten -and $WhatIfMode) {
        "whatif_not_written"
    } elseif ($proofOnly) {
        "proof_only_provider"
    } else {
        "provider_registered_pending_detection"
    }

    return [ordered]@{
        kind = "immoapp_hub_runtime_provider_registration"
        schema_version = 1
        created_at_utc = (Get-Date).ToUniversalTime().ToString("o")
        provider_config_path = $providerPath
        proof_only = $proofOnly
        provider = $payload
        provider_config_sha256_after_write = $providerConfigSha256AfterWrite
        provider_lock_status = $providerLockStatus
        provider_write_status = $providerWriteStatus
        internal_proof_status = if ($providerWritten -or ($proofOnly -and -not $WhatIfMode)) { "GO" } else { "NO_GO" }
        agency_install_status = $registrationAgencyStatus
        proof_result = $registrationProofResult
        reason_code = $registrationReasonCode
    }
}

function Test-ImmoAppStrictBackupRestoreEvidence {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [string]$ExpectedSourceCommitSha = "",
        [string]$ExpectedInstallerSha256 = "",
        [string]$ExpectedCandidateProofRunId = "",
        [string]$ExpectedRuntimeDependencyMode = "",
        [string]$ExpectedProviderConfigSha256 = "",
        [string]$ExpectedProviderConfigPath = "",
        [string]$ExpectedHubRuntimeProviderMode = ""
    )

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return [ordered]@{ ok = $false; reason_code = "backup_restore_evidence_missing"; reason = "Backup/restore evidence path does not exist." }
    }
    if (Test-ImmoAppPathHasReparsePoint -Path $Path) {
        return [ordered]@{ ok = $false; reason_code = "backup_restore_evidence_reparse_point"; reason = "Backup/restore evidence path contains a reparse point, symlink, or junction." }
    }

    try {
        $data = Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
    }
    catch {
        return [ordered]@{ ok = $false; reason_code = "backup_restore_evidence_invalid_json"; reason = $_.Exception.Message }
    }

    $kind = [string](Get-ImmoAppObjectValue -Data $data -Name "kind")
    if ($kind -notin @("immoapp_release_backup_restore_evidence", "immoapp_beta_release_backup_restore_evidence")) {
        return [ordered]@{ ok = $false; reason_code = "backup_restore_wrong_kind"; reason = "Backup/restore evidence kind is not accepted." }
    }
    $schema = [string](Get-ImmoAppObjectValue -Data $data -Name "schema_version")
    if ([string]::IsNullOrWhiteSpace($schema)) {
        return [ordered]@{ ok = $false; reason_code = "backup_restore_schema_missing"; reason = "Backup/restore evidence must include schema_version." }
    }
    $proof = [string](Get-ImmoAppObjectValue -Data $data -Name "proof_result")
    $status = [string](Get-ImmoAppObjectValue -Data $data -Name "status")
    if ($proof -ne "GO") {
        $statusNote = if ($status -eq "GO") { " Legacy status=GO is informational only and cannot satisfy release proof." } else { "" }
        return [ordered]@{ ok = $false; reason_code = "backup_restore_proof_result_missing"; reason = "Backup/restore evidence must explicitly include proof_result=GO.$statusNote" }
    }
    $restoreDatabase = [string](Get-ImmoAppObjectValue -Data $data -Name "restore_database")
    if ([string]::IsNullOrWhiteSpace($restoreDatabase)) {
        return [ordered]@{ ok = $false; reason_code = "backup_restore_database_missing"; reason = "Backup/restore evidence must include restore_database." }
    }
    $restoreBucket = [string](Get-ImmoAppObjectValue -Data $data -Name "isolated_restore_bucket")
    if ([string]::IsNullOrWhiteSpace($restoreBucket) -or -not $restoreBucket.StartsWith("immoapp-restore-drill-", [System.StringComparison]::OrdinalIgnoreCase)) {
        return [ordered]@{ ok = $false; reason_code = "backup_restore_bucket_not_isolated"; reason = "Backup/restore evidence isolated_restore_bucket must start with immoapp-restore-drill-." }
    }
    $objectsChecked = 0
    [void][int]::TryParse([string](Get-ImmoAppObjectValue -Data $data -Name "storage_objects_checked"), [ref]$objectsChecked)
    if ($objectsChecked -le 0) {
        return [ordered]@{ ok = $false; reason_code = "backup_restore_objects_not_checked"; reason = "Backup/restore evidence must check at least one storage object." }
    }
    $hashVerified = 0
    [void][int]::TryParse([string](Get-ImmoAppObjectValue -Data $data -Name "storage_objects_hash_verified"), [ref]$hashVerified)
    if ($hashVerified -ne $objectsChecked) {
        return [ordered]@{ ok = $false; reason_code = "backup_restore_hash_verification_incomplete"; reason = "Backup/restore evidence must hash-verify every checked storage object." }
    }
    $sourceBucketUsed = ([string](Get-ImmoAppObjectValue -Data $data -Name "live_source_bucket_used_as_restore_target")).ToLowerInvariant() -in @("true", "1", "yes")
    if ($sourceBucketUsed) {
        return [ordered]@{ ok = $false; reason_code = "source_bucket_used_as_restore_target"; reason = "Backup/restore evidence must not use the live source bucket as the restore target." }
    }
    foreach ($sourceBucketField in @("source_bucket", "live_source_bucket", "backup_source_bucket")) {
        $sourceBucket = [string](Get-ImmoAppObjectValue -Data $data -Name $sourceBucketField)
        if (-not [string]::IsNullOrWhiteSpace($sourceBucket) -and $sourceBucket.Equals($restoreBucket, [System.StringComparison]::OrdinalIgnoreCase)) {
            return [ordered]@{ ok = $false; reason_code = "source_bucket_used_as_restore_target"; reason = "Backup/restore evidence source bucket must differ from isolated restore bucket." }
        }
    }
    $backupBundleSha = [string](Get-ImmoAppObjectValue -Data $data -Name "backup_bundle_sha256")
    if ($backupBundleSha -notmatch "^[0-9a-f]{64}$") {
        return [ordered]@{ ok = $false; reason_code = "backup_bundle_sha256_missing"; reason = "Backup/restore evidence must include lowercase backup_bundle_sha256." }
    }
    $backupBundlePath = [string](Get-ImmoAppObjectValue -Data $data -Name "backup_bundle_path")
    $localArtifactVerified = $false
    if (-not [string]::IsNullOrWhiteSpace($backupBundlePath)) {
        if (-not (Test-Path -LiteralPath $backupBundlePath -PathType Leaf)) {
            return [ordered]@{ ok = $false; reason_code = "backup_bundle_missing"; reason = "backup_bundle_path is present but does not point to an existing local file." }
        }
        if (Test-ImmoAppPathHasReparsePoint -Path $backupBundlePath) {
            return [ordered]@{ ok = $false; reason_code = "backup_bundle_reparse_point"; reason = "Backup bundle path contains a reparse point, symlink, or junction." }
        }
        $actualSha = Get-ImmoAppFileSha256 -Path $backupBundlePath
        if ($actualSha -ne $backupBundleSha) {
            return [ordered]@{ ok = $false; reason_code = "backup_bundle_sha256_mismatch"; reason = "backup_bundle_sha256 does not match the local backup bundle file." }
        }
        $localArtifactVerified = $true
    }
    $remoteEvidence = ([string](Get-ImmoAppObjectValue -Data $data -Name "remote_evidence")).ToLowerInvariant() -in @("true", "1", "yes")
    $remoteArtifactVerified = $false
    if ($remoteEvidence) {
        foreach ($field in @("evidence_file_sha256", "copied_artifact_sha256")) {
            $value = [string](Get-ImmoAppObjectValue -Data $data -Name $field)
            if ($value -notmatch "^[0-9a-f]{64}$") {
                return [ordered]@{ ok = $false; reason_code = "backup_restore_remote_artifact_proof_missing"; reason = "Remote backup evidence must include lowercase $field." }
            }
        }
        $copiedSha = [string](Get-ImmoAppObjectValue -Data $data -Name "copied_artifact_sha256")
        if ($copiedSha -ne $backupBundleSha) {
            return [ordered]@{ ok = $false; reason_code = "backup_restore_remote_artifact_sha_mismatch"; reason = "copied_artifact_sha256 must match backup_bundle_sha256." }
        }
        foreach ($field in @("copied_artifact_reference", "remote_machine_name", "collected_at_utc")) {
            if ([string]::IsNullOrWhiteSpace([string](Get-ImmoAppObjectValue -Data $data -Name $field))) {
                return [ordered]@{ ok = $false; reason_code = "backup_restore_remote_artifact_proof_missing"; reason = "Remote backup evidence must include $field." }
            }
        }
        $remoteArtifactVerified = $true
    }
    if (-not $localArtifactVerified -and -not $remoteArtifactVerified) {
        return [ordered]@{ ok = $false; reason_code = "backup_restore_artifact_proof_missing"; reason = "Backup/restore evidence must verify a local backup_bundle_path hash or provide complete remote artifact proof." }
    }

    $candidateBindingRequested = (
        -not [string]::IsNullOrWhiteSpace($ExpectedCandidateProofRunId) -or
        -not [string]::IsNullOrWhiteSpace($ExpectedRuntimeDependencyMode) -or
        -not [string]::IsNullOrWhiteSpace($ExpectedProviderConfigSha256) -or
        -not [string]::IsNullOrWhiteSpace($ExpectedProviderConfigPath) -or
        -not [string]::IsNullOrWhiteSpace($ExpectedHubRuntimeProviderMode)
    )
    if ($candidateBindingRequested) {
        foreach ($timeField in @("backup_started_at_utc", "restore_verified_at_utc")) {
            if ([string]::IsNullOrWhiteSpace([string](Get-ImmoAppObjectValue -Data $data -Name $timeField))) {
                return [ordered]@{ ok = $false; reason_code = "backup_restore_identity_missing"; reason = "Backup/restore evidence must include $timeField for candidate-bound promotion." }
            }
        }
    }
    if (-not [string]::IsNullOrWhiteSpace($ExpectedSourceCommitSha)) {
        $actual = [string](Get-ImmoAppObjectValue -Data $data -Name "source_commit_sha")
        if ([string]::IsNullOrWhiteSpace($actual)) {
            return [ordered]@{ ok = $false; reason_code = "backup_restore_source_commit_missing"; reason = "Backup/restore evidence must include source_commit_sha." }
        }
        if ($actual -ne $ExpectedSourceCommitSha) {
            return [ordered]@{ ok = $false; reason_code = "backup_restore_source_commit_mismatch"; reason = "Backup/restore evidence source_commit_sha does not match the candidate proof." }
        }
    }
    if (-not [string]::IsNullOrWhiteSpace($ExpectedInstallerSha256)) {
        $actual = [string](Get-ImmoAppObjectValue -Data $data -Name "installer_sha256")
        if ([string]::IsNullOrWhiteSpace($actual)) {
            return [ordered]@{ ok = $false; reason_code = "backup_restore_installer_sha_missing"; reason = "Backup/restore evidence must include installer_sha256." }
        }
        if ($actual.ToLowerInvariant() -ne $ExpectedInstallerSha256.ToLowerInvariant()) {
            return [ordered]@{ ok = $false; reason_code = "backup_restore_installer_sha_mismatch"; reason = "Backup/restore evidence installer_sha256 does not match the candidate proof." }
        }
    }
    if (-not [string]::IsNullOrWhiteSpace($ExpectedCandidateProofRunId)) {
        $actual = [string](Get-ImmoAppObjectValue -Data $data -Name "candidate_proof_run_id")
        if ([string]::IsNullOrWhiteSpace($actual)) {
            return [ordered]@{ ok = $false; reason_code = "backup_restore_candidate_proof_run_id_missing"; reason = "Backup/restore evidence must include candidate_proof_run_id." }
        }
        if ($actual -ne $ExpectedCandidateProofRunId) {
            return [ordered]@{ ok = $false; reason_code = "backup_restore_candidate_proof_run_id_mismatch"; reason = "Backup/restore evidence candidate_proof_run_id does not match the candidate proof." }
        }
    }
    if (-not [string]::IsNullOrWhiteSpace($ExpectedRuntimeDependencyMode)) {
        $actual = [string](Get-ImmoAppObjectValue -Data $data -Name "runtime_dependency_mode")
        if ([string]::IsNullOrWhiteSpace($actual)) {
            return [ordered]@{ ok = $false; reason_code = "backup_restore_runtime_mode_missing"; reason = "Backup/restore evidence must include runtime_dependency_mode." }
        }
        if ($actual -ne $ExpectedRuntimeDependencyMode) {
            return [ordered]@{ ok = $false; reason_code = "backup_restore_runtime_mode_mismatch"; reason = "Backup/restore evidence runtime_dependency_mode does not match the candidate provider." }
        }
    }
    if (-not [string]::IsNullOrWhiteSpace($ExpectedProviderConfigSha256)) {
        $actual = [string](Get-ImmoAppObjectValue -Data $data -Name "provider_config_sha256_at_backup")
        if ([string]::IsNullOrWhiteSpace($actual)) {
            $actual = [string](Get-ImmoAppObjectValue -Data $data -Name "provider_config_sha256_final")
        }
        if ([string]::IsNullOrWhiteSpace($actual)) {
            return [ordered]@{ ok = $false; reason_code = "backup_restore_provider_sha_missing"; reason = "Backup/restore evidence must include provider_config_sha256_at_backup." }
        }
        if ($actual.ToLowerInvariant() -ne $ExpectedProviderConfigSha256.ToLowerInvariant()) {
            return [ordered]@{ ok = $false; reason_code = "backup_restore_provider_sha_mismatch"; reason = "Backup/restore evidence provider config SHA-256 does not match the candidate provider." }
        }
    }
    if (-not [string]::IsNullOrWhiteSpace($ExpectedProviderConfigPath)) {
        $actual = [string](Get-ImmoAppObjectValue -Data $data -Name "provider_config_path")
        if ([string]::IsNullOrWhiteSpace($actual)) {
            return [ordered]@{ ok = $false; reason_code = "backup_restore_provider_path_missing"; reason = "Backup/restore evidence must include provider_config_path." }
        }
        if (-not ([System.IO.Path]::GetFullPath($actual).Equals([System.IO.Path]::GetFullPath($ExpectedProviderConfigPath), [System.StringComparison]::OrdinalIgnoreCase))) {
            return [ordered]@{ ok = $false; reason_code = "backup_restore_provider_path_mismatch"; reason = "Backup/restore evidence provider_config_path does not match the candidate provider." }
        }
    }
    if (-not [string]::IsNullOrWhiteSpace($ExpectedHubRuntimeProviderMode)) {
        $actual = [string](Get-ImmoAppObjectValue -Data $data -Name "hub_runtime_provider_mode")
        if ([string]::IsNullOrWhiteSpace($actual)) {
            return [ordered]@{ ok = $false; reason_code = "backup_restore_provider_mode_missing"; reason = "Backup/restore evidence must include hub_runtime_provider_mode." }
        }
        if ($actual -ne $ExpectedHubRuntimeProviderMode) {
            return [ordered]@{ ok = $false; reason_code = "backup_restore_provider_mode_mismatch"; reason = "Backup/restore evidence hub_runtime_provider_mode does not match the candidate provider." }
        }
    }

    return [ordered]@{ ok = $true; reason_code = "backup_restore_verified"; reason = ""; evidence = $data }
}

function Assert-ImmoAppStrictBackupRestoreEvidence {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [string]$ExpectedSourceCommitSha = "",
        [string]$ExpectedInstallerSha256 = "",
        [string]$ExpectedCandidateProofRunId = "",
        [string]$ExpectedRuntimeDependencyMode = "",
        [string]$ExpectedProviderConfigSha256 = "",
        [string]$ExpectedProviderConfigPath = "",
        [string]$ExpectedHubRuntimeProviderMode = ""
    )
    $result = Test-ImmoAppStrictBackupRestoreEvidence `
        -Path $Path `
        -ExpectedSourceCommitSha $ExpectedSourceCommitSha `
        -ExpectedInstallerSha256 $ExpectedInstallerSha256 `
        -ExpectedCandidateProofRunId $ExpectedCandidateProofRunId `
        -ExpectedRuntimeDependencyMode $ExpectedRuntimeDependencyMode `
        -ExpectedProviderConfigSha256 $ExpectedProviderConfigSha256 `
        -ExpectedProviderConfigPath $ExpectedProviderConfigPath `
        -ExpectedHubRuntimeProviderMode $ExpectedHubRuntimeProviderMode
    if ($result.ok -ne $true) {
        throw "$($result.reason_code)|$($result.reason)"
    }
    return $result
}

function Write-ImmoAppSafeJson {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)]$Payload,
        [Parameter(Mandatory = $true)][string[]]$ApprovedRoots,
        [int]$Depth = 12
    )
    $full = [System.IO.Path]::GetFullPath($Path)
    $approvedRootForWrite = ""
    $underApprovedRoot = $false
    foreach ($root in $ApprovedRoots) {
        $rootFull = [System.IO.Path]::GetFullPath($root)
        if (
            (Test-ImmoAppPathUnderRoot -Root $rootFull -Path $full) -and
            ((-not (Test-Path -LiteralPath $rootFull)) -or (Test-ImmoAppResolvedPathUnderRoot -Root $rootFull -Path $full))
        ) {
            $underApprovedRoot = $true
            $approvedRootForWrite = $rootFull
            break
        }
    }
    if (-not $underApprovedRoot) {
        throw "safe_json_output_outside_approved_root|JSON output path must be under an approved root: $full"
    }

    $parent = Split-Path -Parent $full
    if ($parent) {
        $existing = $parent
        while (-not [string]::IsNullOrWhiteSpace($existing) -and -not (Test-Path -LiteralPath $existing)) {
            $next = Split-Path -Parent $existing
            if ([string]::IsNullOrWhiteSpace($next) -or $next -eq $existing) { break }
            $existing = $next
        }
        if (-not [string]::IsNullOrWhiteSpace($existing) -and (Test-Path -LiteralPath $existing)) {
            if (Test-ImmoAppPathHasReparsePoint -Path $existing) {
                throw "safe_json_output_reparse_point|JSON output parent contains a reparse point, symlink, or junction: $existing"
            }
            if (
                (Test-Path -LiteralPath $approvedRootForWrite) -and
                -not (Test-ImmoAppResolvedPathUnderRoot -Root $approvedRootForWrite -Path $existing)
            ) {
                throw "safe_json_output_resolved_outside_approved_root|JSON output parent resolves outside approved roots: $existing"
            }
        }
        if (-not (Test-Path -LiteralPath $parent)) {
            [System.IO.Directory]::CreateDirectory($parent) | Out-Null
        }
        if (-not (Test-Path -LiteralPath $parent -PathType Container)) {
            throw "safe_json_output_parent_missing|JSON output parent directory could not be created: $parent"
        }
        if (Test-ImmoAppPathHasReparsePoint -Path $parent) {
            throw "safe_json_output_reparse_point|JSON output parent contains a reparse point, symlink, or junction after creation: $parent"
        }
        if (-not (Test-ImmoAppResolvedPathUnderRoot -Root $approvedRootForWrite -Path $parent)) {
            throw "safe_json_output_resolved_outside_approved_root|JSON output parent resolves outside approved root after creation: $parent"
        }
    }
    if (Test-Path -LiteralPath $full) {
        if (Test-ImmoAppPathHasReparsePoint -Path $full) {
            throw "safe_json_output_reparse_point|JSON output file contains a reparse point, symlink, or junction: $full"
        }
    }
    if ([string]::IsNullOrWhiteSpace($parent)) {
        $parent = (Get-Location).Path
    }
    $temp = Join-Path $parent ([System.IO.Path]::GetFileName($full) + ".tmp." + [System.Guid]::NewGuid().ToString("N"))
    $backup = Join-Path $parent ([System.IO.Path]::GetFileName($full) + ".bak." + [System.Guid]::NewGuid().ToString("N"))
    if (-not (Test-ImmoAppPathUnderRoot -Root $parent -Path $temp) -or -not (Test-ImmoAppResolvedPathUnderRoot -Root $parent -Path $temp)) {
        throw "safe_json_output_resolved_outside_approved_root|Temporary JSON output path escaped its parent: $temp"
    }
    if (-not (Test-ImmoAppPathUnderRoot -Root $parent -Path $backup) -or -not (Test-ImmoAppResolvedPathUnderRoot -Root $parent -Path $backup)) {
        throw "safe_json_output_resolved_outside_approved_root|Temporary JSON backup path escaped its parent: $backup"
    }
    $pathBytes = [System.Text.Encoding]::UTF8.GetBytes($full.ToLowerInvariant())
    $pathHasher = [System.Security.Cryptography.SHA256]::Create()
    try {
        $pathHash = ([System.BitConverter]::ToString($pathHasher.ComputeHash($pathBytes))).Replace("-", "").ToLowerInvariant()
    }
    finally {
        $pathHasher.Dispose()
    }
    $mutex = [System.Threading.Mutex]::new($false, "Local\ImmoAppSafeJson_$pathHash")
    $hasMutex = $false
    try {
        $hasMutex = $mutex.WaitOne([System.TimeSpan]::FromSeconds(30))
        if (-not $hasMutex) {
            throw "safe_json_output_lock_timeout|Timed out waiting for same-path JSON evidence write lock: $full"
        }
        $json = $Payload | ConvertTo-Json -Depth $Depth
        $utf8NoBom = [System.Text.UTF8Encoding]::new($false)
        [System.IO.File]::WriteAllText($temp, $json, $utf8NoBom)
        if (Test-ImmoAppPathHasReparsePoint -Path $temp) {
            throw "safe_json_output_reparse_point|Temporary JSON output path contains a reparse point, symlink, or junction: $temp"
        }
        Get-Content -LiteralPath $temp -Raw | ConvertFrom-Json | Out-Null
        $tempSha = Get-ImmoAppFileSha256 -Path $temp
        try {
            if (Test-Path -LiteralPath $full -PathType Leaf) {
                [System.IO.File]::Replace($temp, $full, $backup, $true)
            }
            else {
                [System.IO.File]::Move($temp, $full)
            }
        }
        catch [System.IO.IOException] {
            # Another Hub Manager action can create the same evidence file between
            # the existence check and Move(). Treat that as last-writer-wins only
            # after re-checking the destination is a normal file.
            if (Test-Path -LiteralPath $full -PathType Leaf) {
                if (Test-ImmoAppPathHasReparsePoint -Path $full) {
                    throw "safe_json_output_reparse_point|JSON output file contains a reparse point, symlink, or junction: $full"
                }
                [System.IO.File]::Replace($temp, $full, $backup, $true)
            }
            else {
                throw
            }
        }
        if (-not (Test-Path -LiteralPath $full -PathType Leaf)) {
            throw "safe_json_output_missing_after_write|JSON output file missing after atomic move: $full"
        }
        if (Test-ImmoAppPathHasReparsePoint -Path $full) {
            throw "safe_json_output_reparse_point|JSON output file became a reparse point, symlink, or junction: $full"
        }
        $finalSha = Get-ImmoAppFileSha256 -Path $full
        if ($finalSha -ne $tempSha) {
            throw "safe_json_output_sha_mismatch|JSON output SHA-256 does not match temp file after atomic move: $full"
        }
        if (Test-Path -LiteralPath $backup) {
            try {
                [System.IO.File]::Delete($backup)
            }
            catch {
                # The final evidence is already verified; backup cleanup is best-effort
                # because prior admin-owned evidence can produce admin-owned backups.
            }
        }
        return [ordered]@{
            path = $full
            sha256 = $finalSha
        }
    }
    finally {
        if (Test-Path -LiteralPath $temp) {
            Remove-Item -LiteralPath $temp -Force
        }
        if (Test-Path -LiteralPath $backup) {
            try {
                [System.IO.File]::Delete($backup)
            }
            catch {
            }
        }
        if ($hasMutex) {
            $mutex.ReleaseMutex()
        }
        $mutex.Dispose()
    }
}

function Get-ImmoAppManagedRuntimeLogsRoot {
    return (Join-Path (Get-ImmoAppRuntimePaths).LogsRoot "managed-runtime")
}

function Invoke-ImmoAppManagedRuntimeLogRetention {
    param(
        [string]$LogsRoot = "",
        [string]$OutputJson = "",
        [int]$RetentionDays = 14,
        [Int64]$MaxTotalBytes = 536870912
    )

    $paths = Ensure-ImmoAppRuntimeLayout
    $canonicalPaths = Get-ImmoAppCanonicalRuntimePaths
    if ([string]::IsNullOrWhiteSpace($LogsRoot)) {
        $LogsRoot = Join-Path $paths.LogsRoot "managed-runtime"
    }
    if ([string]::IsNullOrWhiteSpace($OutputJson)) {
        $OutputJson = Join-Path $paths.LogsRoot "managed_runtime_log_retention.json"
    }

    $approvedManagedLogRoots = New-Object System.Collections.Generic.List[string]
    $approvedManagedLogRoots.Add((Join-Path $canonicalPaths.LogsRoot "managed-runtime"))
    if ((Get-ImmoAppRuntimeRootSource) -eq "test_programdata_root") {
        $approvedManagedLogRoots.Add((Join-Path $paths.LogsRoot "managed-runtime"))
    }
    $approvedOutputRoots = @()
    $approvedOutputRoots += Get-ImmoAppProofApprovedRoots -CanonicalPaths $canonicalPaths -ActivePaths $paths -Kind "logs"
    $approvedOutputRoots += Get-ImmoAppProofApprovedRoots -CanonicalPaths $canonicalPaths -ActivePaths $paths -Kind "config"
    $approvedOutputRoots = @($approvedOutputRoots | Select-Object -Unique)

    $createdAt = (Get-Date).ToUniversalTime()
    $logsRootFull = [System.IO.Path]::GetFullPath($LogsRoot)
    $proofResult = "GO"
    $reasonCode = "managed_runtime_log_retention_go"
    $scanned = New-Object System.Collections.Generic.List[object]
    $deleted = New-Object System.Collections.Generic.List[object]
    $skipped = New-Object System.Collections.Generic.List[object]
    $failedDeletes = New-Object System.Collections.Generic.List[object]
    $failedDeleteByPath = @{}
    $deletedBytes = [Int64]0
    $retainedBytes = [Int64]0
    $sizeCapSatisfied = $true
    $ageRetentionSatisfied = $true
    $allowedExtensions = @(".log", ".txt", ".out", ".err", ".trace", ".jsonl", ".ndjson")

    function Add-LogRetentionSkip {
        param([string]$Path, [string]$Reason)
        $relative = ""
        try {
            $full = [System.IO.Path]::GetFullPath($Path)
            if (Test-ImmoAppPathUnderRoot -Root $logsRootFull -Path $full) {
                $relative = $full.Substring($logsRootFull.TrimEnd("\", "/").Length).TrimStart("\", "/").Replace("\", "/")
            }
        }
        catch {
            $relative = ""
        }
        if ([string]::IsNullOrWhiteSpace($relative)) { $relative = [System.IO.Path]::GetFileName($Path) }
        $skipped.Add([ordered]@{ path = $relative; reason = $Reason }) | Out-Null
    }

    function Add-LogRetentionFailedDelete {
        param([object]$Entry, [string]$Reason)
        $relativePath = [string]$Entry.path
        if ([string]::IsNullOrWhiteSpace($relativePath)) { return }
        if ($failedDeleteByPath.ContainsKey($relativePath)) { return }
        $failedDeleteByPath[$relativePath] = $Reason
        $failedDeletes.Add([ordered]@{
            path = $relativePath
            bytes = [Int64]$Entry.bytes
            reason = $Reason
        }) | Out-Null
    }

    function Get-LogRetentionManagedRuntimeFiles {
        param([switch]$RecordSkips)

        $found = New-Object System.Collections.Generic.List[object]
        $stack = New-Object System.Collections.Generic.Stack[string]
        $stack.Push($logsRootFull)
        while ($stack.Count -gt 0) {
            $current = $stack.Pop()
            if (Test-ImmoAppPathHasReparsePoint -Path $current) {
                if ($RecordSkips) { Add-LogRetentionSkip -Path $current -Reason "reparse_directory" }
                continue
            }
            foreach ($item in Get-ChildItem -LiteralPath $current -Force -ErrorAction Stop) {
                $full = [System.IO.Path]::GetFullPath($item.FullName)
                if (-not (Test-ImmoAppPathUnderRoot -Root $logsRootFull -Path $full)) {
                    if ($RecordSkips) { Add-LogRetentionSkip -Path $full -Reason "path_escape" }
                    continue
                }
                if (Test-ImmoAppPathHasReparsePoint -Path $full) {
                    if ($RecordSkips) { Add-LogRetentionSkip -Path $full -Reason "reparse_point" }
                    continue
                }
                if ($item.PSIsContainer) {
                    $stack.Push($full)
                    continue
                }
                $extension = ([System.IO.Path]::GetExtension($full)).ToLowerInvariant()
                if ($allowedExtensions -notcontains $extension) {
                    if ($RecordSkips) { Add-LogRetentionSkip -Path $full -Reason "non_managed_runtime_log_extension" }
                    continue
                }
                $relative = $full.Substring($logsRootFull.TrimEnd("\", "/").Length).TrimStart("\", "/").Replace("\", "/")
                $found.Add([ordered]@{
                    path = $relative
                    full_path = $full
                    bytes = [Int64]$item.Length
                    last_write_utc = $item.LastWriteTimeUtc
                }) | Out-Null
            }
        }
        return @($found.ToArray())
    }

    try {
        if ($RetentionDays -lt 1) {
            throw "managed_runtime_log_retention_days_invalid|RetentionDays must be at least 1."
        }
        if ($MaxTotalBytes -lt 1) {
            throw "managed_runtime_log_retention_max_bytes_invalid|MaxTotalBytes must be at least 1."
        }
        if (-not (Test-ImmoAppPathUnderAnyApprovedRoot -Path $logsRootFull -Roots @($approvedManagedLogRoots.ToArray()))) {
            throw "managed_runtime_log_retention_root_not_approved|Managed runtime log cleanup root must be the dedicated managed-runtime logs directory."
        }
        if (Test-ImmoAppPathHasReparsePoint -Path $logsRootFull) {
            throw "managed_runtime_log_retention_root_reparse_point|Managed runtime log cleanup root is or contains a reparse point."
        }
        if (-not (Test-Path -LiteralPath $logsRootFull)) {
            [System.IO.Directory]::CreateDirectory($logsRootFull) | Out-Null
        }
        if (-not (Test-Path -LiteralPath $logsRootFull -PathType Container)) {
            throw "managed_runtime_log_retention_root_missing|Managed runtime log cleanup root could not be created."
        }

        foreach ($entry in @(Get-LogRetentionManagedRuntimeFiles -RecordSkips)) {
            $scanned.Add($entry) | Out-Null
        }

        $cutoff = $createdAt.AddDays(-1 * $RetentionDays)
        $deleteSet = @{}
        $ageDeletes = @(
            $scanned |
                Where-Object { $_.last_write_utc -lt $cutoff } |
                Sort-Object @{Expression = { $_.last_write_utc }; Ascending = $true}, @{Expression = { $_.path }; Ascending = $true}
        )
        foreach ($entry in $ageDeletes) {
            $deleteSet[[string]$entry.path] = "older_than_retention_days"
        }

        $remaining = @($scanned | Where-Object { -not $deleteSet.ContainsKey([string]$_.path) })
        $remainingBytes = [Int64]0
        foreach ($entry in $remaining) { $remainingBytes += [Int64]$entry.bytes }
        if ($remainingBytes -gt $MaxTotalBytes) {
            foreach ($entry in @($remaining | Sort-Object @{Expression = { $_.last_write_utc }; Ascending = $true}, @{Expression = { $_.path }; Ascending = $true})) {
                if ($remainingBytes -le $MaxTotalBytes) { break }
                $deleteSet[[string]$entry.path] = "max_total_bytes_exceeded"
                $remainingBytes -= [Int64]$entry.bytes
            }
        }

        foreach ($entry in @($scanned | Sort-Object @{Expression = { $_.last_write_utc }; Ascending = $true}, @{Expression = { $_.path }; Ascending = $true})) {
            if (-not $deleteSet.ContainsKey([string]$entry.path)) { continue }
            $full = [string]$entry.full_path
            try {
                if (
                    (Test-Path -LiteralPath $full -PathType Leaf) -and
                    (Test-ImmoAppPathUnderRoot -Root $logsRootFull -Path $full) -and
                    -not (Test-ImmoAppPathHasReparsePoint -Path $full)
                ) {
                    $bytesBeforeDelete = [Int64]$entry.bytes
                    try {
                        $bytesBeforeDelete = [Int64](Get-Item -LiteralPath $full -Force -ErrorAction Stop).Length
                    }
                    catch {
                        $bytesBeforeDelete = [Int64]$entry.bytes
                    }
                    Remove-Item -LiteralPath $full -Force
                    if (Test-Path -LiteralPath $full -PathType Leaf) {
                        Add-LogRetentionFailedDelete -Entry $entry -Reason "delete_incomplete"
                    }
                    else {
                        $deletedBytes += $bytesBeforeDelete
                        $deleted.Add([ordered]@{
                            path = [string]$entry.path
                            bytes = $bytesBeforeDelete
                            reason = [string]$deleteSet[[string]$entry.path]
                        }) | Out-Null
                    }
                }
                elseif (Test-Path -LiteralPath $full -PathType Leaf) {
                    Add-LogRetentionSkip -Path $full -Reason "delete_safety_check_failed"
                    Add-LogRetentionFailedDelete -Entry $entry -Reason "delete_safety_check_failed"
                }
                else {
                    Add-LogRetentionSkip -Path $full -Reason "selected_file_missing_before_delete"
                }
            }
            catch {
                Add-LogRetentionSkip -Path $full -Reason ("delete_failed:" + $_.Exception.GetType().Name)
                Add-LogRetentionFailedDelete -Entry $entry -Reason ("delete_failed:" + $_.Exception.GetType().Name)
            }
        }

        $remainingByPath = @{}
        foreach ($entry in @(Get-LogRetentionManagedRuntimeFiles)) {
            $remainingByPath[[string]$entry.path] = $entry
            $retainedBytes += [Int64]$entry.bytes
            if ($entry.last_write_utc -lt $cutoff) {
                $ageRetentionSatisfied = $false
            }
        }
        $sizeCapSatisfied = ($retainedBytes -le $MaxTotalBytes)
        foreach ($selectedPath in @($deleteSet.Keys)) {
            if ($remainingByPath.ContainsKey([string]$selectedPath)) {
                Add-LogRetentionFailedDelete -Entry $remainingByPath[[string]$selectedPath] -Reason "selected_file_still_present"
            }
        }
        if ($failedDeletes.Count -gt 0) {
            $proofResult = "NO-GO"
            $reasonCode = "managed_runtime_log_retention_delete_incomplete"
        }
        elseif (-not $sizeCapSatisfied) {
            $proofResult = "NO-GO"
            $reasonCode = "managed_runtime_log_retention_size_cap_not_satisfied"
        }
        elseif (-not $ageRetentionSatisfied) {
            $proofResult = "NO-GO"
            $reasonCode = "managed_runtime_log_retention_age_retention_not_satisfied"
        }
    }
    catch {
        $proofResult = "NO-GO"
        $reason = [string]$_.Exception.Message
        if ($reason.Contains("|")) { $reasonCode = $reason.Split("|", 2)[0] } else { $reasonCode = "managed_runtime_log_retention_failed" }
        Add-LogRetentionSkip -Path $logsRootFull -Reason $reasonCode
    }

    $payload = [ordered]@{
        kind = "immoapp_managed_runtime_log_retention_evidence"
        schema_version = 1
        created_at_utc = $createdAt.ToString("o")
        proof_result = $proofResult
        reason_code = $reasonCode
        logs_root = $logsRootFull
        retention_days = [int]$RetentionDays
        max_total_bytes = [Int64]$MaxTotalBytes
        scanned_file_count = [int]$scanned.Count
        deleted_file_count = [int]$deleted.Count
        deleted_bytes = [Int64]$deletedBytes
        retained_bytes = [Int64]$retainedBytes
        failed_delete_count = [int]$failedDeletes.Count
        failed_delete_files = @($failedDeletes.ToArray())
        size_cap_satisfied = [bool]$sizeCapSatisfied
        age_retention_satisfied = [bool]$ageRetentionSatisfied
        skipped_file_count = [int]$skipped.Count
        skipped_reasons = @($skipped.ToArray())
        deleted_files = @($deleted.ToArray())
        agency_install_status = "NO_GO"
    }
    $write = Write-ImmoAppSafeJson -Path $OutputJson -Payload $payload -ApprovedRoots @($approvedOutputRoots)
    $payload["evidence_path"] = $write.path
    $payload["evidence_sha256"] = $write.sha256
    return $payload
}

function Get-ImmoAppHubFoundationDirectoryEvidence {
    param([switch]$Create)

    $paths = Get-ImmoAppRuntimePaths
    $appRoot = [System.IO.Path]::GetFullPath($paths.AppDataRoot)
    $items = @(
        @{ Name = "config"; Path = $paths.ConfigRoot },
        @{ Name = "data"; Path = $paths.DataRoot },
        @{ Name = "logs"; Path = $paths.LogsRoot },
        @{ Name = "runtime"; Path = $paths.RuntimeRoot }
    )
    $results = New-Object System.Collections.Generic.List[object]
    $refused = New-Object System.Collections.Generic.List[string]

    foreach ($item in $items) {
        $name = [string]$item.Name
        $path = [System.IO.Path]::GetFullPath([string]$item.Path)
        $status = "validated"
        $reason = ""
        try {
            if (-not (Test-ImmoAppPathUnderRoot -Root $appRoot -Path $path)) {
                throw "directory_outside_app_root"
            }
            $existing = $path
            while (-not [string]::IsNullOrWhiteSpace($existing) -and -not (Test-Path -LiteralPath $existing)) {
                $parent = Split-Path -Parent $existing
                if ([string]::IsNullOrWhiteSpace($parent) -or $parent -eq $existing) { break }
                $existing = $parent
            }
            if (-not [string]::IsNullOrWhiteSpace($existing) -and (Test-Path -LiteralPath $existing) -and (Test-ImmoAppPathHasReparsePoint -Path $existing)) {
                throw "directory_reparse_point"
            }
            if (Test-Path -LiteralPath $path) {
                if (-not (Test-Path -LiteralPath $path -PathType Container)) {
                    throw "directory_path_is_file"
                }
                if (Test-ImmoAppPathHasReparsePoint -Path $path) {
                    throw "directory_reparse_point"
                }
                if (-not (Test-ImmoAppResolvedPathUnderRoot -Root $appRoot -Path $path)) {
                    throw "directory_resolved_outside_app_root"
                }
                $status = "existing"
            }
            elseif ($Create) {
                [System.IO.Directory]::CreateDirectory($path) | Out-Null
                if (Test-ImmoAppPathHasReparsePoint -Path $path) {
                    throw "directory_reparse_point"
                }
                if (-not (Test-ImmoAppResolvedPathUnderRoot -Root $appRoot -Path $path)) {
                    throw "directory_resolved_outside_app_root"
                }
                $status = "created"
            }
            else {
                $status = "would_create"
            }
        }
        catch {
            $status = "refused"
            $reason = [string]$_.Exception.Message
            $refused.Add("${name}:$reason") | Out-Null
        }
        $results.Add([ordered]@{
            name = $name
            path = $path
            status = $status
            reason = $reason
        }) | Out-Null
    }

    return [ordered]@{
        status = if ($refused.Count -eq 0) { "GO" } else { "NO-GO" }
        app_data_root = $appRoot
        create_requested = [bool]$Create
        refused_paths = @($refused.ToArray())
        directories = @($results.ToArray())
    }
}

function Ensure-ImmoAppSafeRuntimeDirectory {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$AppRoot,
        [Parameter(Mandatory = $true)][string]$Label
    )

    $rootFull = [System.IO.Path]::GetFullPath($AppRoot)
    $pathFull = [System.IO.Path]::GetFullPath($Path)
    if (-not (Test-ImmoAppPathUnderRoot -Root $rootFull -Path $pathFull)) {
        throw "runtime_directory_outside_app_root|$Label must be under runtime app root: $pathFull"
    }
    $existing = $pathFull
    while (-not [string]::IsNullOrWhiteSpace($existing) -and -not (Test-Path -LiteralPath $existing)) {
        $parent = Split-Path -Parent $existing
        if ([string]::IsNullOrWhiteSpace($parent) -or $parent -eq $existing) { break }
        $existing = $parent
    }
    if (-not [string]::IsNullOrWhiteSpace($existing) -and (Test-Path -LiteralPath $existing)) {
        if (Test-ImmoAppPathHasReparsePoint -Path $existing) {
            throw "runtime_directory_reparse_point|$Label parent contains a reparse point, symlink, or junction: $existing"
        }
        if (-not (Test-ImmoAppResolvedPathUnderRoot -Root $rootFull -Path $existing)) {
            throw "runtime_directory_resolved_outside_app_root|$Label parent resolves outside runtime app root: $existing"
        }
    }
    if (Test-Path -LiteralPath $pathFull) {
        if (-not (Test-Path -LiteralPath $pathFull -PathType Container)) {
            throw "runtime_directory_path_is_file|$Label path exists but is not a directory: $pathFull"
        }
    }
    else {
        [System.IO.Directory]::CreateDirectory($pathFull) | Out-Null
    }
    if (Test-ImmoAppPathHasReparsePoint -Path $pathFull) {
        throw "runtime_directory_reparse_point|$Label contains a reparse point, symlink, or junction: $pathFull"
    }
    if (-not (Test-ImmoAppResolvedPathUnderRoot -Root $rootFull -Path $pathFull)) {
        throw "runtime_directory_resolved_outside_app_root|$Label resolves outside runtime app root: $pathFull"
    }
    return $pathFull
}

function Get-ImmoAppHubFirewallRuleEvidence {
    param(
        [string]$RuleName = "ImmoApp Office Hub Front Door",
        [int]$Port = (Get-ImmoAppHubPort)
    )

    $infraPorts = @("5432", "5672", "6379", "8200", "9000", "9001", "3310", "18000")
    $base = [ordered]@{
        rule_name = $RuleName
        status = "missing"
        applied = $false
        verified = $false
        enabled = $false
        direction = ""
        action = ""
        protocol = ""
        local_port = ""
        profile = ""
        edge_traversal_policy = ""
        scope = "Private"
        reason_code = "firewall_rule_missing"
    }

    try {
        $rule = Get-NetFirewallRule -DisplayName $RuleName -ErrorAction SilentlyContinue | Select-Object -First 1
        if (-not $rule) { return $base }
        $portFilter = Get-NetFirewallPortFilter -AssociatedNetFirewallRule $rule -ErrorAction SilentlyContinue | Select-Object -First 1
        $addressFilter = Get-NetFirewallAddressFilter -AssociatedNetFirewallRule $rule -ErrorAction SilentlyContinue | Select-Object -First 1
        $protocol = if ($portFilter) { [string]$portFilter.Protocol } else { "" }
        $localPort = if ($portFilter) { [string]$portFilter.LocalPort } else { "" }
        $profile = [string]$rule.Profile
        $enabled = ([string]$rule.Enabled -eq "True")
        $direction = [string]$rule.Direction
        $action = [string]$rule.Action
        $edge = [string]$rule.EdgeTraversalPolicy
        $scope = if ($addressFilter) {
            "LocalAddress=$($addressFilter.LocalAddress);RemoteAddress=$($addressFilter.RemoteAddress)"
        } else {
            "Private"
        }
        $reasons = New-Object System.Collections.Generic.List[string]
        if (-not $enabled) { $reasons.Add("firewall_rule_disabled") | Out-Null }
        if ($direction -ne "Inbound") { $reasons.Add("firewall_rule_wrong_direction") | Out-Null }
        if ($action -ne "Allow") { $reasons.Add("firewall_rule_wrong_action") | Out-Null }
        if ($protocol -ne "TCP") { $reasons.Add("firewall_rule_wrong_protocol") | Out-Null }
        if ($localPort -ne [string]$Port) { $reasons.Add("firewall_rule_wrong_port") | Out-Null }
        if ($localPort -in $infraPorts) { $reasons.Add("firewall_rule_infra_or_backend_port") | Out-Null }
        if ($profile -ne "Private") { $reasons.Add("firewall_rule_wrong_profile") | Out-Null }
        $valid = ($reasons.Count -eq 0)
        return [ordered]@{
            rule_name = $RuleName
            status = if ($valid) { "already_present_valid" } else { "already_present_invalid" }
            applied = $true
            verified = $valid
            enabled = $enabled
            direction = $direction
            action = $action
            protocol = $protocol
            local_port = $localPort
            profile = $profile
            edge_traversal_policy = $edge
            scope = $scope
            reason_code = if ($valid) { "firewall_rule_valid" } else { ($reasons.ToArray() -join ";") }
        }
    }
    catch {
        $base.status = "failed"
        $base.reason_code = "firewall_rule_query_failed"
        $base.error = $_.Exception.Message
        return $base
    }
}

function Ensure-ImmoAppHubFirewallRule {
    param(
        [switch]$ValidateOnly,
        [switch]$LanAccess,
        [switch]$Requested
    )

    $ruleName = "ImmoApp Office Hub Front Door"
    $port = Get-ImmoAppHubPort
    if (-not $LanAccess) {
        return [ordered]@{
            rule_name = $ruleName
            status = "skipped_local_only"
            applied = $false
            verified = $false
            enabled = $false
            direction = ""
            action = ""
            protocol = "TCP"
            local_port = [string]$port
            profile = "Private"
            edge_traversal_policy = ""
            scope = "localhost_only"
            reason_code = "lan_access_disabled"
        }
    }
    if (-not $Requested) {
        return [ordered]@{
            rule_name = $ruleName
            status = "skipped_no_lan_requested"
            applied = $false
            verified = $false
            enabled = $false
            direction = "Inbound"
            action = "Allow"
            protocol = "TCP"
            local_port = [string]$port
            profile = "Private"
            edge_traversal_policy = ""
            scope = "Private"
            reason_code = "firewall_rule_not_requested_for_lan"
        }
    }
    if ($ValidateOnly) {
        return [ordered]@{
            rule_name = $ruleName
            status = "intended"
            applied = $false
            verified = $false
            enabled = $true
            direction = "Inbound"
            action = "Allow"
            protocol = "TCP"
            local_port = [string]$port
            profile = "Private"
            edge_traversal_policy = ""
            scope = "Private"
            reason_code = "dry_run_not_applied"
        }
    }

    $existing = Get-ImmoAppHubFirewallRuleEvidence -RuleName $ruleName -Port $port
    if ([string]$existing.status -eq "already_present_valid") { return $existing }
    $wasInvalid = ([string]$existing.status -eq "already_present_invalid")

    try {
        $principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
        if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
            $existing.status = "needs_admin"
            $existing.reason_code = "firewall_rule_needs_admin"
            return $existing
        }
        if ($wasInvalid) {
            Remove-NetFirewallRule -DisplayName $ruleName -ErrorAction Stop | Out-Null
        }
        New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Action Allow -Protocol TCP -LocalPort $port -Profile Private | Out-Null
        $created = Get-ImmoAppHubFirewallRuleEvidence -RuleName $ruleName -Port $port
        if ([string]$created.status -eq "already_present_valid") {
            $created.status = if ($wasInvalid) { "updated" } else { "created" }
            $created.reason_code = if ($wasInvalid) {
                "firewall_rule_updated_and_verified"
            }
            else {
                "firewall_rule_created_and_verified"
            }
        }
        return $created
    }
    catch {
        return [ordered]@{
            rule_name = $ruleName
            status = "failed"
            applied = $false
            verified = $false
            enabled = $false
            direction = "Inbound"
            action = "Allow"
            protocol = "TCP"
            local_port = [string]$port
            profile = "Private"
            edge_traversal_policy = ""
            scope = "Private"
            reason_code = if ($wasInvalid) { "firewall_rule_update_failed" } else { "firewall_rule_create_failed" }
            error = $_.Exception.Message
        }
    }
}

function Test-ImmoAppCurrentProcessElevated {
    if (
        $env:IMMOAPP_ALLOW_TEST_PROGRAMDATA_ROOT -in @("1", "true", "yes", "on") -and
        -not [string]::IsNullOrWhiteSpace([string]$env:IMMOAPP_TEST_IS_ADMIN)
    ) {
        return ([string]$env:IMMOAPP_TEST_IS_ADMIN).ToLowerInvariant() -in @("1", "true", "yes", "on")
    }
    $principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Test-ImmoAppIPv4Address {
    param([string]$Address)
    $parsed = [System.Net.IPAddress]::None
    return (
        [System.Net.IPAddress]::TryParse($Address, [ref]$parsed) -and
        $parsed.AddressFamily -eq [System.Net.Sockets.AddressFamily]::InterNetwork
    )
}

function Get-ImmoAppManagedWslRuntimeIp {
    param([string]$DistroName = "ImmoAppRuntime")

    if (
        $env:IMMOAPP_ALLOW_TEST_PROGRAMDATA_ROOT -in @("1", "true", "yes", "on") -and
        -not [string]::IsNullOrWhiteSpace([string]$env:IMMOAPP_TEST_MANAGED_WSL_IP)
    ) {
        $testIp = [string]$env:IMMOAPP_TEST_MANAGED_WSL_IP
        if (Test-ImmoAppIPv4Address -Address $testIp -and $testIp -ne "127.0.0.1") {
            return $testIp
        }
        return ""
    }

    try {
        $raw = & wsl.exe -d $DistroName -- hostname -I 2>$null
        if ($LASTEXITCODE -ne 0) { return "" }
        foreach ($candidate in (($raw | Out-String).Trim() -split "\s+")) {
            $value = ([string]$candidate).Trim()
            if (Test-ImmoAppIPv4Address -Address $value -and $value -ne "127.0.0.1") {
                return $value
            }
        }
    }
    catch {
        return ""
    }
    return ""
}

function Get-ImmoAppHubWslPortProxyEvidence {
    param(
        [Parameter(Mandatory = $true)][string]$ListenAddress,
        [Parameter(Mandatory = $true)][string]$ConnectAddress,
        [int]$Port = (Get-ImmoAppHubPort)
    )

    $base = [ordered]@{
        status = "missing"
        applied = $false
        verified = $false
        listen_address = $ListenAddress
        listen_port = [int]$Port
        connect_address = $ConnectAddress
        connect_port = [int]$Port
        rule_scope = "wsl_portproxy"
        reason_code = "portproxy_rule_missing"
        entries = @()
    }
    if (-not (Test-ImmoAppIPv4Address -Address $ListenAddress) -or $ListenAddress -eq "127.0.0.1") {
        $base.status = "invalid"
        $base.reason_code = "portproxy_listen_address_not_lan_ipv4"
        return $base
    }
    if (-not (Test-ImmoAppIPv4Address -Address $ConnectAddress) -or $ConnectAddress -eq "127.0.0.1") {
        $base.status = "invalid"
        $base.reason_code = "portproxy_connect_address_not_wsl_ipv4"
        return $base
    }

    try {
        $text = ""
        if (
            $env:IMMOAPP_ALLOW_TEST_PROGRAMDATA_ROOT -in @("1", "true", "yes", "on") -and
            -not [string]::IsNullOrWhiteSpace([string]$env:IMMOAPP_TEST_PORTPROXY_TEXT)
        ) {
            $text = [string]$env:IMMOAPP_TEST_PORTPROXY_TEXT
        }
        else {
            $text = (& netsh interface portproxy show v4tov4 2>$null | Out-String)
        }

        $entries = New-Object System.Collections.Generic.List[object]
        foreach ($line in ($text -split "(`r`n|`n|`r)")) {
            if ($line -match "^\s*(?<listen>\d{1,3}(?:\.\d{1,3}){3})\s+(?<listenPort>\d+)\s+(?<connect>\d{1,3}(?:\.\d{1,3}){3})\s+(?<connectPort>\d+)\s*$") {
                $entries.Add([ordered]@{
                    listen_address = [string]$Matches.listen
                    listen_port = [int]$Matches.listenPort
                    connect_address = [string]$Matches.connect
                    connect_port = [int]$Matches.connectPort
                }) | Out-Null
            }
        }
        $base.entries = @($entries.ToArray())
        foreach ($entry in @($base.entries)) {
            if ([string]$entry.listen_address -eq $ListenAddress -and [int]$entry.listen_port -eq [int]$Port) {
                $base.applied = $true
                if ([string]$entry.connect_address -eq $ConnectAddress -and [int]$entry.connect_port -eq [int]$Port) {
                    $base.status = "already_present_valid"
                    $base.verified = $true
                    $base.reason_code = "portproxy_rule_valid"
                    return $base
                }
                $base.status = "already_present_invalid"
                $base.reason_code = "portproxy_rule_wrong_target"
                return $base
            }
        }
        return $base
    }
    catch {
        $base.status = "failed"
        $base.reason_code = "portproxy_rule_query_failed"
        $base.error = $_.Exception.Message
        return $base
    }
}

function Ensure-ImmoAppHubWslPortProxy {
    param(
        [switch]$ValidateOnly,
        [switch]$LanAccess,
        [switch]$Requested,
        [string]$DistroName = "ImmoAppRuntime",
        [string]$ListenAddress = "",
        [int]$Port = (Get-ImmoAppHubPort)
    )

    if (-not $LanAccess) {
        return [ordered]@{
            status = "skipped_local_only"
            applied = $false
            verified = $false
            listen_address = "127.0.0.1"
            listen_port = [int]$Port
            connect_address = ""
            connect_port = [int]$Port
            rule_scope = "wsl_portproxy"
            reason_code = "lan_access_disabled"
        }
    }
    if (-not $Requested) {
        return [ordered]@{
            status = "skipped_no_lan_requested"
            applied = $false
            verified = $false
            listen_address = $ListenAddress
            listen_port = [int]$Port
            connect_address = ""
            connect_port = [int]$Port
            rule_scope = "wsl_portproxy"
            reason_code = "portproxy_not_requested_for_lan"
        }
    }
    if ([string]::IsNullOrWhiteSpace($ListenAddress)) {
        $ListenAddress = Get-ImmoAppPreferredLanAddress
    }
    $connectAddress = Get-ImmoAppManagedWslRuntimeIp -DistroName $DistroName
    if ([string]::IsNullOrWhiteSpace($connectAddress)) {
        return [ordered]@{
            status = "failed"
            applied = $false
            verified = $false
            listen_address = $ListenAddress
            listen_port = [int]$Port
            connect_address = ""
            connect_port = [int]$Port
            rule_scope = "wsl_portproxy"
            reason_code = "managed_wsl2_ip_unavailable"
        }
    }
    if ($ValidateOnly) {
        return [ordered]@{
            status = "intended"
            applied = $false
            verified = $false
            listen_address = $ListenAddress
            listen_port = [int]$Port
            connect_address = $connectAddress
            connect_port = [int]$Port
            rule_scope = "wsl_portproxy"
            reason_code = "dry_run_not_applied"
        }
    }

    $existing = Get-ImmoAppHubWslPortProxyEvidence -ListenAddress $ListenAddress -ConnectAddress $connectAddress -Port $Port
    if ([string]$existing.status -eq "already_present_valid") { return $existing }
    if (-not (Test-ImmoAppCurrentProcessElevated)) {
        $existing.status = "needs_admin"
        $existing.reason_code = "portproxy_rule_needs_admin"
        return $existing
    }

    try {
        & netsh interface portproxy delete v4tov4 listenaddress=$ListenAddress listenport=$Port 2>$null | Out-Null
        & netsh interface portproxy add v4tov4 listenaddress=$ListenAddress listenport=$Port connectaddress=$connectAddress connectport=$Port | Out-Null
        $created = Get-ImmoAppHubWslPortProxyEvidence -ListenAddress $ListenAddress -ConnectAddress $connectAddress -Port $Port
        if ([string]$created.status -eq "already_present_valid") {
            $created.status = if ([string]$existing.status -eq "already_present_invalid") { "updated" } else { "created" }
            $created.reason_code = "portproxy_rule_created_and_verified"
        }
        return $created
    }
    catch {
        return [ordered]@{
            status = "failed"
            applied = $false
            verified = $false
            listen_address = $ListenAddress
            listen_port = [int]$Port
            connect_address = $connectAddress
            connect_port = [int]$Port
            rule_scope = "wsl_portproxy"
            reason_code = "portproxy_rule_create_failed"
            error = $_.Exception.Message
        }
    }
}

function Test-ImmoAppInstalledSource {
    param([Parameter(Mandatory = $true)][string]$Source)
    return ($Source -in @("installed", "installed_app", "installed_programdata"))
}

function Get-ImmoAppCurrentScriptRootSource {
    param([string]$ScriptRoot = $PSScriptRoot)

    $root = [System.IO.Path]::GetFullPath($ScriptRoot).TrimEnd("\", "/")
    $repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..")).TrimEnd("\", "/")
    $looksLikeSourceRepo = (
        (Test-Path -LiteralPath (Join-Path $repoRoot ".git")) -and
        (Test-Path -LiteralPath (Join-Path $repoRoot "pyproject.toml") -PathType Leaf) -and
        (Test-Path -LiteralPath (Join-Path $repoRoot "app\main.py") -PathType Leaf)
    )
    if ($looksLikeSourceRepo -and (Test-ImmoAppPathUnderRoot -Root $repoRoot -Path $root)) {
        return "repo_dev"
    }

    $paths = Get-ImmoAppRuntimePaths
    $programDataScripts = [System.IO.Path]::GetFullPath($paths.InstalledScriptsRoot).TrimEnd("\", "/")
    if (Test-ImmoAppPathUnderRoot -Root $programDataScripts -Path $root) {
        return "installed_programdata"
    }

    $localAppScripts = if ($env:LOCALAPPDATA) {
        [System.IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA "Programs\ImmoApp Beta\scripts")).TrimEnd("\", "/")
    } else {
        ""
    }
    if ($localAppScripts -and (Test-ImmoAppPathUnderRoot -Root $localAppScripts -Path $root)) {
        return "installed_app"
    }

    $appRoot = Split-Path -Parent $root
    $installedAppIdentity = Join-Path $appRoot "_internal\app\installer_build_identity.json"
    if (
        (Test-Path -LiteralPath (Join-Path $root "hub_manager.ps1") -PathType Leaf) -and
        (Test-Path -LiteralPath (Join-Path $appRoot "ImmoApp.exe") -PathType Leaf) -and
        (Test-Path -LiteralPath $installedAppIdentity -PathType Leaf)
    ) {
        return "installed_app"
    }

    return "missing"
}

function Resolve-ImmoAppHubManagerScript {
    $currentScriptRootSource = Get-ImmoAppCurrentScriptRootSource
    $currentHubManager = Join-Path $PSScriptRoot "hub_manager.ps1"
    if ($currentScriptRootSource -in @("installed_app", "installed_programdata", "repo_dev") -and (Test-Path -LiteralPath $currentHubManager -PathType Leaf)) {
        return [ordered]@{ path = (Resolve-Path -LiteralPath $currentHubManager).Path; source = $currentScriptRootSource }
    }

    $paths = Get-ImmoAppRuntimePaths
    $programDataInstalled = Join-Path $paths.InstalledScriptsRoot "hub_manager.ps1"
    if (Test-Path -LiteralPath $programDataInstalled -PathType Leaf) {
        return [ordered]@{ path = (Resolve-Path -LiteralPath $programDataInstalled).Path; source = "installed_programdata" }
    }

    $localAppInstalled = if ($env:LOCALAPPDATA) { Join-Path $env:LOCALAPPDATA "Programs\ImmoApp Beta\scripts\hub_manager.ps1" } else { "" }
    if ($localAppInstalled -and (Test-Path -LiteralPath $localAppInstalled -PathType Leaf)) {
        return [ordered]@{ path = (Resolve-Path -LiteralPath $localAppInstalled).Path; source = "installed_app" }
    }

    return [ordered]@{ path = (Join-Path $PSScriptRoot "hub_manager.ps1"); source = "repo_dev" }
}

function Resolve-ImmoAppDesktopExecutable {
    $currentScriptRootSource = Get-ImmoAppCurrentScriptRootSource
    $currentAppRoot = Split-Path -Parent $PSScriptRoot
    $currentExe = Join-Path $currentAppRoot "ImmoApp.exe"
    if ($currentScriptRootSource -in @("installed_app", "installed_programdata") -and (Test-Path -LiteralPath $currentExe -PathType Leaf)) {
        return [ordered]@{ path = (Resolve-Path -LiteralPath $currentExe).Path; source = $currentScriptRootSource }
    }
    if ($currentScriptRootSource -eq "repo_dev") {
        $repoExe = Join-Path (Get-ImmoAppRepoRoot) "dist\ImmoApp\ImmoApp.exe"
        if (Test-Path -LiteralPath $repoExe -PathType Leaf) {
            return [ordered]@{ path = (Resolve-Path -LiteralPath $repoExe).Path; source = "repo_dev" }
        }
        return [ordered]@{ path = ""; source = "missing" }
    }

    $paths = Get-ImmoAppRuntimePaths
    $programDataInstalled = Join-Path $paths.InstalledAppRoot "ImmoApp.exe"
    if (Test-Path -LiteralPath $programDataInstalled -PathType Leaf) {
        return [ordered]@{ path = (Resolve-Path -LiteralPath $programDataInstalled).Path; source = "installed_programdata" }
    }
    $localApp = if ($env:LOCALAPPDATA) { Join-Path $env:LOCALAPPDATA "Programs\ImmoApp Beta\ImmoApp.exe" } else { "" }
    if ($localApp -and (Test-Path -LiteralPath $localApp -PathType Leaf)) {
        return [ordered]@{ path = (Resolve-Path -LiteralPath $localApp).Path; source = "installed_app" }
    }
    return [ordered]@{ path = ""; source = "missing" }
}

function Get-ImmoAppHubRequiredComposeServices {
    return @(
        "db",
        "rabbitmq",
        "valkey",
        "minio",
        "clamav",
        "openbao",
        "web",
        "worker",
        "worker-import",
        "worker-rebuild",
        "worker-match",
        "beat"
    )
}

function Get-ImmoAppHubInfraComposeServices {
    return @("db", "rabbitmq", "valkey", "minio", "clamav", "openbao")
}

function Get-ImmoAppHubAppComposeServices {
    return @("web", "worker", "worker-import", "worker-rebuild", "worker-match", "beat")
}

function Get-ImmoAppObjectValue {
    param(
        [object]$Data,
        [Parameter(Mandatory = $true)][string]$Name
    )
    if ($null -eq $Data) { return $null }
    if ($Data -is [System.Collections.IDictionary] -and $Data.Contains($Name)) {
        return $Data[$Name]
    }
    $property = $Data.PSObject.Properties[$Name]
    if ($null -eq $property) { return $null }
    return $property.Value
}

function Convert-ImmoAppBoolean {
    param([AllowNull()]$Value)
    if ($null -eq $Value) { return $false }
    if ($Value -is [bool]) { return [bool]$Value }
    $text = ([string]$Value).Trim().ToLowerInvariant()
    return ($text -in @("1", "true", "yes", "on"))
}

function Invoke-ImmoAppHubRuntimeDetection {
    param([string]$OutputJson = "")

    $args = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", (Join-Path $PSScriptRoot "detect_hub_runtime.ps1"))
    if ($OutputJson) {
        $args += @("-OutputJson", $OutputJson)
    }
    $output = & powershell @args
    if ($LASTEXITCODE -ne 0) {
        throw "Hub runtime detection failed."
    }
    return (($output | Out-String) | ConvertFrom-Json)
}

function Resolve-ImmoAppHubRuntimeDetection {
    param([string]$RuntimeDetectionJson = "")

    if (-not [string]::IsNullOrWhiteSpace($RuntimeDetectionJson) -and (Test-Path -LiteralPath $RuntimeDetectionJson)) {
        return (Get-Content -LiteralPath $RuntimeDetectionJson -Raw | ConvertFrom-Json)
    }
    if ([string]::IsNullOrWhiteSpace($RuntimeDetectionJson)) {
        $RuntimeDetectionJson = Join-Path (Get-ImmoAppRuntimePaths).LogsRoot "hub_runtime_detection.json"
    }
    return Invoke-ImmoAppHubRuntimeDetection -OutputJson $RuntimeDetectionJson
}

function Get-ImmoAppHubRuntimeEngineInvocation {
    param([object]$RuntimeDetection = $null)

    if ($null -eq $RuntimeDetection) {
        $RuntimeDetection = Resolve-ImmoAppHubRuntimeDetection
    }
    $mode = [string](Get-ImmoAppObjectValue -Data $RuntimeDetection -Name "runtime_dependency_mode")
    $status = [string](Get-ImmoAppObjectValue -Data $RuntimeDetection -Name "agency_install_status")
    $reason = [string](Get-ImmoAppObjectValue -Data $RuntimeDetection -Name "reason")
    $command = [string](Get-ImmoAppObjectValue -Data $RuntimeDetection -Name "runtime_command")
    if ([string]::IsNullOrWhiteSpace($command)) {
        $command = [string](Get-ImmoAppObjectValue -Data $RuntimeDetection -Name "runtime_executable_path")
    }
    if ([string]::IsNullOrWhiteSpace($command) -and $mode -eq "manual_docker_desktop") {
        $command = "docker"
    }
    if ([string]::IsNullOrWhiteSpace($command)) {
        throw "Hub runtime is unavailable for engine command execution. mode=$mode status=$status reason=$reason"
    }
    if ($mode -notin @("manual_docker_desktop", "managed_container_runtime")) {
        throw "Hub runtime mode '$mode' does not provide a container engine command. status=$status reason=$reason"
    }
    $engineReachable = [string](Get-ImmoAppObjectValue -Data $RuntimeDetection -Name "docker_engine_reachable")
    if ($mode -eq "manual_docker_desktop" -and $engineReachable -notin @("True", "true", "1")) {
        throw "Manual Docker Desktop runtime is installed but not reachable. reason=$reason"
    }
    return [ordered]@{
        Command = $command
        Mode = $mode
        AgencyInstallStatus = $status
        Reason = $reason
    }
}

function Get-ImmoAppHubComposeInvocation {
    param([object]$RuntimeDetection = $null)

    if ($null -eq $RuntimeDetection) {
        $RuntimeDetection = Resolve-ImmoAppHubRuntimeDetection
    }
    $mode = [string](Get-ImmoAppObjectValue -Data $RuntimeDetection -Name "runtime_dependency_mode")
    $status = [string](Get-ImmoAppObjectValue -Data $RuntimeDetection -Name "agency_install_status")
    $reason = [string](Get-ImmoAppObjectValue -Data $RuntimeDetection -Name "reason")
    $command = [string](Get-ImmoAppObjectValue -Data $RuntimeDetection -Name "compose_command")
    $prefix = @()
    $prefixValue = Get-ImmoAppObjectValue -Data $RuntimeDetection -Name "compose_arguments_prefix"
    if ($null -ne $prefixValue) {
        $prefix = @($prefixValue)
    }
    if ([string]::IsNullOrWhiteSpace($command)) {
        if ($mode -eq "manual_docker_desktop") {
            $command = "docker"
            $prefix = @("compose")
        }
        elseif ($mode -eq "managed_container_runtime") {
            $command = [string](Get-ImmoAppObjectValue -Data $RuntimeDetection -Name "runtime_command")
            if ([string]::IsNullOrWhiteSpace($command)) {
                $command = [string](Get-ImmoAppObjectValue -Data $RuntimeDetection -Name "runtime_executable_path")
            }
            $prefix = @("compose")
        }
    }
    if ([string]::IsNullOrWhiteSpace($command)) {
        throw "Hub runtime is unavailable for Compose execution. mode=$mode status=$status reason=$reason"
    }
    if ($mode -notin @("manual_docker_desktop", "managed_container_runtime")) {
        throw "Hub runtime mode '$mode' does not provide Compose execution. status=$status reason=$reason"
    }
    $engineReachable = [string](Get-ImmoAppObjectValue -Data $RuntimeDetection -Name "docker_engine_reachable")
    $composeAvailable = [string](Get-ImmoAppObjectValue -Data $RuntimeDetection -Name "compose_available")
    if ($mode -eq "manual_docker_desktop" -and ($engineReachable -notin @("True", "true", "1") -or $composeAvailable -notin @("True", "true", "1"))) {
        throw "Manual Docker Desktop runtime is installed but engine or Compose is not reachable. reason=$reason"
    }
    return [ordered]@{
        Command = $command
        PrefixArguments = @($prefix)
        Mode = $mode
        AgencyInstallStatus = $status
        Reason = $reason
    }
}

function Invoke-ImmoAppHubRuntimeCommand {
    param(
        [Parameter(Mandatory = $true)][string[]]$RuntimeArgs,
        [switch]$NoThrow
    )

    $invocation = Get-ImmoAppHubRuntimeEngineInvocation
    $output = & $invocation.Command @RuntimeArgs
    if ($LASTEXITCODE -ne 0 -and -not $NoThrow) {
        throw "Hub runtime command failed: $($invocation.Command) $($RuntimeArgs -join ' ')"
    }
    return $output
}

function Invoke-ImmoAppHubCompose {
    param(
        [Parameter(Mandatory = $true)][string[]]$ComposeArgs,
        [switch]$NoThrow
    )

    $invocation = Get-ImmoAppHubComposeInvocation
    $arguments = @($invocation.PrefixArguments) + $ComposeArgs
    $output = & $invocation.Command @arguments
    if ($LASTEXITCODE -ne 0 -and -not $NoThrow) {
        throw "Hub Compose command failed: $($invocation.Command) $($arguments -join ' ')"
    }
    return $output
}

function Get-ImmoAppDefaultEnvFile {
    if ($env:DJANGO_ENV_FILE) {
        return $env:DJANGO_ENV_FILE
    }
    return (Get-ImmoAppRuntimePaths).EnvFile
}

function Get-ImmoAppVenvPython {
    param(
        [Parameter(Mandatory = $true)]
        [ValidateSet("server", "client")]
        [string]$Kind
    )

    $paths = Get-ImmoAppRuntimePaths
    $venvName = if ($Kind -eq "server") { "immoapp-server-py314" } else { "immoapp-client-py314" }
    return (Join-Path $paths.VenvsRoot "$venvName\Scripts\python.exe")
}

function Invoke-ImmoAppHubRuntimeProfile {
    param(
        [Parameter(Mandatory = $true)]
        [ValidateSet("generate", "print", "validate", "export-env")]
        [string]$Action,
        [string]$Format = "json"
    )

    $repoRoot = (Get-ImmoAppRepoRoot).Path
    $python = Get-ImmoAppVenvPython -Kind server
    if (-not (Test-Path -LiteralPath $python)) {
        $python = "python"
    }
    $oldPyPath = $env:PYTHONPATH
    try {
        $env:PYTHONPATH = $repoRoot
        $script = Join-Path $repoRoot "scripts\hub_runtime_profile.py"
        $output = & $python -B $script $Action --format $Format
        if ($LASTEXITCODE -ne 0) {
            throw "Hub runtime profile $Action failed."
        }
        return $output
    }
    finally {
        if ($null -ne $oldPyPath) { $env:PYTHONPATH = $oldPyPath } else { Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue }
    }
}

function Set-ImmoAppHubRuntimeProfileEnv {
    $lines = @(Invoke-ImmoAppHubRuntimeProfile -Action "generate" -Format "json")
    foreach ($line in $lines) {
        if ($line -match '^\s*"selected_profile"\s*:\s*"([^"]+)"') {
            Write-Host "Hub runtime profile selected: $($Matches[1])"
            break
        }
    }
    $envLines = @(Invoke-ImmoAppHubRuntimeProfile -Action "export-env" -Format "dotenv")
    foreach ($line in $envLines) {
        $text = [string]$line
        if ([string]::IsNullOrWhiteSpace($text)) { continue }
        $eq = $text.IndexOf("=")
        if ($eq -le 0) { continue }
        $name = $text.Substring(0, $eq)
        $value = $text.Substring($eq + 1)
        [Environment]::SetEnvironmentVariable($name, $value)
    }
}

function Ensure-ImmoAppRuntimeLayout {
    $paths = Get-ImmoAppRuntimePaths
    $foundationDirectories = Get-ImmoAppHubFoundationDirectoryEvidence -Create
    if ([string]$foundationDirectories.status -ne "GO") {
        throw "runtime_layout_foundation_directories_unsafe|Hub foundation directory setup failed: $($foundationDirectories.refused_paths -join '; ')"
    }

    $requiredDirs = @(
        $paths.AppDataRoot,
        $paths.ConfigRoot,
        $paths.SecretsRoot,
        $paths.DataRoot,
        $paths.DataPgRoot,
        $paths.DataRabbitMqRoot,
        $paths.DataValkeyRoot,
        $paths.DataMinioRoot,
        $paths.DataClamAvRoot,
        $paths.DataCaddyRoot,
        $paths.DataCaddyDataRoot,
        $paths.DataCaddyConfigRoot,
        $paths.DataAppRoot,
        $paths.DataAppCacheRoot,
        $paths.DataAppMediaRoot,
        $paths.DataAppStaticRoot,
        $paths.DataAppLogsRoot,
        $paths.DataAppBackupsRoot,
        $paths.DataAppConfigRoot,
        $paths.DataAppToolsRoot,
        $paths.DataAppTmpRoot,
        $paths.VenvsRoot,
        $paths.ToolsRoot,
        $paths.CacheRoot,
        $paths.PycacheRoot,
        $paths.LogsRoot,
        $paths.MediaRoot,
        $paths.TmpRoot,
        $paths.BackupsRoot,
        $paths.ImportsRoot,
        $paths.OfflineSyncRoot,
        $paths.ApiWriteQueueRoot
    )

    $appRoot = [System.IO.Path]::GetFullPath($paths.AppDataRoot)
    foreach ($path in $requiredDirs) {
        Ensure-ImmoAppSafeRuntimeDirectory -Path $path -AppRoot $appRoot -Label "Runtime layout directory" | Out-Null
    }

    foreach ($tool in @("ruff", "pytest", "mypy", "coverage")) {
        $toolPath = Join-Path $paths.ToolsRoot $tool
        Ensure-ImmoAppSafeRuntimeDirectory -Path $toolPath -AppRoot $appRoot -Label "Runtime tool cache directory" | Out-Null
    }

    return $paths
}

function Get-ImmoAppEnvTemplateInfo {
    $paths = Get-ImmoAppRuntimePaths
    $templatePath = Get-ImmoAppEnvTemplatePath -Name ".env.example"
    return @{
        TemplatePath = $templatePath
        EnvFilePath = $paths.EnvFile
    }
}

function Initialize-ImmoAppEnvFileFromTemplate {
    param([switch]$ValidateOnly)

    $info = Get-ImmoAppEnvTemplateInfo
    $templatePath = $info.TemplatePath
    $envFilePath = $info.EnvFilePath
    if (-not (Test-Path $templatePath)) {
        throw "Env template not found: $templatePath"
    }

    $created = $false
    if (-not (Test-Path $envFilePath)) {
        if (-not $ValidateOnly) {
            Copy-Item -Path $templatePath -Destination $envFilePath
        }
        $created = $true
    }

    return @{
        Path = $envFilePath
        TemplatePath = $templatePath
        Exists = (Test-Path $envFilePath)
        Created = $created
    }
}

function Initialize-ImmoAppBootstrapSecretsFile {
    param([switch]$ValidateOnly)

    $paths = Get-ImmoAppRuntimePaths
    $targetPath = $paths.BootstrapSecretsFile
    $created = $false
    $utf8NoBom = [System.Text.UTF8Encoding]::new($false)

    if (-not (Test-Path $targetPath)) {
        if (-not $ValidateOnly) {
            # Windows PowerShell 5.1 `Set-Content -Encoding UTF8` writes a UTF-8 BOM.
            # OpenBao's Python seed reader expects canonical BOM-less UTF-8 JSON.
            [System.IO.File]::WriteAllText($targetPath, "{}", $utf8NoBom)
        }
        $created = $true
    }

    if (Test-Path $targetPath) {
        if (-not $ValidateOnly) {
            # Repair bootstrap files created by older Windows PowerShell builds without
            # changing their JSON content. This makes upgrades self-healing.
            $rawBytes = [System.IO.File]::ReadAllBytes($targetPath)
            $hasUtf8Bom = (
                $rawBytes.Length -ge 3 -and
                $rawBytes[0] -eq 0xEF -and
                $rawBytes[1] -eq 0xBB -and
                $rawBytes[2] -eq 0xBF
            )
            if ($hasUtf8Bom) {
                $rawText = [System.Text.Encoding]::UTF8.GetString($rawBytes, 3, $rawBytes.Length - 3)
                [System.IO.File]::WriteAllText($targetPath, $rawText, $utf8NoBom)
            }
        }

        if (-not $ValidateOnly -and (Test-ImmoAppUsingCanonicalRuntimeRoot)) {
            # Docker Desktop accesses this bind-mounted file through the Windows host.
            # A file created by elevated Windows PowerShell under ProgramData can inherit
            # an ACL that lets the normal desktop user read it but not overwrite it.
            # openbao-seed must persist generated application secrets back to this JSON,
            # so grant the invoking Windows user read/write while keeping the file limited
            # to that user, SYSTEM, and the local Administrators group. Use SIDs so this
            # works on localized Windows installations.
            $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
            $currentSid = $identity.User.Value
            if ([string]::IsNullOrWhiteSpace($currentSid)) {
                throw "Could not resolve the current Windows user SID for bootstrap secret permissions."
            }

            & icacls.exe $targetPath /inheritance:r /grant:r "*$($currentSid):(R,W)" "*S-1-5-18:(F)" "*S-1-5-32-544:(F)" | Out-Null
            if ($LASTEXITCODE -ne 0) {
                throw "Could not set Windows permissions on bootstrap secrets file: $targetPath"
            }
        }

        try {
            $parsed = Get-Content $targetPath -Raw | ConvertFrom-Json
        }
        catch {
            throw "Bootstrap secrets file is not valid JSON: $targetPath"
        }
        if ($null -eq $parsed) {
            throw "Bootstrap secrets file is empty: $targetPath"
        }
    }

    return @{
        Path = $targetPath
        Exists = (Test-Path $targetPath)
        Created = $created
    }
}

function Get-ImmoAppBootstrapSecretValue {
    param([Parameter(Mandatory = $true)][string]$Name)

    $path = (Get-ImmoAppRuntimePaths).BootstrapSecretsFile
    if (-not (Test-Path $path)) {
        return $null
    }

    try {
        $parsed = Get-Content $path -Raw | ConvertFrom-Json
    }
    catch {
        throw "Bootstrap secrets file is not valid JSON: $path"
    }

    if ($null -eq $parsed) {
        return $null
    }

    $property = $parsed.PSObject.Properties[$Name]
    if ($null -eq $property) {
        return $null
    }

    $value = [string]$property.Value
    if ([string]::IsNullOrWhiteSpace($value)) {
        return $null
    }
    return $value
}

function Set-ImmoAppEnvFromBootstrapSecrets {
    param(
        [Parameter(Mandatory = $true)][string[]]$Names,
        [switch]$Overwrite
    )

    foreach ($name in $Names) {
        $existing = [Environment]::GetEnvironmentVariable($name, "Process")
        if (-not $Overwrite -and -not [string]::IsNullOrWhiteSpace($existing)) {
            continue
        }

        $value = Get-ImmoAppBootstrapSecretValue -Name $name
        if ($null -ne $value) {
            [Environment]::SetEnvironmentVariable($name, $value, "Process")
        }
    }
}

function Get-ImmoAppPython314Command {
    $candidates = @(
        @{
            FilePath = "py"
            Arguments = @("-3.14")
            DisplayName = "py -3.14"
        },
        @{
            FilePath = "python"
            Arguments = @()
            DisplayName = "python"
        }
    )

    foreach ($candidate in $candidates) {
        if (-not (Get-Command $candidate.FilePath -ErrorAction SilentlyContinue)) {
            continue
        }

        try {
            $output = & $candidate.FilePath @($candidate.Arguments + @("--version")) 2>&1
            if ($LASTEXITCODE -ne 0) {
                continue
            }
            $version = (($output | Out-String).Trim())
            if ($version -match "^Python 3\.14(\.|$)") {
                return $candidate
            }
        }
        catch {
            continue
        }
    }

    $bootstrapScript = Join-Path $PSScriptRoot "bootstrap_local_runtime.ps1"
    throw "Python 3.14 was not found on PATH. Install Python 3.14 and rerun $bootstrapScript."
}

function Invoke-ImmoAppPython314 {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )

    $command = Get-ImmoAppPython314Command
    & $command.FilePath @($command.Arguments + $Arguments)
    if ($LASTEXITCODE -ne 0) {
        throw "Python 3.14 command failed: $($command.DisplayName) $($Arguments -join ' ')"
    }
}

function Ensure-ImmoAppVenv {
    param(
        [Parameter(Mandatory = $true)]
        [ValidateSet("server", "client")]
        [string]$Kind,
        [Parameter(Mandatory = $true)]
        [string]$RequirementsPath,
        [switch]$ValidateOnly
    )

    if (-not (Test-Path $RequirementsPath)) {
        throw "Requirements file not found: $RequirementsPath"
    }

    $venvPython = Get-ImmoAppVenvPython -Kind $Kind
    $venvRoot = Split-Path -Parent (Split-Path -Parent $venvPython)
    $created = $false

    if (-not (Test-Path $venvRoot)) {
        if (-not $ValidateOnly) {
            New-Item -ItemType Directory -Path $venvRoot -Force | Out-Null
        }
    }

    if (-not (Test-Path $venvPython)) {
        if (-not $ValidateOnly) {
            Invoke-ImmoAppPython314 -Arguments @("-m", "venv", $venvRoot)
        }
        $created = $true
    }

    if (-not $ValidateOnly) {
        # Keep pip's verbose output visible/loggable without leaking it into the
        # function's success-output stream. The caller expects this function to
        # return exactly one state object; leaked native-command stdout turns the
        # result into an Object[] and breaks StrictMode callers such as quickstart.ps1.
        # Let pip own its retry policy. Windows PowerShell 5.1 can promote native
        # stderr (including harmless pip retry warnings) to NativeCommandError when
        # the script-wide ErrorActionPreference is Stop. Temporarily relax only
        # around the native pip process, then decide success from its real exit code.
        # Do not pre-upgrade pip: the requirements files already pin the intended
        # pip version, and an extra upgrade creates unnecessary network work.
        # The requirement sets are exact-pinned, so `pip install -r` is sufficient
        # to synchronize versions. Avoid `--upgrade`, which needlessly re-queries
        # PyPI on every Quick Start rerun even when the venv is already correct.
        $previousErrorActionPreference = $ErrorActionPreference
        try {
            $ErrorActionPreference = "Continue"
            $pipInstallOutput = @(& $venvPython -m pip --disable-pip-version-check install -r $RequirementsPath 2>&1)
            $pipInstallExitCode = $LASTEXITCODE
        }
        finally {
            $ErrorActionPreference = $previousErrorActionPreference
        }

        foreach ($line in $pipInstallOutput) {
            Write-Host $line
        }
        if ($pipInstallExitCode -ne 0) {
            throw "Failed to install requirements from $RequirementsPath into $venvRoot (pip exit code $pipInstallExitCode)"
        }
    }

    return @{
        Kind = $Kind
        Path = $venvRoot
        PythonPath = $venvPython
        RequirementsPath = $RequirementsPath
        Exists = (Test-Path $venvPython)
        Created = $created
    }
}

function Assert-ImmoAppVenvPython {
    param(
        [Parameter(Mandatory = $true)]
        [ValidateSet("server", "client")]
        [string]$Kind,
        [string]$Purpose = "this command"
    )

    $venvPython = Get-ImmoAppVenvPython -Kind $Kind
    if (-not (Test-Path $venvPython)) {
        $bootstrapScript = Join-Path $PSScriptRoot "bootstrap_local_runtime.ps1"
        throw "$($Kind.Substring(0, 1).ToUpper() + $Kind.Substring(1)) venv python not found at $venvPython. Run '$bootstrapScript' before $Purpose."
    }
    return $venvPython
}

function Read-ImmoAppEnvFile {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    $values = @{}
    if (-not (Test-Path $Path)) {
        return $values
    }

    foreach ($rawLine in Get-Content $Path) {
        $line = $rawLine.Trim()
        if ([string]::IsNullOrWhiteSpace($line)) { continue }
        if ($line.StartsWith("#")) { continue }
        $eq = $line.IndexOf("=")
        if ($eq -le 0) { continue }
        $name = $line.Substring(0, $eq).Trim()
        if ([string]::IsNullOrWhiteSpace($name)) { continue }
        $value = $line.Substring($eq + 1).Trim()
        if (
            ($value.StartsWith("'") -and $value.EndsWith("'")) -or
            ($value.StartsWith('"') -and $value.EndsWith('"'))
        ) {
            $value = $value.Substring(1, $value.Length - 2)
        }
        $values[$name] = $value
    }

    return $values
}

function Set-ImmoAppEnvFileValue {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Value
    )

    $parent = Split-Path -Parent $Path
    if ($parent -and -not (Test-Path -LiteralPath $parent)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    $lines = @()
    if (Test-Path -LiteralPath $Path) {
        $lines = @(Get-Content -LiteralPath $Path)
    }
    $updated = $false
    $next = New-Object System.Collections.Generic.List[string]
    foreach ($rawLine in $lines) {
        $line = [string]$rawLine
        $trimmed = $line.Trim()
        if (-not $trimmed.StartsWith("#") -and $trimmed.Contains("=")) {
            $eq = $trimmed.IndexOf("=")
            $key = $trimmed.Substring(0, $eq).Trim()
            if ($key -eq $Name) {
                $next.Add("$Name=$Value")
                $updated = $true
                continue
            }
        }
        $next.Add($line)
    }
    if (-not $updated) {
        $next.Add("$Name=$Value")
    }
    $next | Set-Content -LiteralPath $Path -Encoding UTF8
}

function Test-ImmoAppLocalhostUrl {
    param([string]$Url)
    if ([string]::IsNullOrWhiteSpace($Url)) { return $false }
    try { $uri = [Uri]$Url } catch { return $false }
    return $uri.Host.Trim().ToLowerInvariant() -in @("localhost", "127.0.0.1", "::1")
}

function Test-ImmoAppIpAddressText {
    param([string]$Value)
    if ([string]::IsNullOrWhiteSpace($Value)) { return $false }
    $address = [System.Net.IPAddress]::None
    return [System.Net.IPAddress]::TryParse($Value.Trim(), [ref]$address)
}

function Assert-ImmoAppHubDisplayName {
    param([Parameter(Mandatory = $true)][string]$HubDisplayName)

    $help = Get-ImmoAppHubIdentityDisplayNameHelp
    $name = ($HubDisplayName -replace "\s+", " ").Trim()
    if ($name.Length -lt 3 -or $name.Length -gt 60) {
        throw "invalid_hub_display_name|$help"
    }
    if ($name -match "[/:\\?#@\[\]]" -or $name -match "^\w+://") {
        throw "invalid_hub_display_name_url|$help"
    }
    $lower = $name.ToLowerInvariant()
    if ($lower -in @("localhost", "127.0.0.1", "::1")) {
        throw "invalid_hub_display_name_localhost|$help"
    }
    if (Test-ImmoAppIpAddressText -Value $name) {
        throw "invalid_hub_display_name_ip|$help"
    }
    $machine = [string]$env:COMPUTERNAME
    if (-not [string]::IsNullOrWhiteSpace($machine) -and $name.Equals($machine, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "invalid_hub_display_name_machine_hostname|$help"
    }
    if ($name -match "^(?i)(DESKTOP|LAPTOP|WIN)-[A-Z0-9]{5,}$") {
        throw "invalid_hub_display_name_machine_hostname|$help"
    }
    if ($name -notmatch "^[\p{L}\p{Nd}][\p{L}\p{Nd} '\-]{1,58}[\p{L}\p{Nd}]$") {
        throw "invalid_hub_display_name_characters|$help"
    }
    return $name
}

function Read-ImmoAppHubIdentity {
    param([switch]$Optional)

    $path = Get-ImmoAppHubIdentityPath
    Assert-ImmoAppCanonicalProviderConfigPathSafe -Path (Get-ImmoAppHubRuntimeProviderConfigPath) -AllowNonCanonical | Out-Null
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        if ($Optional) { return $null }
        throw "hub_identity_missing|Hub identity has not been configured. $(Get-ImmoAppHubIdentityDisplayNameHelp)"
    }
    if (Test-ImmoAppPathHasReparsePoint -Path $path) {
        throw "hub_identity_reparse_point|Hub identity path contains a reparse point, symlink, or junction."
    }
    $data = Get-Content -LiteralPath $path -Raw | ConvertFrom-Json
    if ([string](Get-ImmoAppObjectValue -Data $data -Name "kind") -ne "immoapp_hub_identity") {
        throw "hub_identity_invalid_kind|Hub identity JSON has an invalid kind."
    }
    if ([int](Get-ImmoAppObjectValue -Data $data -Name "schema_version") -ne 1) {
        throw "hub_identity_invalid_schema|Hub identity JSON has an invalid schema_version."
    }
    $rawDisplayName = [string](Get-ImmoAppObjectValue -Data $data -Name "hub_display_name")
    if ([string]::IsNullOrWhiteSpace($rawDisplayName)) {
        $rawDisplayName = [string](Get-ImmoAppObjectValue -Data $data -Name "friendly_name")
    }
    $displayName = Assert-ImmoAppHubDisplayName -HubDisplayName $rawDisplayName
    $hubId = [string](Get-ImmoAppObjectValue -Data $data -Name "hub_id")
    return [ordered]@{
        path = $path
        data = $data
        hub_id = $hubId
        hub_display_name = $displayName
    }
}

function Write-ImmoAppHubIdentity {
    param(
        [Parameter(Mandatory = $true)][string]$HubDisplayName,
        [ValidateSet("installer_setup", "installer", "hub_manager", "dev_fixture")]
        [string]$Source = "installer_setup"
    )

    $paths = Ensure-ImmoAppRuntimeLayout
    $path = Get-ImmoAppHubIdentityPath
    $displayName = Assert-ImmoAppHubDisplayName -HubDisplayName $HubDisplayName
    $existing = $null
    try { $existing = Read-ImmoAppHubIdentity -Optional } catch { $existing = $null }
    $now = (Get-Date).ToUniversalTime().ToString("o")
    $createdAt = if ($existing -and $existing.data.created_at_utc) { [string]$existing.data.created_at_utc } else { $now }
    $createdBy = if ($existing -and $existing.data.created_by_windows_user) { [string]$existing.data.created_by_windows_user } else { [System.Security.Principal.WindowsIdentity]::GetCurrent().Name }
    $hubId = if ($existing -and -not [string]::IsNullOrWhiteSpace([string](Get-ImmoAppObjectValue -Data $existing.data -Name "hub_id"))) {
        [string](Get-ImmoAppObjectValue -Data $existing.data -Name "hub_id")
    }
    else {
        [System.Guid]::NewGuid().ToString("N")
    }
    $createdBySource = if ($existing -and -not [string]::IsNullOrWhiteSpace([string](Get-ImmoAppObjectValue -Data $existing.data -Name "created_by_source"))) {
        [string](Get-ImmoAppObjectValue -Data $existing.data -Name "created_by_source")
    }
    else {
        $Source
    }
    $payload = [ordered]@{
        kind = "immoapp_hub_identity"
        schema_version = 1
        hub_id = $hubId
        hub_display_name = $displayName
        friendly_name = $displayName
        created_at_utc = $createdAt
        updated_at_utc = $now
        created_by_source = $createdBySource
        updated_by_source = $Source
        created_by_windows_user = $createdBy
        updated_by_windows_user = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
        machine_hostname_readonly = $env:COMPUTERNAME
        source = $Source
    }
    $write = Write-ImmoAppSafeJson -Path $path -Payload $payload -ApprovedRoots @($paths.ConfigRoot)
    return [ordered]@{
        kind = "immoapp_hub_identity_write_result"
        schema_version = 1
        proof_result = "GO"
        path = $write.path
        sha256 = $write.sha256
        hub_id = $hubId
        hub_identity = $payload
        hostname_mutated = $false
    }
}

function Assert-ImmoAppHubStatePath {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string]$Label
    )
    if ([string]::IsNullOrWhiteSpace($Path)) {
        throw "hub_state_manifest_${Label}_missing|Hub state manifest is missing $Label."
    }
    if (-not (Test-ImmoAppPathUnderRoot -Root $Root -Path $Path)) {
        throw "hub_state_manifest_${Label}_outside_root|Hub state manifest $Label must stay under $Root."
    }
    if (Test-Path -LiteralPath $Path) {
        if (Test-ImmoAppPathHasReparsePoint -Path $Path) {
            throw "hub_state_manifest_${Label}_reparse_point|Hub state manifest $Label contains a reparse point, symlink, or junction."
        }
        if (-not (Test-ImmoAppResolvedPathUnderRoot -Root $Root -Path $Path)) {
            throw "hub_state_manifest_${Label}_resolved_outside_root|Hub state manifest $Label resolves outside $Root."
        }
    }
}

function Read-ImmoAppHubStateManifest {
    param([switch]$Optional)

    $paths = Get-ImmoAppRuntimePaths
    $path = Get-ImmoAppHubStateManifestPath
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        if ($Optional) { return $null }
        throw "hub_state_manifest_missing|Hub state manifest has not been configured."
    }
    if (Test-ImmoAppPathHasReparsePoint -Path $path) {
        throw "hub_state_manifest_reparse_point|Hub state manifest path contains a reparse point, symlink, or junction."
    }
    $identity = Read-ImmoAppHubIdentity
    $data = Get-Content -LiteralPath $path -Raw | ConvertFrom-Json
    if ([string](Get-ImmoAppObjectValue -Data $data -Name "kind") -ne "immoapp_hub_state_manifest") {
        throw "hub_state_manifest_invalid_kind|Hub state manifest JSON has an invalid kind."
    }
    if ([int](Get-ImmoAppObjectValue -Data $data -Name "schema_version") -ne 1) {
        throw "hub_state_manifest_invalid_schema|Hub state manifest JSON has an invalid schema_version."
    }
    $hubId = [string](Get-ImmoAppObjectValue -Data $data -Name "hub_id")
    if ([string]::IsNullOrWhiteSpace($hubId) -or $hubId -ne [string]$identity.hub_id) {
        throw "hub_state_manifest_identity_mismatch|Hub state manifest hub_id does not match hub_identity.json."
    }
    Assert-ImmoAppHubStatePath -Path ([string](Get-ImmoAppObjectValue -Data $data -Name "config_root")) -Root $paths.AppDataRoot -Label "config_root"
    Assert-ImmoAppHubStatePath -Path ([string](Get-ImmoAppObjectValue -Data $data -Name "data_root")) -Root $paths.AppDataRoot -Label "data_root"
    Assert-ImmoAppHubStatePath -Path ([string](Get-ImmoAppObjectValue -Data $data -Name "runtime_root")) -Root $paths.AppDataRoot -Label "runtime_root"
    Assert-ImmoAppHubStatePath -Path ([string](Get-ImmoAppObjectValue -Data $data -Name "logs_root")) -Root $paths.AppDataRoot -Label "logs_root"
    return [ordered]@{
        kind = "immoapp_hub_state_manifest_read_result"
        schema_version = 1
        proof_result = "GO"
        path = $path
        sha256 = Get-ImmoAppFileSha256 -Path $path
        hub_id = $hubId
        hub_display_name = [string]$identity.hub_display_name
        data = $data
    }
}

function Write-ImmoAppHubStateManifest {
    param(
        [ValidateSet("installer_setup", "hub_manager", "repair", "dev_fixture")]
        [string]$Source = "installer_setup"
    )

    $paths = Ensure-ImmoAppRuntimeLayout
    $identity = Read-ImmoAppHubIdentity
    if ([string]::IsNullOrWhiteSpace([string]$identity.hub_id)) {
        throw "hub_state_manifest_identity_missing_hub_id|Hub identity must have hub_id before writing state manifest."
    }
    $existing = $null
    if (Test-Path -LiteralPath (Get-ImmoAppHubStateManifestPath) -PathType Leaf) {
        $existing = Read-ImmoAppHubStateManifest
    }
    $now = (Get-Date).ToUniversalTime().ToString("o")
    $createdAt = if ($existing -and $existing.data.created_at_utc) { [string]$existing.data.created_at_utc } else { $now }
    $installLineage = if ($existing -and $existing.data.install_lineage) { [string]$existing.data.install_lineage } else { [System.Guid]::NewGuid().ToString("N") }
    $providerMode = ""
    $providerPath = Get-ImmoAppHubRuntimeProviderConfigPath
    if (Test-Path -LiteralPath $providerPath -PathType Leaf) {
        try {
            $provider = Get-Content -LiteralPath $providerPath -Raw | ConvertFrom-Json
            $providerMode = [string](Get-ImmoAppObjectValue -Data $provider -Name "provider_mode")
        }
        catch {
            $providerMode = "unreadable"
        }
    }
    $payload = [ordered]@{
        kind = "immoapp_hub_state_manifest"
        schema_version = 1
        hub_id = [string]$identity.hub_id
        hub_display_name = [string]$identity.hub_display_name
        friendly_name = [string]$identity.hub_display_name
        appdata_root = [string]$paths.AppDataRoot
        config_root = [string]$paths.ConfigRoot
        data_root = [string]$paths.DataRoot
        runtime_root = [string]$paths.RuntimeRoot
        logs_root = [string]$paths.LogsRoot
        install_lineage = $installLineage
        runtime_provider_mode = $providerMode
        database_schema_version = "unknown"
        created_at_utc = $createdAt
        updated_at_utc = $now
        created_by_source = if ($existing -and $existing.data.created_by_source) { [string]$existing.data.created_by_source } else { $Source }
        updated_by_source = $Source
        machine_hostname_readonly = $env:COMPUTERNAME
    }
    $write = Write-ImmoAppSafeJson -Path (Get-ImmoAppHubStateManifestPath) -Payload $payload -ApprovedRoots @($paths.ConfigRoot)
    return [ordered]@{
        kind = "immoapp_hub_state_manifest_write_result"
        schema_version = 1
        proof_result = "GO"
        path = $write.path
        sha256 = $write.sha256
        hub_id = [string]$identity.hub_id
        hub_state_manifest = $payload
    }
}

function Get-ImmoAppHubStateSummary {
    $identityResult = $null
    $manifestResult = $null
    $identityStatus = "NO-GO"
    $manifestStatus = "NO-GO"
    $reason = ""
    try {
        $identityResult = Read-ImmoAppHubIdentity
        $identityStatus = "GO"
    }
    catch {
        $reason = $_.Exception.Message
    }
    try {
        $manifestResult = Read-ImmoAppHubStateManifest
        $manifestStatus = "GO"
    }
    catch {
        if ([string]::IsNullOrWhiteSpace($reason)) { $reason = $_.Exception.Message }
    }
    return [ordered]@{
        kind = "immoapp_hub_state_summary"
        schema_version = 1
        created_at_utc = (Get-Date).ToUniversalTime().ToString("o")
        proof_result = if ($identityStatus -eq "GO" -and $manifestStatus -eq "GO") { "GO" } else { "NO-GO" }
        reason = $reason
        hub_identity_status = $identityStatus
        hub_state_manifest_status = $manifestStatus
        hub_id = if ($identityResult) { [string]$identityResult.hub_id } else { "" }
        hub_display_name = if ($identityResult) { [string]$identityResult.hub_display_name } else { "" }
        hub_identity_path = if ($identityResult) { [string]$identityResult.path } else { Get-ImmoAppHubIdentityPath }
        hub_state_manifest_path = if ($manifestResult) { [string]$manifestResult.path } else { Get-ImmoAppHubStateManifestPath }
        manifest = if ($manifestResult) { $manifestResult.data } else { $null }
    }
}

function Get-ImmoAppHubPreservedDataStateEvidence {
    $paths = Get-ImmoAppRuntimePaths
    $identityStatus = "NO-GO"
    $manifestStatus = "NO-GO"
    $reason = ""
    $identity = $null
    $manifest = $null
    try {
        $identity = Read-ImmoAppHubIdentity
        $identityStatus = "GO"
    }
    catch {
        $reason = $_.Exception.Message
    }
    try {
        $manifest = Read-ImmoAppHubStateManifest
        $manifestStatus = "GO"
    }
    catch {
        if ([string]::IsNullOrWhiteSpace($reason)) { $reason = $_.Exception.Message }
    }
    $dataRootPresent = Test-Path -LiteralPath $paths.DataRoot -PathType Container
    $databaseRootPresent = Test-Path -LiteralPath $paths.DataPgRoot -PathType Container
    $databaseStatePresent = $false
    if ($databaseRootPresent) {
        $databaseStatePresent = $null -ne (Get-ChildItem -LiteralPath $paths.DataPgRoot -Force -ErrorAction SilentlyContinue | Select-Object -First 1)
    }
    $proof = if ($identityStatus -eq "GO" -and $manifestStatus -eq "GO" -and $dataRootPresent -and $databaseStatePresent) { "GO" } else { "NO-GO" }
    return [ordered]@{
        kind = "immoapp_hub_preserved_data_state_evidence"
        schema_version = 1
        created_at_utc = (Get-Date).ToUniversalTime().ToString("o")
        proof_result = $proof
        reason_code = if ($proof -eq "GO") { "preserved_hub_data_detected" } elseif ($reason) { ($reason -split "\|")[0] } else { "preserved_hub_data_incomplete" }
        hub_identity_present = ($identityStatus -eq "GO")
        hub_identity_path = Get-ImmoAppHubIdentityPath
        hub_identity_sha256 = if ($identity) { Get-ImmoAppFileSha256 -Path (Get-ImmoAppHubIdentityPath) } else { "" }
        hub_state_manifest_present = ($manifestStatus -eq "GO")
        hub_state_manifest_path = Get-ImmoAppHubStateManifestPath
        hub_state_manifest_sha256 = if ($manifest) { [string]$manifest.sha256 } else { "" }
        data_root_present = [bool]$dataRootPresent
        data_root_path = [string]$paths.DataRoot
        database_state_present = [bool]$databaseStatePresent
        database_state_path = [string]$paths.DataPgRoot
        hub_id = if ($identity) { [string]$identity.hub_id } else { "" }
        hub_display_name = if ($identity) { [string]$identity.hub_display_name } else { "" }
        install_lineage = if ($manifest) { [string](Get-ImmoAppObjectValue -Data $manifest.data -Name "install_lineage") } else { "" }
    }
}

function Test-ImmoAppCurrentProcessElevated {
    $principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Test-ImmoAppDeleteHubDataAdminAllowed {
    if (Test-ImmoAppCurrentProcessElevated) { return $true }
    return (
        (Get-ImmoAppRuntimeRootSource) -eq "test_programdata_root" -and
        $env:IMMOAPP_TEST_ASSUME_WINDOWS_ADMIN -in @("1", "true", "yes", "on")
    )
}

function Convert-ImmoAppJsonBoolean {
    param([object]$Value)
    if ($Value -is [bool]) { return [bool]$Value }
    $text = [string]$Value
    return $text.Trim().ToLowerInvariant() -in @("1", "true", "yes", "on")
}

function Read-ImmoAppHubOwnerAuthorizationEvidence {
    param(
        [string]$Path,
        [string]$ExpectedAction = "delete_hub_data",
        [string]$ExpectedScope = "hub_data_delete",
        [string]$HubBaseUrl = ""
    )

    $paths = Get-ImmoAppRuntimePaths
    $identityPath = Get-ImmoAppHubIdentityPath
    $statePath = Get-ImmoAppHubStateManifestPath
    if ([string]::IsNullOrWhiteSpace($Path)) {
        throw "hub_delete_owner_authorization_required|Protected Hub Manager actions require agency owner/admin authorization evidence."
    }
    $full = [System.IO.Path]::GetFullPath($Path)
    $allowed = @($paths.ConfigRoot, $paths.LogsRoot, $paths.TmpRoot)
    $underAllowed = $false
    foreach ($root in $allowed) {
        if (Test-ImmoAppPathUnderRoot -Root $root -Path $full) { $underAllowed = $true; break }
    }
    if (-not $underAllowed) {
        throw "hub_delete_owner_authorization_path_unapproved|Owner authorization evidence must be under config, logs, or tmp roots."
    }
    if (-not (Test-Path -LiteralPath $full -PathType Leaf)) {
        throw "hub_delete_owner_authorization_missing|Owner authorization evidence file is missing."
    }
    if (Test-ImmoAppPathHasReparsePoint -Path $full) {
        throw "hub_delete_owner_authorization_reparse_point|Owner authorization evidence path contains a reparse point, symlink, or junction."
    }
    try {
        $data = Get-Content -LiteralPath $full -Raw | ConvertFrom-Json
    }
    catch {
        throw "hub_delete_owner_authorization_malformed_json|Owner authorization evidence is malformed JSON."
    }
    if ([string](Get-ImmoAppObjectValue -Data $data -Name "kind") -ne "immoapp_hub_owner_authorization_evidence") {
        throw "hub_delete_owner_authorization_invalid_kind|Owner authorization evidence has wrong kind."
    }
    if ([int](Get-ImmoAppObjectValue -Data $data -Name "schema_version") -ne 3) {
        throw "hub_delete_owner_authorization_invalid_schema|Owner authorization evidence has wrong schema_version."
    }
    if ([string](Get-ImmoAppObjectValue -Data $data -Name "source") -ne "hub_db") {
        throw "hub_delete_owner_authorization_source_invalid|Owner authorization evidence must come from the Hub DB."
    }
    $actualAction = [string](Get-ImmoAppObjectValue -Data $data -Name "action")
    if ($ExpectedAction -eq "delete_hub_data" -and [string](Get-ImmoAppObjectValue -Data $data -Name "action") -ne "delete_hub_data") {
        throw "hub_delete_owner_authorization_action_invalid|Owner authorization evidence is not bound to delete_hub_data."
    }
    if ($ExpectedAction -ne "delete_hub_data" -and $actualAction -ne $ExpectedAction) {
        throw "hub_delete_owner_authorization_action_invalid|Owner authorization evidence is not bound to $ExpectedAction."
    }
    $actualScope = [string](Get-ImmoAppObjectValue -Data $data -Name "authorization_scope")
    if ($ExpectedScope -eq "hub_data_delete" -and [string](Get-ImmoAppObjectValue -Data $data -Name "authorization_scope") -ne "hub_data_delete") {
        throw "hub_delete_owner_authorization_scope_invalid|Owner authorization evidence has wrong scope."
    }
    if ($ExpectedScope -ne "hub_data_delete" -and $actualScope -ne $ExpectedScope) {
        throw "hub_delete_owner_authorization_scope_invalid|Owner authorization evidence has wrong scope."
    }
    if ([string](Get-ImmoAppObjectValue -Data $data -Name "proof_result") -ne "GO") {
        throw "hub_delete_owner_authorization_not_go|Owner authorization evidence is not GO."
    }
    if ([string](Get-ImmoAppObjectValue -Data $data -Name "owner_authorization_status") -ne "GO") {
        throw "hub_delete_owner_authorization_not_go|Owner authorization evidence is not GO."
    }
    $role = [string](Get-ImmoAppObjectValue -Data $data -Name "authorized_role")
    if ($role -notin @("agency_owner", "agency_admin")) {
        throw "hub_delete_owner_authorization_role_invalid|Owner authorization must be agency_owner or agency_admin."
    }
    $actorRole = [string](Get-ImmoAppObjectValue -Data $data -Name "actor_role")
    $actorIsOwner = Convert-ImmoAppJsonBoolean -Value (Get-ImmoAppObjectValue -Data $data -Name "actor_is_owner")
    $actorCanHardDelete = Convert-ImmoAppJsonBoolean -Value (Get-ImmoAppObjectValue -Data $data -Name "actor_can_hard_delete")
    $actorIsSuperuser = Convert-ImmoAppJsonBoolean -Value (Get-ImmoAppObjectValue -Data $data -Name "actor_is_superuser")
    if ($role -eq "agency_owner" -and -not ($actorRole -eq "manager" -and $actorIsOwner)) {
        throw "hub_delete_owner_authorization_role_invalid|Agency owner evidence must be a manager owner."
    }
    if ($role -eq "agency_admin" -and -not ($actorIsSuperuser -or ($actorRole -eq "manager" -and $actorCanHardDelete))) {
        throw "hub_delete_owner_authorization_role_invalid|Agency admin evidence must be superuser or hard-delete manager."
    }
    if (Convert-ImmoAppJsonBoolean -Value (Get-ImmoAppObjectValue -Data $data -Name "plaintext_password_written")) {
        throw "hub_delete_owner_authorization_plaintext_password|Owner authorization evidence must not contain plaintext passwords."
    }
    if (Convert-ImmoAppJsonBoolean -Value (Get-ImmoAppObjectValue -Data $data -Name "session_token_written")) {
        throw "hub_delete_owner_authorization_session_token|Owner authorization evidence must not contain session tokens."
    }
    $createdRaw = [string](Get-ImmoAppObjectValue -Data $data -Name "created_at_utc")
    $expiresRaw = [string](Get-ImmoAppObjectValue -Data $data -Name "expires_at_utc")
    try {
        $created = [DateTimeOffset]::Parse($createdRaw).ToUniversalTime()
        $expires = [DateTimeOffset]::Parse($expiresRaw).ToUniversalTime()
    }
    catch {
        throw "hub_delete_owner_authorization_time_invalid|Owner authorization evidence has invalid timestamps."
    }
    $now = [DateTimeOffset]::UtcNow
    if ($created -gt $now.AddMinutes(5)) {
        throw "hub_delete_owner_authorization_from_future|Owner authorization evidence timestamp is in the future."
    }
    if ($expires -le $now) {
        throw "hub_delete_owner_authorization_expired|Owner authorization evidence has expired."
    }
    if (($expires - $created).TotalMinutes -gt 15) {
        throw "hub_delete_owner_authorization_ttl_too_long|Owner authorization evidence TTL is too long."
    }
    if ([string](Get-ImmoAppObjectValue -Data $data -Name "hub_identity_sha256") -ne (Get-ImmoAppFileSha256 -Path $identityPath)) {
        throw "hub_delete_owner_authorization_identity_hash_mismatch|Owner authorization evidence does not match current hub_identity.json."
    }
    if ([string](Get-ImmoAppObjectValue -Data $data -Name "hub_state_manifest_sha256") -ne (Get-ImmoAppFileSha256 -Path $statePath)) {
        throw "hub_delete_owner_authorization_state_hash_mismatch|Owner authorization evidence does not match current hub_state_manifest.json."
    }
    $currentState = Read-ImmoAppHubStateManifest
    if ([string](Get-ImmoAppObjectValue -Data $data -Name "hub_id") -ne [string](Get-ImmoAppObjectValue -Data $currentState.data -Name "hub_id")) {
        throw "hub_delete_owner_authorization_hub_mismatch|Owner authorization evidence does not match the current Hub."
    }
    if ([string](Get-ImmoAppObjectValue -Data $data -Name "hub_state_install_lineage") -ne [string](Get-ImmoAppObjectValue -Data $currentState.data -Name "install_lineage")) {
        throw "hub_delete_owner_authorization_lineage_mismatch|Owner authorization evidence does not match current Hub install lineage."
    }
    Confirm-ImmoAppHubOwnerAuthorizationWithHub `
        -Evidence $data `
        -ExpectedAction $ExpectedAction `
        -ExpectedScope $ExpectedScope `
        -HubBaseUrl $HubBaseUrl | Out-Null
    return [ordered]@{
        path = $full
        sha256 = Get-ImmoAppFileSha256 -Path $full
        data = $data
    }
}

function Read-ImmoAppHubDeleteOwnerAuthorizationEvidence {
    param([string]$Path, [string]$HubBaseUrl = "")

    return Read-ImmoAppHubOwnerAuthorizationEvidence `
        -Path $Path `
        -ExpectedAction "delete_hub_data" `
        -ExpectedScope "hub_data_delete" `
        -HubBaseUrl $HubBaseUrl
}

function Invoke-ImmoAppHubDataDeletion {
    param(
        [Parameter(Mandatory = $true)][string]$OutputJson,
        [string]$OwnerAuthorizationEvidenceJson = "",
        [string]$HubBaseUrl = "",
        [string]$TypedConfirmation = "",
        [switch]$ConfirmDeleteHubData,
        [scriptblock]$StopRuntime = $null
    )

    $paths = Ensure-ImmoAppRuntimeLayout
    $state = Get-ImmoAppHubStateSummary
    $reason = ""
    $canDelete = $true
    if (-not $ConfirmDeleteHubData) { $canDelete = $false; $reason = "hub_delete_confirm_flag_required" }
    elseif ($TypedConfirmation -cne "DELETE HUB DATA") { $canDelete = $false; $reason = "hub_delete_confirmation_text_required" }
    elseif (-not (Test-ImmoAppDeleteHubDataAdminAllowed)) { $canDelete = $false; $reason = "hub_delete_windows_admin_required" }

    $ownerEvidence = $null
    if ($canDelete) {
        try { $ownerEvidence = Read-ImmoAppHubDeleteOwnerAuthorizationEvidence -Path $OwnerAuthorizationEvidenceJson -HubBaseUrl $HubBaseUrl }
        catch { $canDelete = $false; $reason = ($_.Exception.Message -split "\|")[0] }
    }
    if ($canDelete -and [string]$state.proof_result -ne "GO") {
        $canDelete = $false
        $reason = "hub_state_not_valid_for_deletion"
    }
    if ($canDelete -and $ownerEvidence -and -not [string]::IsNullOrWhiteSpace([string](Get-ImmoAppObjectValue -Data $ownerEvidence.data -Name "hub_id"))) {
        if ([string](Get-ImmoAppObjectValue -Data $ownerEvidence.data -Name "hub_id") -ne [string]$state.hub_id) {
            $canDelete = $false
            $reason = "hub_delete_owner_authorization_hub_mismatch"
        }
    }

    $runtimeDetection = $null
    if ($canDelete) {
        try { $runtimeDetection = Resolve-ImmoAppHubRuntimeDetection }
        catch { $runtimeDetection = $null }
        if ($runtimeDetection) {
            $runtimeStartStatus = [string](Get-ImmoAppObjectValue -Data $runtimeDetection -Name "runtime_start_status")
            $frontDoorStatus = [string](Get-ImmoAppObjectValue -Data $runtimeDetection -Name "front_door_health_status")
            if ($runtimeStartStatus -eq "GO" -or $frontDoorStatus -eq "GO") {
                if ($null -eq $StopRuntime) {
                    $canDelete = $false
                    $reason = "hub_delete_runtime_still_running"
                }
                else {
                    try {
                        & $StopRuntime
                        $runtimeDetection = Resolve-ImmoAppHubRuntimeDetection
                        $runtimeStartStatus = [string](Get-ImmoAppObjectValue -Data $runtimeDetection -Name "runtime_start_status")
                        $frontDoorStatus = [string](Get-ImmoAppObjectValue -Data $runtimeDetection -Name "front_door_health_status")
                        if ($runtimeStartStatus -eq "GO" -or $frontDoorStatus -eq "GO") {
                            $canDelete = $false
                            $reason = "hub_delete_runtime_stop_unconfirmed"
                        }
                    }
                    catch {
                        $canDelete = $false
                        $reason = "hub_delete_runtime_stop_failed"
                    }
                }
            }
        }
    }

    $targetRoots = @($paths.ConfigRoot, $paths.DataRoot, $paths.RuntimeRoot)
    $auditRoot = Join-Path $paths.AppDataRoot "deletion-evidence"
    if (-not (Test-Path -LiteralPath $auditRoot)) {
        [System.IO.Directory]::CreateDirectory($auditRoot) | Out-Null
    }
    $preEvidence = [ordered]@{
        kind = "immoapp_hub_data_deletion_intent"
        schema_version = 1
        created_at_utc = (Get-Date).ToUniversalTime().ToString("o")
        hub_id = [string]$state.hub_id
        hub_display_name = [string]$state.hub_display_name
        owner_authorization_evidence_path = if ($ownerEvidence) { [string]$ownerEvidence.path } else { [string]$OwnerAuthorizationEvidenceJson }
        owner_authorization_evidence_sha256 = if ($ownerEvidence) { [string]$ownerEvidence.sha256 } else { "" }
        windows_admin_confirmed = [bool](Test-ImmoAppDeleteHubDataAdminAllowed)
        typed_confirmation_matched = ($TypedConfirmation -cne "DELETE HUB DATA") -eq $false
        target_roots = @($targetRoots)
        can_delete = [bool]$canDelete
        reason_code = $reason
    }
    $prePath = Join-Path $auditRoot ("hub_data_deletion_intent_" + [System.Guid]::NewGuid().ToString("N") + ".json")
    Write-ImmoAppSafeJson -Path $prePath -Payload $preEvidence -ApprovedRoots @($auditRoot) -Depth 8 | Out-Null

    $deleted = New-Object System.Collections.Generic.List[object]
    $failed = New-Object System.Collections.Generic.List[object]
    if ($canDelete) {
        foreach ($root in $targetRoots) {
            if (-not (Test-ImmoAppPathUnderRoot -Root $paths.AppDataRoot -Path $root)) {
                $failed.Add([ordered]@{ path = $root; reason = "target_outside_appdata_root" })
                continue
            }
            if (Test-Path -LiteralPath $root) {
                if (Test-ImmoAppPathHasReparsePoint -Path $root) {
                    $failed.Add([ordered]@{ path = $root; reason = "target_reparse_point" })
                    continue
                }
                try {
                    Remove-Item -LiteralPath $root -Recurse -Force -ErrorAction Stop
                    if (Test-Path -LiteralPath $root) {
                        $failed.Add([ordered]@{ path = $root; reason = "delete_incomplete" })
                    }
                    else {
                        $deleted.Add([ordered]@{ path = $root; reason = "deleted" })
                    }
                }
                catch {
                    $failed.Add([ordered]@{ path = $root; reason = "delete_failed:" + $_.Exception.GetType().Name })
                }
            }
        }
    }
    $proof = if ($canDelete -and $failed.Count -eq 0) { "GO" } else { "NO-GO" }
    $payload = [ordered]@{
        kind = "immoapp_hub_data_deletion_evidence"
        schema_version = 1
        created_at_utc = (Get-Date).ToUniversalTime().ToString("o")
        proof_result = $proof
        reason_code = if ($proof -eq "GO") { "hub_data_deleted" } elseif ($reason) { $reason } else { "hub_data_delete_incomplete" }
        hub_id = [string]$state.hub_id
        pre_delete_evidence_path = $prePath
        target_roots = @($targetRoots)
        deleted_roots = @($deleted.ToArray())
        failed_delete_count = [int]$failed.Count
        failed_delete_files = @($failed.ToArray())
        agency_install_status = "NO_GO"
        public_beta_status = "NO_GO"
    }
    Write-ImmoAppSafeJson -Path $OutputJson -Payload $payload -ApprovedRoots @($paths.LogsRoot, $paths.TmpRoot, $auditRoot) -Depth 10 | Out-Null
    return $payload
}

function Get-ImmoAppHostLanAddresses {
    $addresses = New-Object System.Collections.Generic.List[string]
    try {
        $candidates = [System.Net.Dns]::GetHostAddresses($env:COMPUTERNAME)
        foreach ($candidate in $candidates) {
            if ($candidate.AddressFamily -ne [System.Net.Sockets.AddressFamily]::InterNetwork) {
                continue
            }
            $text = $candidate.IPAddressToString
            if ([string]::IsNullOrWhiteSpace($text)) { continue }
            if ($text.StartsWith("127.")) { continue }
            if ($text.StartsWith("169.254.")) { continue }
            if (-not $addresses.Contains($text)) {
                $addresses.Add($text)
            }
        }
    }
    catch {
        # Fall through to the NetworkInterface path below.
    }
    try {
        $interfaces = [System.Net.NetworkInformation.NetworkInterface]::GetAllNetworkInterfaces()
        foreach ($adapter in $interfaces) {
            if ($adapter.OperationalStatus -ne [System.Net.NetworkInformation.OperationalStatus]::Up) {
                continue
            }
            foreach ($addr in $adapter.GetIPProperties().UnicastAddresses) {
                if ($addr.Address.AddressFamily -ne [System.Net.Sockets.AddressFamily]::InterNetwork) {
                    continue
                }
                $text = $addr.Address.IPAddressToString
                if ([string]::IsNullOrWhiteSpace($text)) { continue }
                if ($text.StartsWith("127.")) { continue }
                if ($text.StartsWith("169.254.")) { continue }
                if (-not $addresses.Contains($text)) {
                    $addresses.Add($text)
                }
            }
        }
    }
    catch {
        # Keep best-effort address detection non-fatal for setup/status.
    }
    return @($addresses.ToArray())
}

function Get-ImmoAppPreferredLanAddress {
    $addresses = @(Get-ImmoAppHostLanAddresses)
    if ($addresses.Count -gt 0) {
        return $addresses[0]
    }
    return "127.0.0.1"
}

function Get-ImmoAppHubPort {
    $value = if ($env:IMMOAPP_HUB_FRONT_DOOR_PORT) { [string]$env:IMMOAPP_HUB_FRONT_DOOR_PORT } else { "" }
    $webPort = ""
    if ([string]::IsNullOrWhiteSpace($value)) {
        $envFile = Get-ImmoAppDefaultEnvFile
        if (Test-Path -LiteralPath $envFile) {
            $fromFile = Read-ImmoAppEnvFile -Path $envFile
            if ($fromFile.ContainsKey("IMMOAPP_HUB_FRONT_DOOR_PORT")) {
                $value = [string]$fromFile["IMMOAPP_HUB_FRONT_DOOR_PORT"]
            }
            if ($fromFile.ContainsKey("WEB_PORT")) {
                $webPort = [string]$fromFile["WEB_PORT"]
            }
        }
    }
    if ([string]::IsNullOrWhiteSpace($value)) {
        if (-not [string]::IsNullOrWhiteSpace($webPort)) { return $webPort }
        return "8000"
    }
    return $value
}

function Get-ImmoAppHubBaseUrl {
    param([switch]$PreferLan)

    $envUrl = [string]$env:IMMOAPP_HUB_FRONT_DOOR_URL
    if (-not [string]::IsNullOrWhiteSpace($envUrl)) {
        return $envUrl.TrimEnd("/")
    }
    $envFile = Get-ImmoAppDefaultEnvFile
    if (Test-Path -LiteralPath $envFile) {
        $fromFile = Read-ImmoAppEnvFile -Path $envFile
        if ($fromFile.ContainsKey("IMMOAPP_HUB_FRONT_DOOR_URL")) {
            $frontDoorUrl = [string]$fromFile["IMMOAPP_HUB_FRONT_DOOR_URL"]
            if (-not [string]::IsNullOrWhiteSpace($frontDoorUrl)) {
                return $frontDoorUrl.TrimEnd("/")
            }
        }
    }
    $port = Get-ImmoAppHubPort
    $hostName = if ($PreferLan) { Get-ImmoAppPreferredLanAddress } else { "127.0.0.1" }
    return "http://${hostName}:$port"
}

function Set-ImmoAppHubLanRuntimeEnv {
    param(
        [Parameter(Mandatory = $true)][string]$EnvFilePath,
        [string]$HubHostName = "",
        [switch]$LanAccess
    )

    $displayName = if ($HubHostName) { Assert-ImmoAppHubDisplayName -HubDisplayName $HubHostName } else { "" }
    $hostname = $env:COMPUTERNAME
    $lanAddress = Get-ImmoAppPreferredLanAddress
    $frontDoorPort = Get-ImmoAppHubPort
    $frontDoorUrl = if ($LanAccess) { "http://${lanAddress}:$frontDoorPort" } else { "http://127.0.0.1:$frontDoorPort" }
    $backendHostPort = "18000"
    $allowed = New-Object System.Collections.Generic.List[string]
    foreach ($entry in @("localhost", "127.0.0.1", "web", "caddy", $hostname, $lanAddress)) {
        if (-not [string]::IsNullOrWhiteSpace($entry) -and -not $allowed.Contains($entry)) {
            $allowed.Add($entry)
        }
    }

    Set-ImmoAppEnvFileValue -Path $EnvFilePath -Name "IMMOAPP_ENV" -Value "office_hub"
    Set-ImmoAppEnvFileValue -Path $EnvFilePath -Name "DJANGO_DEBUG" -Value "0"
    Set-ImmoAppEnvFileValue -Path $EnvFilePath -Name "DJANGO_ALLOWED_HOSTS" -Value ($allowed.ToArray() -join ",")
    Set-ImmoAppEnvFileValue -Path $EnvFilePath -Name "WEB_PORT" -Value $frontDoorPort
    Set-ImmoAppEnvFileValue -Path $EnvFilePath -Name "IMMOAPP_BACKEND_HOST_PORT" -Value $backendHostPort
    Set-ImmoAppEnvFileValue -Path $EnvFilePath -Name "IMMOAPP_WEB_BIND_HOST" -Value "127.0.0.1"
    Set-ImmoAppEnvFileValue -Path $EnvFilePath -Name "IMMOAPP_CADDY_BIND_HOST" -Value $(if ($LanAccess) { "0.0.0.0" } else { "127.0.0.1" })
    Set-ImmoAppEnvFileValue -Path $EnvFilePath -Name "IMMOAPP_HUB_FRONT_DOOR_PORT" -Value $frontDoorPort
    Set-ImmoAppEnvFileValue -Path $EnvFilePath -Name "IMMOAPP_HUB_FRONT_DOOR_URL" -Value $frontDoorUrl
    Set-ImmoAppEnvFileValue -Path $EnvFilePath -Name "COMPOSE_PROFILES" -Value "hub-front-door"
    Set-ImmoAppEnvFileValue -Path $EnvFilePath -Name "SECURE_SSL_REDIRECT" -Value "0"
    Set-ImmoAppEnvFileValue -Path $EnvFilePath -Name "SECURE_SSL_REDIRECT_DOCKER" -Value "0"
    Set-ImmoAppEnvFileValue -Path $EnvFilePath -Name "SESSION_COOKIE_SECURE" -Value "0"
    Set-ImmoAppEnvFileValue -Path $EnvFilePath -Name "SESSION_COOKIE_SECURE_DOCKER" -Value "0"
    Set-ImmoAppEnvFileValue -Path $EnvFilePath -Name "CSRF_COOKIE_SECURE" -Value "0"
    Set-ImmoAppEnvFileValue -Path $EnvFilePath -Name "CSRF_COOKIE_SECURE_DOCKER" -Value "0"

    $env:IMMOAPP_WEB_BIND_HOST = "127.0.0.1"
    $env:IMMOAPP_CADDY_BIND_HOST = if ($LanAccess) { "0.0.0.0" } else { "127.0.0.1" }
    $env:IMMOAPP_BACKEND_HOST_PORT = $backendHostPort
    $env:IMMOAPP_HUB_FRONT_DOOR_PORT = $frontDoorPort
    $env:IMMOAPP_HUB_FRONT_DOOR_URL = $frontDoorUrl
    $env:COMPOSE_PROFILES = "hub-front-door"
    $env:DJANGO_ALLOWED_HOSTS = ($allowed.ToArray() -join ",")
    $env:DJANGO_DEBUG = "0"
    $env:IMMOAPP_ENV = "office_hub"

    return [ordered]@{
        hub_display_name = $displayName
        machine_hostname_readonly = $hostname
        lan_ip = $lanAddress
        hub_url = $frontDoorUrl
        front_door_url = $frontDoorUrl
        front_door_port = $frontDoorPort
        front_door_service = "caddy"
        backend_internal_host_port = $backendHostPort
        web_bind_host = $env:IMMOAPP_WEB_BIND_HOST
        caddy_bind_host = $env:IMMOAPP_CADDY_BIND_HOST
        allowed_hosts = @($allowed.ToArray())
        local_http_private_lan = $true
        lan_access_enabled = [bool]$LanAccess
    }
}

function Get-ImmoAppEnvPlaceholderIssues {
    param(
        [Parameter(Mandatory = $true)]
        [string]$EnvFilePath
    )

    $issues = New-Object System.Collections.Generic.List[object]
    if (-not (Test-Path $EnvFilePath)) {
        $issues.Add([pscustomobject]@{
                Key = "ENV_FILE"
                Value = ""
                Message = "Canonical env file is missing."
            })
        return $issues
    }

    $values = Read-ImmoAppEnvFile -Path $EnvFilePath
    $rules = @(
        @{
            Key = "POSTGRES_PASSWORD"
            Match = "<REPLACE_ME"
            Message = "Set the PostgreSQL application password."
        },
        @{
            Key = "POSTGRES_ADMIN_PASSWORD"
            Match = "<REPLACE_ME"
            Message = "Set the PostgreSQL admin password."
        },
        @{
            Key = "RABBITMQ_PASSWORD"
            Match = "<REPLACE_ME"
            Message = "Set the RabbitMQ password."
        },
        @{
            Key = "MINIO_ROOT_PASSWORD"
            Match = "<REPLACE_ME"
            Message = "Set the MinIO root password."
        },
        @{
            Key = "STORAGE_SECRET_KEY"
            Match = "<REPLACE_ME"
            Message = "Set the storage secret key."
        },
        @{
            Key = "MINIO_KMS_SECRET_KEY"
            Match = "<BASE64_32_BYTES>"
            Message = "Replace the example MinIO KMS secret with a real 32-byte base64 value."
        }
    )

    foreach ($rule in $rules) {
        $value = ""
        if ($values.ContainsKey($rule.Key)) {
            $value = [string]$values[$rule.Key]
        }
        if ([string]::IsNullOrWhiteSpace($value) -or $value.Contains($rule.Match)) {
            $issues.Add([pscustomobject]@{
                    Key = $rule.Key
                    Value = $value
                    Message = $rule.Message
                })
        }
    }

    return $issues
}

function Assert-ImmoAppBootstrapEnvReady {
    param(
        [Parameter(Mandatory = $true)]
        [string]$EnvFilePath,
        [Parameter(Mandatory = $true)]
        [string]$ActionName
    )

    $issues = @(Get-ImmoAppEnvPlaceholderIssues -EnvFilePath $EnvFilePath)
    if ($issues.Count -eq 0) {
        return
    }

    $bootstrapScript = Join-Path $PSScriptRoot "bootstrap_local_runtime.ps1"
    $lines = @()
    foreach ($issue in $issues) {
        $lines += " - $($issue.Key): $($issue.Message)"
    }

    throw "Bootstrap env is not ready for '$ActionName'. Update $EnvFilePath and resolve:`n$($lines -join "`n")`nRun '$bootstrapScript' first if the canonical env file has not been created yet."
}

function Get-ImmoAppHostOpenBaoAddr {
    param([string]$EnvFilePath = "")

    $addr = ""
    if ($env:BAO_ADDR) {
        $addr = $env:BAO_ADDR
    }
    elseif (-not [string]::IsNullOrWhiteSpace($EnvFilePath) -and (Test-Path $EnvFilePath)) {
        $values = Read-ImmoAppEnvFile -Path $EnvFilePath
        if ($values.ContainsKey("BAO_ADDR")) {
            $addr = [string]$values["BAO_ADDR"]
        }
    }

    if ([string]::IsNullOrWhiteSpace($addr)) {
        return "http://127.0.0.1:8200"
    }
    if ($addr -match "://openbao(?=[:/]|$)") {
        return "http://127.0.0.1:8200"
    }
    return $addr.TrimEnd("/")
}

function Test-ImmoAppOpenBaoHostReachable {
    param([string]$Addr)

    if ([string]::IsNullOrWhiteSpace($Addr)) {
        return $false
    }

    try {
        Invoke-WebRequest -Method Get -Uri "$($Addr.TrimEnd('/'))/v1/sys/health" -TimeoutSec 3 -UseBasicParsing | Out-Null
        return $true
    }
    catch {
        if ($_.Exception.Response) {
            return $true
        }
        return $false
    }
}

function Ensure-ImmoAppTools {
    $runtimePaths = Ensure-ImmoAppRuntimeLayout

    return @{
        AppDataRoot = $runtimePaths.AppDataRoot
        ToolsRoot = $runtimePaths.ToolsRoot
        CacheRoot = $runtimePaths.CacheRoot
        Pycache = $runtimePaths.PycacheRoot
    }
}

function Set-ImmoAppCacheEnv {
    param(
        [Parameter(Mandatory = $true)]
        [hashtable]$Paths
    )

    $env:PYTHONPYCACHEPREFIX = $Paths.Pycache
    $env:RUFF_CACHE_DIR = Join-Path $Paths.ToolsRoot "ruff"
    $env:MYPY_CACHE_DIR = Join-Path $Paths.ToolsRoot "mypy"
    $env:COVERAGE_FILE = Join-Path $Paths.ToolsRoot "coverage\.coverage"
    $pytestCache = Join-Path $Paths.ToolsRoot "pytest"
    $env:PYTEST_ADDOPTS = "-o cache_dir=$($pytestCache -replace '\\', '/')"
}

function Set-ImmoAppSecurityEnv {
    # Non-secret safety defaults for local tooling/tests.
    if (-not $env:ALE_KEY_VERSION) { $env:ALE_KEY_VERSION = "v1" }
    if (-not $env:ALE_SEARCH_KEY_VERSION) { $env:ALE_SEARCH_KEY_VERSION = "v1" }
    if (-not $env:IMMOAPP_REQUIRE_ALE_KEY) { $env:IMMOAPP_REQUIRE_ALE_KEY = "1" }
}

function Import-ImmoAppEnvFile {
    $envPath = Get-ImmoAppDefaultEnvFile
    if (-not (Test-Path $envPath)) {
        if ($env:IMMOAPP_ALLOW_REPO_ENV_FALLBACK -and $env:IMMOAPP_ALLOW_REPO_ENV_FALLBACK -in @("1", "true", "yes", "on")) {
            $repoRoot = Get-ImmoAppRepoRoot
            $legacy = @((Join-Path $repoRoot ".env.local"), (Join-Path $repoRoot ".env"))
            foreach ($candidate in $legacy) {
                if (Test-Path $candidate) {
                    $envPath = $candidate
                    break
                }
            }
        }
    }

    if (-not (Test-Path $envPath)) { return }

    foreach ($rawLine in Get-Content $envPath) {
        $line = $rawLine.Trim()
        if ([string]::IsNullOrWhiteSpace($line)) { continue }
        if ($line.StartsWith("#")) { continue }
        $eq = $line.IndexOf("=")
        if ($eq -le 0) { continue }
        $name = $line.Substring(0, $eq).Trim()
        if ([string]::IsNullOrWhiteSpace($name)) { continue }
        if (Get-Item "Env:$name" -ErrorAction SilentlyContinue) { continue }
        $value = $line.Substring($eq + 1).Trim()
        if (
            ($value.StartsWith("'") -and $value.EndsWith("'")) -or
            ($value.StartsWith('"') -and $value.EndsWith('"'))
        ) {
            $value = $value.Substring(1, $value.Length - 2)
        }
        Set-Item -Path "Env:$name" -Value $value
    }
}

function Set-ImmoAppHostRuntimeEndpoints {
    # Host-side tools should target Docker-published infra on numeric loopback.
    # On Windows, libpq/psycopg can spend a long time trying localhost address
    # families that Docker Desktop does not publish, so normalize both missing
    # and friendly/container hostnames to 127.0.0.1.
    if (
        -not $env:POSTGRES_HOST -or
        $env:POSTGRES_HOST -eq "db" -or
        $env:POSTGRES_HOST -eq "localhost" -or
        $env:POSTGRES_HOST -eq "::1"
    ) {
        $env:POSTGRES_HOST = "127.0.0.1"
    }
    if (-not $env:POSTGRES_PORT) {
        $env:POSTGRES_PORT = "5432"
    }
    if (-not $env:PGCONNECT_TIMEOUT) {
        $env:PGCONNECT_TIMEOUT = "5"
    }
    if (-not $env:BAO_ADDR -or $env:BAO_ADDR -match "://openbao(?=[:/]|$)") {
        $env:BAO_ADDR = "http://127.0.0.1:8200"
    }
    if (-not $env:VALKEY_URL -or $env:VALKEY_URL -match "://valkey(?=[:/]|$)") {
        $env:VALKEY_URL = "redis://127.0.0.1:6379/1"
    }
    if (-not $env:CHANNEL_LAYER_URL -or $env:CHANNEL_LAYER_URL -match "://valkey(?=[:/]|$)") {
        $env:CHANNEL_LAYER_URL = "redis://127.0.0.1:6379/3"
    }
    if (-not $env:STORAGE_ENDPOINT_URL -or $env:STORAGE_ENDPOINT_URL -match "://minio(?=[:/]|$)") {
        $env:STORAGE_ENDPOINT_URL = "http://127.0.0.1:9000"
    }
    if (-not $env:STORAGE_CLAMD_HOST -or $env:STORAGE_CLAMD_HOST -eq "clamav") {
        $env:STORAGE_CLAMD_HOST = "127.0.0.1"
    }
    if ($env:CELERY_BROKER_URL -and $env:CELERY_BROKER_URL -match "@rabbitmq(?=[:/]|$)") {
        $env:CELERY_BROKER_URL = $env:CELERY_BROKER_URL -replace "@rabbitmq(?=[:/]|$)", "@127.0.0.1"
    }
}

function Test-ImmoAppHostWindows {
    if ($PSVersionTable.PSEdition -eq "Desktop") {
        return $true
    }
    return ($env:OS -eq "Windows_NT")
}

function Test-ImmoAppWindowsVolumeMode {
    param([switch]$NoWindowsVolumes)

    if ($NoWindowsVolumes) {
        return $false
    }

    $windowsCompose = Get-ImmoAppComposeFile -Name "compose.windows.yml"
    if (-not (Test-Path $windowsCompose)) {
        return $false
    }

    $overrideRaw = if ($null -ne $env:IMMOAPP_USE_WINDOWS_VOLUMES) { $env:IMMOAPP_USE_WINDOWS_VOLUMES } else { "" }
    $override = $overrideRaw.Trim().ToLowerInvariant()
    if ($override -in @("0", "false", "no", "off")) {
        return $false
    }
    if ($override -in @("1", "true", "yes", "on")) {
        return $true
    }

    # Default to bind-volume mode on Windows hosts when compose.windows.yml is present.
    return (Test-ImmoAppHostWindows)
}
