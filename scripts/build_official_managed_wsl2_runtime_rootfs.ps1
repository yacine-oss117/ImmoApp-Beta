[CmdletBinding()]
param(
    [string]$BaseRootfsUrl = "",
    [string]$ExpectedBaseRootfsSha256 = "",
    [string]$SourceRootfsTarPath = "",
    [string]$OutputRootfsTarPath = "",
    [string]$RuntimeVersion = "0.1.0",
    [string]$BuildDistroName = "ImmoAppRuntimeBuild",
    [switch]$ConfirmBuild,
    [switch]$ConfirmReplaceBuildDistro,
    [switch]$KeepBuildDistro,
    [string]$OutputJson = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

. (Join-Path $PSScriptRoot "common.ps1")

$officialReleaseBase = "https://cloud-images.ubuntu.com/minimal/releases/noble/release/"
$officialRootfsFile = "ubuntu-24.04-minimal-cloudimg-amd64-root.tar.xz"
$officialShaFile = "SHA256SUMS"
$requiredRuntimeCommands = @(
    "opt/immoapp/runtime/bin/immoapp-runtime-identity",
    "opt/immoapp/runtime/bin/start-managed-hub",
    "opt/immoapp/runtime/bin/status-managed-hub",
    "opt/immoapp/runtime/bin/health-managed-hub",
    "opt/immoapp/runtime/bin/logs-managed-hub",
    "opt/immoapp/runtime/bin/backup-managed-hub",
    "opt/immoapp/runtime/bin/stop-managed-hub",
    "opt/immoapp/runtime/bin/restart-managed-hub",
    "opt/immoapp/runtime/bin/keepalive-managed-hub"
)
$requiredRuntimeEntries = @(
    $requiredRuntimeCommands +
    @("opt/immoapp/runtime/compose/compose.yaml")
)

function Test-OfficialUbuntuRootfsUrl {
    param([Parameter(Mandatory = $true)][string]$Url)
    try {
        $uri = [System.Uri]$Url
    }
    catch {
        return $false
    }
    return (
        $uri.Scheme -eq "https" -and
        $uri.Host.Equals("cloud-images.ubuntu.com", [System.StringComparison]::OrdinalIgnoreCase) -and
        $uri.AbsolutePath.StartsWith("/minimal/releases/noble/", [System.StringComparison]::OrdinalIgnoreCase) -and
        $uri.AbsolutePath.EndsWith("/$officialRootfsFile", [System.StringComparison]::OrdinalIgnoreCase)
    )
}

function Test-PathParentHasReparsePoint {
    param([Parameter(Mandatory = $true)][string]$Path)
    $current = [System.IO.Path]::GetFullPath($Path)
    while (-not [string]::IsNullOrWhiteSpace($current)) {
        if (Test-Path -LiteralPath $current) {
            return (Test-ImmoAppPathHasReparsePoint -Path $current)
        }
        $parent = Split-Path -Parent $current
        if ([string]::IsNullOrWhiteSpace($parent) -or $parent -eq $current) { break }
        $current = $parent
    }
    return $false
}

function Get-ApprovedWslPath {
    $systemWsl = Join-Path $env:WINDIR "System32\wsl.exe"
    $testWslPath = [Environment]::GetEnvironmentVariable("IMMOAPP_TEST_WSL_EXE")
    if (
        -not [string]::IsNullOrWhiteSpace($testWslPath) -and
        [Environment]::GetEnvironmentVariable("IMMOAPP_ALLOW_TEST_PROGRAMDATA_ROOT") -eq "1"
    ) {
        return [System.IO.Path]::GetFullPath($testWslPath)
    }
    return $systemWsl
}

function Get-ExistingWslDistros {
    param([Parameter(Mandatory = $true)][string]$WslPath)
    $text = (& $WslPath -l -q 2>$null | Out-String).Replace([string][char]0, "")
    if ($LASTEXITCODE -ne 0) {
        throw "official_rootfs_wsl_distro_list_failed|Unable to list WSL distributions."
    }
    return @(
        $text -split "(`r`n|`n|`r)" |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
            ForEach-Object { [string]$_.Trim() }
    )
}

function Invoke-WslChecked {
    param(
        [Parameter(Mandatory = $true)][string]$WslPath,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$ReasonCode
    )
    $oldErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $output = & $WslPath @Arguments 2>&1
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $oldErrorActionPreference
    }
    if ($exitCode -ne 0) {
        throw "$ReasonCode|$($output -join "`n")"
    }
    return @($output)
}

function Quote-Sh {
    param([Parameter(Mandatory = $true)][string]$Value)
    return "'" + $Value.Replace("'", "'\''") + "'"
}

function Convert-HostPathToWslMountPath {
    param([Parameter(Mandatory = $true)][string]$Path)
    $full = [System.IO.Path]::GetFullPath($Path)
    if ($full -notmatch "^([A-Za-z]):\\(.*)$") {
        throw "official_rootfs_host_path_not_convertible|Only local drive paths can be copied into the WSL build distro."
    }
    $drive = $Matches[1].ToLowerInvariant()
    $suffix = $Matches[2].Replace("\", "/")
    return "/mnt/$drive/$suffix"
}

function Invoke-BuildDistroShell {
    param(
        [Parameter(Mandatory = $true)][string]$WslPath,
        [Parameter(Mandatory = $true)][string]$DistroName,
        [Parameter(Mandatory = $true)][string]$Command,
        [Parameter(Mandatory = $true)][string]$ReasonCode
    )
    return Invoke-WslChecked -WslPath $WslPath -Arguments @("-d", $DistroName, "--", "sh", "-lc", $Command) -ReasonCode $ReasonCode
}

function Write-BuildDistroFile {
    param(
        [Parameter(Mandatory = $true)][string]$WslPath,
        [Parameter(Mandatory = $true)][string]$DistroName,
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Content,
        [string]$Mode = "0644"
    )
    $quotedPath = Quote-Sh -Value $Path
    $normalizedPath = $Path.Replace("\", "/")
    $lastSlash = $normalizedPath.LastIndexOf("/")
    $directory = if ($lastSlash -gt 0) { $normalizedPath.Substring(0, $lastSlash) } else { "/" }
    $quotedDir = Quote-Sh -Value $directory
    $tempFile = [System.IO.Path]::GetTempFileName()
    [System.IO.File]::WriteAllText($tempFile, $Content, [System.Text.UTF8Encoding]::new($false))
    $tempWslPath = Convert-HostPathToWslMountPath -Path $tempFile
    $command = "install -d -m 0755 $quotedDir; cp $(Quote-Sh -Value $tempWslPath) $quotedPath; chmod $Mode $quotedPath"
    $oldErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $WslPath -d $DistroName -- sh -lc $command 2>&1 | Out-String | Out-Null
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $oldErrorActionPreference
        Remove-Item -LiteralPath $tempFile -Force -ErrorAction SilentlyContinue
    }
    if ($exitCode -ne 0) {
        throw "official_rootfs_write_runtime_file_failed|Failed writing $Path inside $DistroName."
    }
}

function Expand-XzToTar {
    param(
        [Parameter(Mandatory = $true)][string]$XzPath,
        [Parameter(Mandatory = $true)][string]$TarPath
    )
    $pythonCandidates = @(
        (Join-Path (Get-ImmoAppCanonicalRuntimePaths).VenvsRoot "immoapp-server-py314\Scripts\python.exe"),
        "python.exe",
        "python"
    )
    $python = ""
    foreach ($candidate in $pythonCandidates) {
        try {
            $version = & $candidate -c "import lzma, sys; print(sys.version_info[0])" 2>$null
            if ($LASTEXITCODE -eq 0 -and ([string]$version).Trim() -eq "3") {
                $python = $candidate
                break
            }
        }
        catch {
            continue
        }
    }
    if ([string]::IsNullOrWhiteSpace($python)) {
        throw "official_rootfs_python_lzma_missing|Python 3 with lzma is required to expand the official rootfs tar.xz."
    }
    $code = @'
import lzma
import shutil
import sys

src, dst = sys.argv[1:3]
with lzma.open(src, "rb") as in_file, open(dst, "wb") as out_file:
    shutil.copyfileobj(in_file, out_file)
'@
    $output = $code | & $python - $XzPath $TarPath 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "official_rootfs_xz_expand_failed|$($output -join "`n")"
    }
}

