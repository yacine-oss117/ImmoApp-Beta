param(
    [string]$OutputDir = ""
)

$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "common.ps1")

function ConvertTo-ImmoAppSupportRedactedText {
    param([AllowNull()][object]$Value)
    $text = [string]$Value
    $text = [regex]::Replace($text, "(?im)^(\s*Authorization\s*:\s*)(Basic|Token|Bearer)\s+[^\r\n]+", '$1$2 [REDACTED]')
    $text = [regex]::Replace($text, "(?i)Bearer\s+[A-Za-z0-9._~+/=-]+", "Bearer [REDACTED]")
    $text = [regex]::Replace($text, "(?i)([?&]X-Amz-[^=]+)=([^&\s]+)", '$1=[REDACTED]')
    $text = [regex]::Replace($text, "(?i)([?&](?:api[_-]?key|apiKey|xApiKey|token|access[_-]?token|accessToken|refresh[_-]?token|refreshToken|id[_-]?token|idToken|session[_-]?token|sessionToken|client[_-]?secret|clientSecret|signature)=)([^&\s]+)", '$1[REDACTED]')
    $secretValueNamePattern = "password|passwd|secret|token|nonce|access_token|accessToken|refresh_token|refreshToken|id_token|idToken|session_token|sessionToken|client_secret|clientSecret|apiKey|api_key|xApiKey|privateKey|private_key|key_material|credential|certificate|cert|signature|x-api-key|api-key|token[_-]?(?:file|path)|secret[_-]?(?:file|path|id)|password[_-]?(?:file|path)|credential[_-]?(?:file|path)|private[_-]?key[_-]?(?:file|path)"
    $text = [regex]::Replace($text, "(?i)\b($secretValueNamePattern)\s*=\s*([^\s&;]+)", '$1=[REDACTED]')
    $text = [regex]::Replace($text, "(?i)\b($secretValueNamePattern)\s*:\s*([^\s&;]+)", '$1: [REDACTED]')
    $text = [regex]::Replace($text, "(?i)\b(WITH\s+PASSWORD\s+)'[^']*'", '$1''[REDACTED]''')
    $text = [regex]::Replace($text, "(?i)\b(password\s+)'[^']*'", '$1''[REDACTED]''')
    $text = [regex]::Replace($text, "-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----.*?-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", "[REDACTED PRIVATE KEY]", [System.Text.RegularExpressions.RegexOptions]::Singleline)
    $text = [regex]::Replace($text, "-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----", "[REDACTED CERTIFICATE]", [System.Text.RegularExpressions.RegexOptions]::Singleline)
    return $text
}

function ConvertTo-ImmoAppSupportSanitizedObject {
    param([AllowNull()][object]$Value)
    $secretKeyPattern = "(authorization|password|passwd|secret|token|nonce|refresh|access|access_token|accessToken|refresh_token|refreshToken|idToken|id_token|sessionToken|session_token|client_secret|clientSecret|credential|presigned|signature|api[_-]?key|apiKey|xApiKey|private[_-]?key|privateKey|certificate|cert|key_material|x-api-key|token[_-]?(?:file|path)|secret[_-]?(?:file|path|id)|password[_-]?(?:file|path)|credential[_-]?(?:file|path)|private[_-]?key[_-]?(?:file|path)|\.env)"
    if ($null -eq $Value) { return $null }
    if ($Value -is [System.Collections.IDictionary]) {
        $result = [ordered]@{}
        foreach ($key in $Value.Keys) {
            $name = [string]$key
            if ($name -match $secretKeyPattern) {
                $result[$name] = "[REDACTED]"
            }
            else {
                $result[$name] = ConvertTo-ImmoAppSupportSanitizedObject -Value $Value[$key]
            }
        }
        return $result
    }
    if ($Value -is [pscustomobject]) {
        $result = [ordered]@{}
        foreach ($property in $Value.PSObject.Properties) {
            $name = [string]$property.Name
            if ($name -match $secretKeyPattern) {
                $result[$name] = "[REDACTED]"
            }
            else {
                $result[$name] = ConvertTo-ImmoAppSupportSanitizedObject -Value $property.Value
            }
        }
        return $result
    }
    if ($Value -is [System.Collections.IEnumerable] -and $Value -isnot [string]) {
        $items = @()
        foreach ($item in $Value) {
            $items += ,(ConvertTo-ImmoAppSupportSanitizedObject -Value $item)
        }
        return $items
    }
    return (ConvertTo-ImmoAppSupportRedactedText -Value $Value)
}

