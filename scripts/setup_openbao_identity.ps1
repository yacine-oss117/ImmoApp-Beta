param(
    [string]$OperatorUsername = "",
    [string]$OperatorPassword = "",
    [string]$AdminToken = "",
    [string]$AdminTokenFile = "",
    [string]$AppRoleName = "",
    [string]$SecretsPath = "",
    [string]$OutJson = "",
    [switch]$ShowSecrets
)

$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "common.ps1")

Invoke-ImmoAppRuntimePermissionRepairIfNeeded -AutoRepair | Out-Null

$runtimePaths = Ensure-ImmoAppRuntimeLayout
$paths = Ensure-ImmoAppTools
Set-ImmoAppCacheEnv -Paths $paths
Set-ImmoAppSecurityEnv

$bootstrapScript = Join-Path $PSScriptRoot "bootstrap_local_runtime.ps1"
$stackUpInfraCommand = "powershell -NoProfile -ExecutionPolicy Bypass -File scripts/stack.ps1 -Action up-infra -UseWindowsVolumes"
$envFile = Get-ImmoAppDefaultEnvFile
if (-not (Test-Path $envFile)) {
    throw "Canonical env file not found: $envFile. Run '$bootstrapScript' first."
}

Import-ImmoAppEnvFile
Set-ImmoAppHostRuntimeEndpoints

function Protect-SecretFile {
    param([string]$PathValue)

    if ([string]::IsNullOrWhiteSpace($PathValue)) {
        return
    }
    if (-not (Test-Path $PathValue)) {
        return
    }

    $currentSid = Get-ImmoAppDesktopUserSid

    # Use SIDs so this works on localized Windows editions.
    & icacls.exe $PathValue /inheritance:r /grant:r "*$($currentSid):(R,W)" "*S-1-5-18:(F)" "*S-1-5-32-544:(F)" | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Could not protect local secret file: $PathValue"
    }
}

$repoRoot = Get-ImmoAppRepoRoot
if (-not $env:DJANGO_ENV_FILE) {
    $env:DJANGO_ENV_FILE = $envFile
}

if ([string]::IsNullOrWhiteSpace($OperatorUsername)) {
    if (-not [string]::IsNullOrWhiteSpace($env:OPENBAO_OPERATOR_USERNAME)) {
        $OperatorUsername = $env:OPENBAO_OPERATOR_USERNAME
    }
}
if ([string]::IsNullOrWhiteSpace($OperatorUsername)) {
    $OperatorUsername = Read-Host "OpenBao operator username"
}
if ([string]::IsNullOrWhiteSpace($OperatorUsername)) {
    throw "Operator username is required."
}

if ([string]::IsNullOrWhiteSpace($SecretsPath)) {
    $envName = if ($env:IMMOAPP_ENV) { $env:IMMOAPP_ENV.ToLower() } elseif ($env:DJANGO_DEBUG -eq "1") { "dev" } else { "prod" }
    $SecretsPath = if ($env:IMMOAPP_SECRETS_PATH) { $env:IMMOAPP_SECRETS_PATH } else { "secret/data/immoapp/$envName" }
}

if ([string]::IsNullOrWhiteSpace($AppRoleName)) {
    $envName = if ($env:IMMOAPP_ENV) { $env:IMMOAPP_ENV.ToLower() } elseif ($env:DJANGO_DEBUG -eq "1") { "dev" } else { "prod" }
    $AppRoleName = "immoapp-server-$envName"
}

if ([string]::IsNullOrWhiteSpace($OutJson)) {
    $OutJson = $runtimePaths.OpenBaoAppRoleFile
}

if (-not [string]::IsNullOrWhiteSpace($AdminToken)) {
    throw "Policy violation: AdminToken must remain empty. Use AdminTokenFile only."
}
if (-not [string]::IsNullOrWhiteSpace($env:BAO_TOKEN)) {
    throw "Policy violation: BAO_TOKEN must remain empty. Use BAO_TOKEN_FILE only."
}
if ([string]::IsNullOrWhiteSpace($AdminTokenFile)) {
    if (-not [string]::IsNullOrWhiteSpace($env:BAO_TOKEN_FILE)) {
        $AdminTokenFile = $env:BAO_TOKEN_FILE
    } else {
        $AdminTokenFile = $runtimePaths.OpenBaoTokenFile
    }
}
if (-not (Test-Path $AdminTokenFile)) {
    throw "OpenBao admin token file not found: $AdminTokenFile. Run '$bootstrapScript' first, then run '$stackUpInfraCommand'."
}
Protect-SecretFile -PathValue $AdminTokenFile

$openBaoAddr = Get-ImmoAppHostOpenBaoAddr -EnvFilePath $envFile
if (-not (Test-ImmoAppOpenBaoHostReachable -Addr $openBaoAddr)) {
    throw "OpenBao is not reachable at $openBaoAddr. Run '$bootstrapScript' first, then run '$stackUpInfraCommand'."
}

$plainPwd = $OperatorPassword
if ([string]::IsNullOrWhiteSpace($plainPwd)) {
    if (-not [string]::IsNullOrWhiteSpace($env:OPENBAO_OPERATOR_PASSWORD)) {
        $plainPwd = $env:OPENBAO_OPERATOR_PASSWORD
    }
}
if ([string]::IsNullOrWhiteSpace($plainPwd)) {
    $securePwd = Read-Host "OpenBao operator password" -AsSecureString
    $plainPwd = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
        [Runtime.InteropServices.Marshal]::SecureStringToBSTR($securePwd)
    )
}
if ([string]::IsNullOrWhiteSpace($plainPwd)) {
    throw "Operator password is required."
}

$env:PYTHONPATH = $repoRoot
$env:OPENBAO_OPERATOR_PASSWORD = $plainPwd

$python = Assert-ImmoAppVenvPython -Kind server -Purpose "running scripts/setup_openbao_identity.ps1"
$pycacheArg = "pycache_prefix=$($paths.Pycache)"
$args = @(
    "-X", $pycacheArg,
    "scripts/bootstrap_openbao_identity.py",
    "--operator-username", $OperatorUsername,
    "--app-role-name", $AppRoleName,
    "--secrets-path", $SecretsPath,
    "--out-json", $OutJson
)
if (-not [string]::IsNullOrWhiteSpace($AdminTokenFile)) {
    $args += @("--admin-token-file", $AdminTokenFile)
}
if ($ShowSecrets) {
    $args += "--show-secrets"
}

try {
    & $python @args
}
finally {
    Remove-Item Env:OPENBAO_OPERATOR_PASSWORD -ErrorAction SilentlyContinue
}

Write-Host "setup_openbao_identity: complete."
Write-Host "Credentials file: $OutJson"
Protect-SecretFile -PathValue $OutJson