function Get-TarEntries {
    param([Parameter(Mandatory = $true)][string]$Path)
    $tarPath = Join-Path $env:WINDIR "System32\tar.exe"
    if (-not (Test-Path -LiteralPath $tarPath -PathType Leaf)) {
        $tarPath = "tar.exe"
    }
    $output = & $tarPath -tf $Path 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "official_rootfs_final_tar_invalid|Final rootfs tar could not be listed."
    }
    return @(
        $output |
            ForEach-Object { ([string]$_).Trim().Replace("\", "/").TrimStart("/") } |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
            ForEach-Object {
                $entry = [string]$_
                while ($entry.StartsWith("./")) { $entry = $entry.Substring(2) }
                $entry.TrimEnd("/")
            }
    )
}

function Test-TarForbiddenEntries {
    param([AllowEmptyCollection()][string[]]$Entries = @())
    $matches = New-Object System.Collections.Generic.List[object]
    foreach ($entry in @($Entries | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })) {
        $segments = @($entry -split "/")
        $baseName = if ($segments.Count -gt 0) { [string]$segments[-1] } else { [string]$entry }
        foreach ($segment in $segments) {
            if ($segment -in @(".git", "__pycache__", "support_bundle", "release_artifacts", "ProgramData", "AppData", "desktop_e2e", "pytest")) {
                $matches.Add([ordered]@{ path = $entry; pattern = $segment }) | Out-Null
            }
        }
        $isOsPackagePath = (
            $entry.StartsWith("usr/lib/", [System.StringComparison]::OrdinalIgnoreCase) -or
            $entry.StartsWith("usr/share/", [System.StringComparison]::OrdinalIgnoreCase)
        )
        if (
            -not $isOsPackagePath -and (
                $baseName -eq ".env" -or
                $baseName.StartsWith(".env.", [System.StringComparison]::OrdinalIgnoreCase) -or
                $baseName -in @("id_rsa", "id_dsa", "id_ecdsa", "id_ed25519", "openbao.token", "docker.token", "secret", "secrets", "token", "tokens", "private_key", "private-key") -or
                $baseName.EndsWith(".private-key", [System.StringComparison]::OrdinalIgnoreCase) -or
                $baseName.EndsWith(".private_key", [System.StringComparison]::OrdinalIgnoreCase)
            )
        ) {
            $matches.Add([ordered]@{ path = $entry; pattern = "obvious_secret_filename" }) | Out-Null
        }
    }
    return @($matches.ToArray())
}