function Read-ImmoAppSupportJsonSummary {
    param(
        [Parameter(Mandatory = $true)][string]$Path
    )
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return [ordered]@{ exists = $false; path = $Path }
    }
    try {
        $raw = Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
        return [ordered]@{ exists = $true; path = $Path; data = (ConvertTo-ImmoAppSupportSanitizedObject -Value $raw) }
    }
    catch {
        return [ordered]@{ exists = $true; path = $Path; read_error = $_.Exception.GetType().Name }
    }
}

function Read-ImmoAppSupportOwnerAuthorizationSummary {
    param([Parameter(Mandatory = $true)][string]$Path)

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return [ordered]@{ exists = $false; path = $Path }
    }
    try {
        $raw = Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
    }
    catch {
        return [ordered]@{ exists = $true; path = $Path; read_error = $_.Exception.GetType().Name }
    }
    $allowed = [ordered]@{
        kind = Get-ImmoAppObjectValue -Data $raw -Name "kind"
        schema_version = Get-ImmoAppObjectValue -Data $raw -Name "schema_version"
        created_at_utc = Get-ImmoAppObjectValue -Data $raw -Name "created_at_utc"
        expires_at_utc = Get-ImmoAppObjectValue -Data $raw -Name "expires_at_utc"
        proof_result = Get-ImmoAppObjectValue -Data $raw -Name "proof_result"
        owner_authorization_status = Get-ImmoAppObjectValue -Data $raw -Name "owner_authorization_status"
        reason_code = Get-ImmoAppObjectValue -Data $raw -Name "reason_code"
        action = Get-ImmoAppObjectValue -Data $raw -Name "action"
        authorization_scope = Get-ImmoAppObjectValue -Data $raw -Name "authorization_scope"
        source = Get-ImmoAppObjectValue -Data $raw -Name "source"
        authorized_role = Get-ImmoAppObjectValue -Data $raw -Name "authorized_role"
        actor_role = Get-ImmoAppObjectValue -Data $raw -Name "actor_role"
        actor_is_owner = Get-ImmoAppObjectValue -Data $raw -Name "actor_is_owner"
        actor_can_hard_delete = Get-ImmoAppObjectValue -Data $raw -Name "actor_can_hard_delete"
        actor_is_superuser = Get-ImmoAppObjectValue -Data $raw -Name "actor_is_superuser"
        hub_id = Get-ImmoAppObjectValue -Data $raw -Name "hub_id"
        hub_state_install_lineage = Get-ImmoAppObjectValue -Data $raw -Name "hub_state_install_lineage"
        plaintext_password_written = Get-ImmoAppObjectValue -Data $raw -Name "plaintext_password_written"
        session_token_written = Get-ImmoAppObjectValue -Data $raw -Name "session_token_written"
    }
    $sanitized = [ordered]@{}
    foreach ($key in $allowed.Keys) {
        $sanitized[$key] = ConvertTo-ImmoAppSupportRedactedText -Value $allowed[$key]
    }
    return [ordered]@{
        exists = $true
        path = $Path
        data = $sanitized
    }
}

function Add-ImmoAppSupportZipText {
    param(
        [Parameter(Mandatory = $true)][System.IO.Compression.ZipArchive]$Zip,
        [Parameter(Mandatory = $true)][string]$EntryName,
        [Parameter(Mandatory = $true)][AllowEmptyString()][string]$Text
    )
    $entry = $Zip.CreateEntry($EntryName, [System.IO.Compression.CompressionLevel]::Optimal)
    $stream = $entry.Open()
    try {
        $writer = [System.IO.StreamWriter]::new($stream, [System.Text.UTF8Encoding]::new($false))
        try { $writer.Write($Text) }
        finally { $writer.Dispose() }
    }
    finally {
        $stream.Dispose()
    }
}