$paths = Ensure-ImmoAppRuntimeLayout
$canonicalPaths = Get-ImmoAppCanonicalRuntimePaths
if ([string]::IsNullOrWhiteSpace($OutputRootfsTarPath)) {
    $OutputRootfsTarPath = Join-Path $paths.RuntimeRoot "rootfs\ImmoAppRuntime.rootfs.tar"
}
if ([string]::IsNullOrWhiteSpace($OutputJson)) {
    $OutputJson = Join-Path $paths.ConfigRoot "managed_wsl2_official_rootfs_build.json"
}

$runtimeRoots = @($canonicalPaths.RuntimeRoot)
$outputRoots = @($canonicalPaths.ConfigRoot, $canonicalPaths.RuntimeRoot, $canonicalPaths.LogsRoot)
if ((Get-ImmoAppRuntimeRootSource) -eq "test_programdata_root") {
    $runtimeRoots += @($paths.RuntimeRoot)
    $outputRoots += @($paths.ConfigRoot, $paths.RuntimeRoot, $paths.LogsRoot)
}
$runtimeRoots = @($runtimeRoots | Select-Object -Unique)
$outputRoots = @($outputRoots | Select-Object -Unique)
$sourcesRoot = Join-Path $paths.RuntimeRoot "rootfs\sources"
$createdAt = (Get-Date).ToUniversalTime().ToString("o")
$sourceCommitSha = ""
try {
    $sourceCommitSha = (& git -C (Get-ImmoAppRepoRoot).Path rev-parse HEAD 2>$null | Out-String).Trim().ToLowerInvariant()
}
catch {
    $sourceCommitSha = ""
}

$wslPath = Get-ApprovedWslPath
$baseRootfsUrlEffective = $BaseRootfsUrl
$baseRootfsPath = ""
$baseRootfsSha = ""
$expectedSha = $ExpectedBaseRootfsSha256.Trim().ToLowerInvariant()
$baseRootfsProvenanceStatus = "NO-GO"
$baseImportTarPath = ""
$baseImportTarSha = ""
$buildDistroImportStatus = "NO-GO"
$dockerEngineStatus = "NO-GO"
$dockerEngineVersion = ""
$composeStatus = "NO-GO"
$composeVersion = ""
$logPolicyStatus = "NO-GO"
$requiredCommandStatus = "NO-GO"
$cleanupStatus = "NO-GO"
$outputRootfsSha = ""
$importPlanStatus = "NO-GO"
$importPlanEvidencePath = ""
$importPlanEvidenceSha = ""
$runtimeStartStatus = "NO-GO"
$agencyInstallStatus = "NO_GO"
$publicBetaStatus = "NO_GO"
$proofResult = "NO-GO"
$reasonCode = "official_rootfs_build_failed"
$reason = ""
$buildDistroCleanupStatus = "not_attempted"
$buildDistroCleanupAttempted = $false
$buildDistroPresentAfterCleanup = $false
$buildDistroCleanupReason = ""
$existingDistroPresent = $false
$mutationPerformed = $false
$downloaded = $false
$finalTarMissingEntries = @()
$forbiddenMatches = @()
$identity = @{}