function New-ImmoAppInstalledSupportBundle {
    param([string]$OutputDir = "")

    Add-Type -AssemblyName System.IO.Compression | Out-Null
    Add-Type -AssemblyName System.IO.Compression.FileSystem | Out-Null

    $runtimePaths = Get-ImmoAppRuntimePaths
    $targetDir = if ($OutputDir) { $OutputDir } else { Join-Path $runtimePaths.TmpRoot "support_bundles" }
    New-Item -ItemType Directory -Path $targetDir -Force | Out-Null

    $stamp = (Get-Date).ToUniversalTime().ToString("yyyyMMdd_HHmmss")
    $bundlePath = Join-Path $targetDir "immoapp_support_$stamp.zip"
    $summaryPath = Join-Path $targetDir "immoapp_support_$stamp.json"
    if (Test-Path -LiteralPath $bundlePath) { Remove-Item -LiteralPath $bundlePath -Force }

    $configRoot = $runtimePaths.ConfigRoot
    $logsRoot = $runtimePaths.LogsRoot
    $evidenceNames = @(
        "hub_install_evidence.json",
        "hub_status_evidence.json",
        "hub_runtime_detection.json",
        "managed_wsl2_runtime_start_evidence.json",
        "managed_wsl2_runtime_status_evidence.json",
        "managed_wsl2_runtime_health_evidence.json",
        "managed_wsl2_runtime_logs_evidence.json",
        "managed_wsl2_runtime_stop_evidence.json",
        "managed_wsl2_runtime_restart_evidence.json",
        "managed_runtime_log_retention.json",
        "hub_owner_authorization.json",
        "hub_network_boundary_evidence.json",
        "hub_discovery_evidence.json"
    )
    $configNames = @(
        "hub_identity.json",
        "hub_state_manifest.json",
        "hub_runtime_provider.json",
        "managed_wsl2_runtime_artifact_inventory.json",
        "managed_wsl2_runtime_image_bundle_inventory.json",
        "managed_wsl2_runtime_rootfs_inventory.json"
    )

    $manifest = [ordered]@{
        kind = "immoapp_support_bundle_manifest"
        schema_version = 1
        created_at_utc = (Get-Date).ToUniversalTime().ToString("o")
        collector = "installed_powershell_fallback"
        proof_result = "GO"
        appdata_root = $runtimePaths.AppDataRoot
        logs_root = $logsRoot
        config_root = $configRoot
        evidence = [ordered]@{}
        config = [ordered]@{}
        logs = @()
    }

    $fileStream = [System.IO.File]::Open($bundlePath, [System.IO.FileMode]::CreateNew)
    try {
        $zip = [System.IO.Compression.ZipArchive]::new($fileStream, [System.IO.Compression.ZipArchiveMode]::Create)
        try {
            foreach ($name in $evidenceNames) {
                $path = Join-Path $logsRoot $name
                $summary = if ($name -eq "hub_owner_authorization.json") {
                    Read-ImmoAppSupportOwnerAuthorizationSummary -Path $path
                }
                else {
                    Read-ImmoAppSupportJsonSummary -Path $path
                }
                $manifest.evidence[$name] = $summary
                if ([bool]$summary.exists) {
                    Add-ImmoAppSupportZipText -Zip $zip -EntryName "evidence/$name" -Text (($summary.data | ConvertTo-Json -Depth 50) + "`n")
                }
            }
            foreach ($name in $configNames) {
                $path = Join-Path $configRoot $name
                $summary = Read-ImmoAppSupportJsonSummary -Path $path
                $manifest.config[$name] = $summary
                if ([bool]$summary.exists) {
                    Add-ImmoAppSupportZipText -Zip $zip -EntryName "config/$name" -Text (($summary.data | ConvertTo-Json -Depth 50) + "`n")
                }
            }
            foreach ($logPath in Get-ChildItem -LiteralPath $logsRoot -File -Filter "app.log*" -ErrorAction SilentlyContinue) {
                $text = Get-Content -LiteralPath $logPath.FullName -Raw -Encoding UTF8 -ErrorAction SilentlyContinue
                Add-ImmoAppSupportZipText -Zip $zip -EntryName "logs/$($logPath.Name)" -Text (ConvertTo-ImmoAppSupportRedactedText -Value $text)
                $manifest.logs += $logPath.Name
            }
            Add-ImmoAppSupportZipText -Zip $zip -EntryName "manifest.json" -Text (($manifest | ConvertTo-Json -Depth 60) + "`n")
            Add-ImmoAppSupportZipText -Zip $zip -EntryName "README.txt" -Text "ImmoApp installed support bundle. Evidence and logs are sanitized; secrets, passwords, tokens, certificates, and presigned URL values are redacted.`n"
        }
        finally {
            $zip.Dispose()
        }
    }
    finally {
        $fileStream.Dispose()
    }

    $bundleSha = Get-ImmoAppFileSha256 -Path $bundlePath
    $summaryPayload = [ordered]@{
        kind = "immoapp_support_bundle_manifest"
        schema_version = 1
        created_at_utc = $manifest.created_at_utc
        proof_result = "GO"
        collector = "installed_powershell_fallback"
        bundle_path = $bundlePath
        bundle_sha256 = $bundleSha
        support_bundle_path = $bundlePath
        support_bundle_sha256 = $bundleSha
        evidence = $manifest.evidence
        config = $manifest.config
        logs = $manifest.logs
    }
    $summaryPayload | ConvertTo-Json -Depth 80 | Set-Content -LiteralPath $summaryPath -Encoding UTF8
    Write-Output $bundlePath
}