try {
    if ($BuildDistroName -ne "ImmoAppRuntimeBuild") {
        throw "official_rootfs_build_distro_name_not_approved|BuildDistroName must be ImmoAppRuntimeBuild."
    }
    if (-not (Test-Path -LiteralPath $wslPath -PathType Leaf)) {
        throw "official_rootfs_wsl_missing|Windows WSL executable was not found."
    }
    if (Test-ImmoAppPathHasReparsePoint -Path $wslPath) {
        throw "official_rootfs_wsl_reparse_point|The approved WSL executable path is a reparse point."
    }

    Assert-ImmoAppProofOnlyPathApproved -Path $OutputRootfsTarPath -Roots $runtimeRoots -Label "OutputRootfsTarPath"
    Assert-ImmoAppProofOnlyPathApproved -Path $sourcesRoot -Roots $runtimeRoots -Label "SourcesRoot"
    if (Test-PathParentHasReparsePoint -Path $OutputRootfsTarPath) {
        throw "official_rootfs_output_reparse_point|OutputRootfsTarPath parent contains a reparse point."
    }
    if (Test-PathParentHasReparsePoint -Path $sourcesRoot) {
        throw "official_rootfs_sources_reparse_point|SourcesRoot parent contains a reparse point."
    }
    [System.IO.Directory]::CreateDirectory($sourcesRoot) | Out-Null
    [System.IO.Directory]::CreateDirectory((Split-Path -Parent $OutputRootfsTarPath)) | Out-Null

    if ([string]::IsNullOrWhiteSpace($SourceRootfsTarPath)) {
        if ([string]::IsNullOrWhiteSpace($baseRootfsUrlEffective)) {
            $shaUrl = $officialReleaseBase + $officialShaFile
            $shaResponse = Invoke-WebRequest -Uri $shaUrl -UseBasicParsing
            $shaText = if ($shaResponse.Content -is [byte[]]) {
                [System.Text.Encoding]::UTF8.GetString([byte[]]$shaResponse.Content)
            } else {
                [string]$shaResponse.Content
            }
            $matchingLines = @($shaText -split "(`r`n|`n|`r)" | Where-Object { $_ -match [regex]::Escape($officialRootfsFile) })
            if ($matchingLines.Count -lt 1 -or [string]::IsNullOrWhiteSpace([string]$matchingLines[0])) {
                throw "official_rootfs_metadata_missing|Official SHA256SUMS did not list the Ubuntu 24.04 amd64 minimal rootfs."
            }
            $line = [string]$matchingLines[0]
            $metadataSha = ([string]$line).Trim().Split(" ", [System.StringSplitOptions]::RemoveEmptyEntries)[0].ToLowerInvariant()
            if ([string]::IsNullOrWhiteSpace($expectedSha)) {
                $expectedSha = $metadataSha
            }
            $baseRootfsUrlEffective = $officialReleaseBase + $officialRootfsFile
        }
        if (-not (Test-OfficialUbuntuRootfsUrl -Url $baseRootfsUrlEffective)) {
            throw "official_rootfs_url_not_approved|BaseRootfsUrl must be the official Ubuntu 24.04 LTS minimal amd64 rootfs URL on cloud-images.ubuntu.com."
        }
        $fileName = [System.IO.Path]::GetFileName(([System.Uri]$baseRootfsUrlEffective).AbsolutePath)
        $baseRootfsPath = Join-Path $sourcesRoot $fileName
        Invoke-WebRequest -Uri $baseRootfsUrlEffective -OutFile $baseRootfsPath -UseBasicParsing
        $downloaded = $true
    }
    else {
        $baseRootfsPath = [System.IO.Path]::GetFullPath($SourceRootfsTarPath)
        if (-not (Test-Path -LiteralPath $baseRootfsPath -PathType Leaf)) {
            throw "official_rootfs_source_missing|SourceRootfsTarPath must exist as a local file."
        }
        if (Test-ImmoAppPathHasReparsePoint -Path $baseRootfsPath) {
            throw "official_rootfs_source_reparse_point|SourceRootfsTarPath is a reparse point."
        }
        if (-not (Test-ImmoAppPathUnderRoot -Root $sourcesRoot -Path $baseRootfsPath)) {
            throw "official_rootfs_source_not_under_sources_root|SourceRootfsTarPath must be under C:\ProgramData\ImmoApp\runtime\rootfs\sources."
        }
        if (-not [string]::IsNullOrWhiteSpace($baseRootfsUrlEffective) -and -not (Test-OfficialUbuntuRootfsUrl -Url $baseRootfsUrlEffective)) {
            throw "official_rootfs_url_not_approved|BaseRootfsUrl must be the official Ubuntu 24.04 LTS minimal amd64 rootfs URL on cloud-images.ubuntu.com."
        }
    }

    $baseRootfsSha = Get-ImmoAppFileSha256 -Path $baseRootfsPath
    if (-not [string]::IsNullOrWhiteSpace($expectedSha)) {
        if ($expectedSha -notmatch "^[a-f0-9]{64}$") {
            throw "official_rootfs_expected_sha_invalid|ExpectedBaseRootfsSha256 must be lowercase SHA-256."
        }
        if ($baseRootfsSha -ne $expectedSha) {
            throw "official_rootfs_sha256_mismatch|Downloaded/source rootfs SHA-256 does not match ExpectedBaseRootfsSha256."
        }
        $baseRootfsProvenanceStatus = "official_sha256_verified"
    }
    else {
        $baseRootfsProvenanceStatus = "official_source_internal_proof_only"
    }

    if ($baseRootfsPath.EndsWith(".xz", [System.StringComparison]::OrdinalIgnoreCase)) {
        $baseImportTarPath = Join-Path $sourcesRoot ([System.IO.Path]::GetFileNameWithoutExtension($baseRootfsPath))
        Expand-XzToTar -XzPath $baseRootfsPath -TarPath $baseImportTarPath
    }
    else {
        $baseImportTarPath = $baseRootfsPath
    }
    $baseImportTarSha = Get-ImmoAppFileSha256 -Path $baseImportTarPath

    if (-not $ConfirmBuild.IsPresent) {
        throw "official_rootfs_confirm_build_required|ConfirmBuild is required before importing or mutating the temporary WSL build distro."
    }

    $existingDistros = @(Get-ExistingWslDistros -WslPath $wslPath)
    $existingDistroPresent = ($existingDistros -contains $BuildDistroName)
    if ($existingDistroPresent -and -not $ConfirmReplaceBuildDistro.IsPresent) {
        throw "official_rootfs_build_distro_exists_replace_not_confirmed|ImmoAppRuntimeBuild already exists; replacement requires ConfirmReplaceBuildDistro."
    }
    if ($existingDistroPresent) {
        Invoke-WslChecked -WslPath $wslPath -Arguments @("--unregister", $BuildDistroName) -ReasonCode "official_rootfs_build_distro_unregister_failed" | Out-Null
        $mutationPerformed = $true
    }

    $buildInstallLocation = Join-Path $paths.RuntimeRoot "wsl-build\ImmoAppRuntimeBuild"
    Assert-ImmoAppProofOnlyPathApproved -Path $buildInstallLocation -Roots $runtimeRoots -Label "BuildInstallLocation"
    if (-not (Test-Path -LiteralPath $buildInstallLocation)) {
        [System.IO.Directory]::CreateDirectory($buildInstallLocation) | Out-Null
    }
    Invoke-WslChecked -WslPath $wslPath -Arguments @("--import", $BuildDistroName, $buildInstallLocation, $baseImportTarPath, "--version", "2") -ReasonCode "official_rootfs_build_distro_import_failed" | Out-Null
    $mutationPerformed = $true
    $buildDistroImportStatus = "GO"

    Write-BuildDistroFile -WslPath $wslPath -DistroName $BuildDistroName -Path "/etc/wsl.conf" -Mode "0644" -Content @'
[boot]
systemd=true
[interop]
enabled=false
appendWindowsPath=false
'@
    Invoke-WslChecked -WslPath $wslPath -Arguments @("--terminate", $BuildDistroName) -ReasonCode "official_rootfs_build_distro_terminate_failed" | Out-Null

    Write-BuildDistroFile -WslPath $wslPath -DistroName $BuildDistroName -Path "/tmp/immoapp-official-rootfs-install.sh" -Mode "0755" -Content @'
#!/bin/sh
set -eu
export DEBIAN_FRONTEND=noninteractive
install -d -m 1777 /tmp /var/tmp
printf '%s\n' 'Acquire::ForceIPv4 "true";' 'Acquire::Retries "3";' 'Acquire::http::Timeout "30";' > /etc/apt/apt.conf.d/99-immoapp-build-network
apt_update() {
  attempt=1
  while [ "$attempt" -le 4 ]; do
    if apt-get -o Acquire::ForceIPv4=true -o Acquire::Retries=3 -o Acquire::http::Timeout=30 update; then
      return 0
    fi
    attempt=$((attempt + 1))
    sleep 5
  done
  return 1
}
apt_install() {
  attempt=1
  while [ "$attempt" -le 4 ]; do
    if apt-get -o Acquire::ForceIPv4=true -o Acquire::Retries=3 -o Acquire::http::Timeout=30 install -y --fix-missing "$@"; then
      return 0
    fi
    apt-get -o Acquire::ForceIPv4=true -o Acquire::Retries=3 -o Acquire::http::Timeout=30 -f install -y --fix-missing || true
    apt_update || true
    attempt=$((attempt + 1))
    sleep 5
  done
  return 1
}
rm -rf /var/lib/apt/lists/*
apt_update
apt_install ca-certificates curl gnupg
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
grep -Eq '^(VERSION_CODENAME|UBUNTU_CODENAME)=noble$' /etc/os-release
printf '%s\n' "deb [arch=amd64 signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu noble stable" > /etc/apt/sources.list.d/docker.list
rm -rf /var/lib/apt/lists/*
apt_update
apt_install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
install -d -m 0755 /etc/systemd/system/docker.service.d
cat > /etc/systemd/system/docker.service.d/immoapp-no-network-online.conf <<'EOF'
[Unit]
After=
After=containerd.service docker.socket time-set.target
Wants=
Wants=containerd.service
EOF
systemctl mask systemd-networkd-wait-online.service >/dev/null 2>&1 || true
systemctl daemon-reload >/dev/null 2>&1 || true
systemctl enable docker >/dev/null 2>&1 || true
systemctl start docker --no-block >/dev/null 2>&1 || true
install -d -m 0755 /etc/docker
cat > /etc/docker/daemon.json <<'EOF'
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "10m",
    "max-file": "5"
  }
}
EOF
'@ | Out-Null
    Invoke-BuildDistroShell -WslPath $wslPath -DistroName $BuildDistroName -ReasonCode "official_rootfs_apt_prerequisites_failed" -Command "/tmp/immoapp-official-rootfs-install.sh" | Out-Null

    Invoke-BuildDistroShell -WslPath $wslPath -DistroName $BuildDistroName -ReasonCode "official_rootfs_runtime_dirs_failed" -Command "install -d -m 0755 /opt/immoapp/runtime/bin /opt/immoapp/runtime/compose /opt/immoapp/runtime/logs /opt/immoapp/runtime/proxy" | Out-Null

    $templateRoot = Join-Path (Get-ImmoAppRepoRoot).Path "deployment\managed-runtime"
    if (-not (Test-Path -LiteralPath $templateRoot -PathType Container)) {
        throw "official_rootfs_runtime_template_missing|Managed runtime template root is missing."
    }
    $templateRootFull = [System.IO.Path]::GetFullPath($templateRoot).TrimEnd("\", "/")
    $templateFiles = @(Get-ChildItem -LiteralPath $templateRootFull -File -Recurse)
    foreach ($templateFile in $templateFiles) {
        $templateFileFull = [System.IO.Path]::GetFullPath($templateFile.FullName)
        if (-not $templateFileFull.StartsWith($templateRootFull + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "official_rootfs_runtime_template_unsafe_entry|Managed runtime template file escaped the template root."
        }
        $relative = $templateFileFull.Substring($templateRootFull.Length + 1).Replace("\", "/")
        if ($relative.StartsWith("../") -or $relative.Contains("/../") -or $relative.StartsWith("/")) {
            throw "official_rootfs_runtime_template_unsafe_entry|Managed runtime template contains an unsafe relative path."
        }
        $targetPath = "/opt/immoapp/runtime/$relative"
        $content = [System.IO.File]::ReadAllText($templateFileFull, [System.Text.UTF8Encoding]::new($false))
        $content = $content.Replace("__IMMOAPP_RUNTIME_VERSION__", $RuntimeVersion)
        $content = $content.Replace("__IMMOAPP_SOURCE_COMMIT_SHA__", $sourceCommitSha)
        $mode = if ($relative.StartsWith("bin/", [System.StringComparison]::OrdinalIgnoreCase)) { "0755" } else { "0644" }
        Write-BuildDistroFile -WslPath $wslPath -DistroName $BuildDistroName -Path $targetPath -Mode $mode -Content $content
    }

    $identityText = (Invoke-BuildDistroShell -WslPath $wslPath -DistroName $BuildDistroName -ReasonCode "official_rootfs_identity_failed" -Command "/opt/immoapp/runtime/bin/immoapp-runtime-identity --json" | Out-String).Trim()
    $identity = $identityText | ConvertFrom-Json
    $dockerEngineStatus = [string]$identity.container_engine_status
    $dockerEngineVersion = [string]$identity.container_engine_version
    $composeStatus = [string]$identity.compose_status
    $composeVersion = [string]$identity.compose_version
    if (
        [string]$identity.kind -ne "immoapp_managed_wsl2_runtime_identity" -or
        [int]$identity.schema_version -ne 1 -or
        [string]$identity.runtime_identity -ne "ImmoAppRuntime" -or
        [string]$identity.runtime_root -ne "/opt/immoapp/runtime" -or
        [string]$identity.agency_install_status -ne "NO_GO"
    ) {
        throw "official_rootfs_identity_contract_failed|Runtime identity JSON did not match the ImmoAppRuntime contract."
    }
    if ($dockerEngineStatus -ne "GO") { throw "official_rootfs_docker_engine_missing|Docker Engine did not validate inside ImmoAppRuntimeBuild." }
    if ($composeStatus -ne "GO") { throw "official_rootfs_compose_missing|Docker Compose plugin did not validate inside ImmoAppRuntimeBuild." }
$logPolicyCommand = @'
test -f /etc/docker/daemon.json &&
grep -q '"max-size"' /etc/docker/daemon.json &&
grep -q '"10m"' /etc/docker/daemon.json &&
grep -q '"max-file"' /etc/docker/daemon.json &&
grep -q '"5"' /etc/docker/daemon.json &&
test -L /etc/systemd/system/systemd-networkd-wait-online.service &&
test "$(readlink /etc/systemd/system/systemd-networkd-wait-online.service)" = "/dev/null" &&
test -f /etc/systemd/system/docker.service.d/immoapp-no-network-online.conf &&
grep -q '^After=containerd.service docker.socket time-set.target$' /etc/systemd/system/docker.service.d/immoapp-no-network-online.conf
'@.Trim()
    Invoke-BuildDistroShell `
        -WslPath $wslPath `
        -DistroName $BuildDistroName `
        -ReasonCode "official_rootfs_log_policy_missing" `
        -Command $logPolicyCommand | Out-Null
    $logPolicyStatus = "GO"

    foreach ($commandPath in @($requiredRuntimeCommands | ForEach-Object { "/" + $_ })) {
        Invoke-BuildDistroShell -WslPath $wslPath -DistroName $BuildDistroName -ReasonCode "official_rootfs_required_command_missing" -Command "test -x $(Quote-Sh -Value $commandPath)" | Out-Null
    }
    $requiredCommandStatus = "GO"

    Invoke-BuildDistroShell -WslPath $wslPath -DistroName $BuildDistroName -ReasonCode "official_rootfs_cleanup_failed" -Command "rm -rf /var/cache/apt/* /var/lib/apt/lists/* /tmp/* /var/tmp/* /root/.bash_history /home/*/.bash_history 2>/dev/null || true; find / -xdev \\( -path /proc -o -path /sys -o -path /dev -o -path /run -o -path /mnt \\) -prune -o -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true" | Out-Null
    $cleanupStatus = "GO"

    Invoke-WslChecked -WslPath $wslPath -Arguments @("--shutdown") -ReasonCode "official_rootfs_wsl_shutdown_failed" | Out-Null
    if (Test-Path -LiteralPath $OutputRootfsTarPath -PathType Leaf) {
        Remove-Item -LiteralPath $OutputRootfsTarPath -Force
    }
    Invoke-WslChecked -WslPath $wslPath -Arguments @("--export", $BuildDistroName, $OutputRootfsTarPath) -ReasonCode "official_rootfs_export_failed" | Out-Null
    $outputRootfsSha = Get-ImmoAppFileSha256 -Path $OutputRootfsTarPath
    if ($KeepBuildDistro.IsPresent) {
        $buildDistroCleanupStatus = "kept"
        $buildDistroCleanupAttempted = $false
        $buildDistroPresentAfterCleanup = (@(Get-ExistingWslDistros -WslPath $wslPath) -contains $BuildDistroName)
    }
    else {
        $buildDistroCleanupAttempted = $true
        try {
            Invoke-WslChecked -WslPath $wslPath -Arguments @("--unregister", $BuildDistroName) -ReasonCode "official_rootfs_build_distro_cleanup_unregister_failed" | Out-Null
            $mutationPerformed = $true
        }
        catch {
            $buildDistroCleanupReason = [string]$_.Exception.Message
        }
        try {
            $buildDistroPresentAfterCleanup = (@(Get-ExistingWslDistros -WslPath $wslPath) -contains $BuildDistroName)
        }
        catch {
            $buildDistroPresentAfterCleanup = $true
            if ([string]::IsNullOrWhiteSpace($buildDistroCleanupReason)) {
                $buildDistroCleanupReason = [string]$_.Exception.Message
            }
        }
        if ($buildDistroPresentAfterCleanup -or -not [string]::IsNullOrWhiteSpace($buildDistroCleanupReason)) {
            $buildDistroCleanupStatus = "NO-GO"
            if ([string]::IsNullOrWhiteSpace($buildDistroCleanupReason)) {
                $buildDistroCleanupReason = "official_rootfs_build_distro_cleanup_incomplete|ImmoAppRuntimeBuild remained present after cleanup."
            }
        }
        else {
            $buildDistroCleanupStatus = "GO"
        }
    }
    $entries = @(Get-TarEntries -Path $OutputRootfsTarPath)
    $finalTarMissingEntries = @($requiredRuntimeEntries | Where-Object { $entries -notcontains $_ })
    if ($finalTarMissingEntries.Count -gt 0) {
        throw "official_rootfs_final_tar_required_command_missing|Final rootfs tar is missing required runtime commands."
    }
    $forbiddenMatches = @(Test-TarForbiddenEntries -Entries $entries)
    if ($forbiddenMatches.Count -gt 0) {
        throw "official_rootfs_final_tar_forbidden_entries|Final rootfs tar contains forbidden local/dev/proof content."
    }

    $importPlanOutput = & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "import_managed_wsl2_runtime_distro.ps1") -RootfsTarPath $OutputRootfsTarPath -PlanOnly -ConfirmReplaceExistingDistro 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "official_rootfs_import_plan_failed|$($importPlanOutput -join "`n")"
    }
    $importPlan = ($importPlanOutput | Out-String) | ConvertFrom-Json
    $importPlanStatus = [string]$importPlan.proof_result
    $importPlanEvidencePath = ""
    if ($importPlan.PSObject.Properties.Name -contains "evidence_path") {
        $importPlanEvidencePath = [string]$importPlan.evidence_path
    }
    if ([string]::IsNullOrWhiteSpace($importPlanEvidencePath)) {
        $importPlanEvidencePath = Join-Path $canonicalPaths.LogsRoot "managed_wsl2_runtime_import_plan.json"
    }
    if (Test-Path -LiteralPath $importPlanEvidencePath -PathType Leaf) {
        $importPlanEvidenceSha = Get-ImmoAppFileSha256 -Path $importPlanEvidencePath
    }
    if ($importPlanStatus -ne "GO") {
        throw "official_rootfs_import_plan_failed|Plan-only import did not return GO."
    }

    if ($buildDistroCleanupStatus -eq "NO-GO") {
        $proofResult = "NO-GO"
        $reasonCode = "official_rootfs_build_distro_cleanup_failed_after_export"
        $reason = $buildDistroCleanupReason
    }
    else {
        $proofResult = "GO"
        $reasonCode = "official_managed_wsl2_rootfs_build_go"
    }
}
catch {
    $reason = [string]$_.Exception.Message
    if ($reason.Contains("|")) {
        $reasonCode = $reason.Split("|", 2)[0]
    }
    elseif ([string]::IsNullOrWhiteSpace($reasonCode)) {
        $reasonCode = "official_rootfs_build_failed"
    }
    $proofResult = "NO-GO"
}

$payload = [ordered]@{
    kind = "immoapp_managed_wsl2_official_rootfs_build"
    schema_version = 1
    created_at_utc = $createdAt
    source_commit_sha = $sourceCommitSha
    base_rootfs_url = $baseRootfsUrlEffective
    base_rootfs_path = $baseRootfsPath
    base_rootfs_sha256 = $baseRootfsSha
    expected_base_rootfs_sha256 = $expectedSha
    base_rootfs_provenance_status = $baseRootfsProvenanceStatus
    base_import_tar_path = $baseImportTarPath
    base_import_tar_sha256 = $baseImportTarSha
    base_rootfs_downloaded = $downloaded
    build_distro_name = $BuildDistroName
    build_distro_import_status = $buildDistroImportStatus
    build_distro_replaced = ($existingDistroPresent -and $ConfirmReplaceBuildDistro.IsPresent)
    build_distro_cleanup_status = $buildDistroCleanupStatus
    build_distro_cleanup_attempted = $buildDistroCleanupAttempted
    build_distro_present_after_cleanup = $buildDistroPresentAfterCleanup
    build_distro_cleanup_reason = $buildDistroCleanupReason
    mutation_performed = $mutationPerformed
    docker_engine_status = $dockerEngineStatus
    docker_engine_version = $dockerEngineVersion
    compose_status = $composeStatus
    compose_version = $composeVersion
    log_policy_status = $logPolicyStatus
    required_command_status = $requiredCommandStatus
    cleanup_status = $cleanupStatus
    output_rootfs_tar_path = [System.IO.Path]::GetFullPath($OutputRootfsTarPath)
    output_rootfs_tar_sha256 = $outputRootfsSha
    final_tar_missing_entries = @($finalTarMissingEntries)
    final_tar_forbidden_matches = @($forbiddenMatches)
    import_plan_status = $importPlanStatus
    import_plan_evidence_path = $importPlanEvidencePath
    import_plan_evidence_sha256 = $importPlanEvidenceSha
    runtime_start_status = $runtimeStartStatus
    agency_install_status = $agencyInstallStatus
    public_beta_status = $publicBetaStatus
    proof_result = $proofResult
    reason_code = $reasonCode
    reason = $reason
}

$rootfsInventoryPath = Join-Path $paths.ConfigRoot "managed_wsl2_runtime_rootfs_inventory.json"
$rootfsInventory = [ordered]@{
    kind = "immoapp_managed_wsl2_runtime_rootfs_inventory"
    schema_version = 1
    created_at_utc = $createdAt
    source_commit_sha = $sourceCommitSha
    base_rootfs_tar_path = $baseRootfsPath
    base_rootfs_tar_sha256 = $baseRootfsSha
    output_rootfs_tar_path = [System.IO.Path]::GetFullPath($OutputRootfsTarPath)
    output_rootfs_tar_sha256 = $outputRootfsSha
    runtime_version = $RuntimeVersion
    expected_distro_name = "ImmoAppRuntime"
    required_entries = @($requiredRuntimeEntries)
    rootfs_artifact_status = if ($proofResult -eq "GO") { "GO" } else { "NO-GO" }
    runtime_identity_status = "NO-GO"
    runtime_start_status = "NO-GO"
    agency_install_status = $agencyInstallStatus
    public_beta_status = $publicBetaStatus
    proof_result = $proofResult
    reason_code = if ($proofResult -eq "GO") { "official_managed_wsl2_rootfs_inventory_go" } else { $reasonCode }
    reason = $reason
    recommended_next_action = if ($proofResult -eq "GO") {
        "Run import_managed_wsl2_runtime_distro.ps1 -PlanOnly against this rootfs, then import with explicit confirmation only when ready."
    } else {
        "Fix the official rootfs build failure before packaging a Hub-capable installer."
    }
}
$rootfsInventoryWrite = Write-ImmoAppSafeJson -Path $rootfsInventoryPath -Payload $rootfsInventory -ApprovedRoots $outputRoots
$rootfsInventory["inventory_path"] = $rootfsInventoryWrite.path
$rootfsInventory["inventory_sha256"] = $rootfsInventoryWrite.sha256
$rootfsInventoryFinalWrite = Write-ImmoAppSafeJson -Path $rootfsInventoryPath -Payload $rootfsInventory -ApprovedRoots $outputRoots
$rootfsInventory["inventory_sha256"] = $rootfsInventoryFinalWrite.sha256
$payload["rootfs_inventory_path"] = $rootfsInventoryFinalWrite.path
$payload["rootfs_inventory_sha256"] = $rootfsInventoryFinalWrite.sha256

$write = Write-ImmoAppSafeJson -Path $OutputJson -Payload $payload -ApprovedRoots $outputRoots -Depth 12
$payload["evidence_path"] = $write.path
$payload["evidence_sha256"] = $write.sha256
$payload | ConvertTo-Json -Depth 12
if ($proofResult -ne "GO") {
    [Console]::Error.WriteLine("$($payload.reason_code)|$($payload.reason)")
    exit 1
}
exit 0