$supportSource = Join-Path (Get-ImmoAppRepoRoot) "app\services\support_bundle.py"
if (-not (Test-Path -LiteralPath $supportSource -PathType Leaf)) {
    New-ImmoAppInstalledSupportBundle -OutputDir $OutputDir
    exit 0
}

$clientPython = Get-ImmoAppVenvPython -Kind client
if (-not (Test-Path $clientPython)) {
    throw "Client venv python not found at $clientPython"
}

$repoRoot = (Get-ImmoAppRepoRoot).Path
$runtimePaths = Get-ImmoAppRuntimePaths
$oldPyPath = $env:PYTHONPATH
$oldAppDataRoot = $env:IMMOAPP_APPDATA_ROOT
$oldOutputDir = $env:IMMOAPP_SUPPORT_BUNDLE_OUTPUT_DIR
$tmpPy = $null
try {
    $env:PYTHONPATH = $repoRoot
    $env:IMMOAPP_APPDATA_ROOT = $runtimePaths.AppDataRoot
    if ($OutputDir) {
        $env:IMMOAPP_SUPPORT_BUNDLE_OUTPUT_DIR = $OutputDir
    }
    $tmpPy = Join-Path $env:TEMP ("immoapp_support_bundle_" + [Guid]::NewGuid().ToString("N") + ".py")
    @'
import os

from app.services.support_bundle import create_support_bundle

output = os.environ.get("IMMOAPP_SUPPORT_BUNDLE_OUTPUT_DIR") or None
path = create_support_bundle(output_dir=output)
print(path)
'@ | Set-Content -Path $tmpPy -Encoding UTF8
    & $clientPython $tmpPy
    if ($LASTEXITCODE -ne 0) {
        throw "Support bundle collection failed."
    }
}
finally {
    if ($null -ne $oldPyPath) { $env:PYTHONPATH = $oldPyPath } else { Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue }
    if ($null -ne $oldAppDataRoot) { $env:IMMOAPP_APPDATA_ROOT = $oldAppDataRoot } else { Remove-Item Env:IMMOAPP_APPDATA_ROOT -ErrorAction SilentlyContinue }
    if ($null -ne $oldOutputDir) { $env:IMMOAPP_SUPPORT_BUNDLE_OUTPUT_DIR = $oldOutputDir } else { Remove-Item Env:IMMOAPP_SUPPORT_BUNDLE_OUTPUT_DIR -ErrorAction SilentlyContinue }
    if ($tmpPy -and (Test-Path $tmpPy)) {
        Remove-Item -Path $tmpPy -Force -ErrorAction SilentlyContinue
    }
}
